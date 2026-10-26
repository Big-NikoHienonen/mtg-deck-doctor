"""Building a deck with the Doctor, one phase at a time.

A build is a session the player moves through, stored on disk so it survives a
reload and a restart:

1. **brief** — the optional form answers and the player's own words, read by the
   Doctor (`interpret_deck_request`; the form's answers win);
2. **commander** — the Doctor offers up to three that support the plan (or the
   player already chose one);
3. **plan** — the Doctor decides which phases the deck needs, in what order, and how
   many cards each fills: a creature deck builds its creatures first, a spells deck
   its spells, lands come once the colored costs are known;
4. **phases** — for each, in that order, the Doctor proposes cards from EDHREC's data
   for the commander; the player keeps or replaces them and locks the phase in;
5. **review** — the whole list, then the deck is made, with the Doctor's account of
   each phase as the first messages of its Correspondence tab.

The model proposes; the rules decide. Every card it names must be on the candidate
list, which is already limited to what is legal and in the commander's colors; the
Game Changer limit, the singleton rule and the budget are enforced here, not asked
of the model. While the player reviews a phase, the next is already being prepared
on the assumption they keep what was proposed, and redone if they don't.
"""

import hashlib
import json
import logging
import os
import random
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import anthropic

from mtg_deck_doctor import ai_errors, wizard
from mtg_deck_doctor.card_cache import BASIC_LAND_NAMES, get_card_info, get_card_info_batch
from mtg_deck_doctor.edhrec import get_commander_includes
from mtg_deck_doctor.commander_search import scryfall_candidates, with_edhrec
from mtg_deck_doctor.tool_loop import (
    PHASE_KINDS,
    StructuredLoopError,
    interpret_deck_request,
    plan_commander_search,
    plan_phases,
    propose_commanders,
    propose_phase,
)

logger = logging.getLogger(__name__)

BUILDS_DIR = Path("data/builds")
DECK_SIZE = 99
_NO_WORDS = "(they added nothing in their own words)"
_ORACLE_CHARS = 130
# A phase may run over its share of the budget by this much before cards are dropped.
_BUDGET_SLACK = 1.5
# At least this many commanders to choose between, from a menu of up to _MENU_SIZE.
_MIN_OPTIONS = 3
_MENU_SIZE = 9
# For a request that names no colors and gives the Doctor nothing to choose them by.
_SURPRISE_COMBOS = ["R", "G", "B", "U", "W", "BR", "RG", "BG", "UB", "WU", "WB", "UR", "RW", "GW", "GU"]
_BASIC_FOR_COLOR = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}


class BuildError(Exception):
    """A request that can't go ahead, with the HTTP status and message to show."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


# -- storage ---------------------------------------------------------------------

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def _lock(build_id: str) -> threading.RLock:
    with _locks_guard:
        return _locks.setdefault(build_id, threading.RLock())


def _path(build_id: str) -> Path:
    return BUILDS_DIR / f"{build_id}.json"


def load(build_id: str) -> dict | None:
    path = _path(build_id)
    if not build_id.isalnum() or not path.exists():
        return None
    return json.loads(path.read_text())


def _save(session: dict) -> None:
    BUILDS_DIR.mkdir(parents=True, exist_ok=True)
    session["updated_at"] = time.time()
    tmp = _path(session["id"]).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(session))
    os.replace(tmp, _path(session["id"]))


def session_lock(build_id: str) -> threading.RLock:
    """The lock that makes changes to one build one at a time."""
    return _lock(build_id)


def get(build_id: str) -> dict:
    """The stored session, or a 404 BuildError."""
    return _get(build_id)


def _get(build_id: str) -> dict:
    session = load(build_id)
    if session is None:
        raise BuildError(404, "That build isn't here any more. Start a new one.")
    return session


def _update(build_id: str, change) -> dict:
    """Loads the session, applies `change(session)`, saves, all under its lock."""
    with _lock(build_id):
        session = _get(build_id)
        change(session)
        _save(session)
        return session


# -- running steps in the background ------------------------------------------------


def _fail(build_id: str, status: int, body: dict, retry: dict | None) -> None:
    def change(s: dict) -> None:
        s["busy"] = None
        s["error"] = {"status": status, **body, "retry": retry}

    try:
        _update(build_id, change)
    except BuildError:
        pass


def _run(build_id: str, retry: dict | None, step) -> None:
    """Runs `step()` in the background. A failure is recorded on the session, with
    how to retry it, for the page to show."""

    def work() -> None:
        try:
            step()
        except BuildError as err:
            _fail(build_id, err.status, {"detail": err.detail, "code": "build_error"}, retry)
        except StructuredLoopError:
            _fail(build_id, 502, {"detail": "The Doctor didn't finish thinking that through.", "code": "build_error"}, retry)
        except anthropic.APIError as err:
            status, body = ai_errors.describe(err)
            _fail(build_id, status, body, retry)
        except Exception:
            logger.exception("build step failed")
            _fail(build_id, 500, {"detail": "Something went wrong on the Doctor's side.", "code": "build_error"}, retry)

    threading.Thread(target=work, daemon=True).start()


_MAX_STEPS = 30


def _note(s: dict, label: str, during: str) -> None:
    """Records what the Doctor is doing now (`during`: the step it belongs to)."""
    s["busy"] = label
    s["steps"] = [*s.get("steps", []), {"during": during, "label": label}][-_MAX_STEPS:]


def _label(build_id: str, label: str, during: str) -> None:
    _update(build_id, lambda s: _note(s, label, during))


def _begin_step(build_id: str, label: str, retry: dict) -> None:
    def change(s: dict) -> None:
        s["error"] = None
        s["retry"] = retry
        # A step run again starts its log afresh.
        s["steps"] = [x for x in s.get("steps", []) if x["during"] != retry["op"]]
        _note(s, label, retry["op"])

    _update(build_id, change)


def _end_step(s: dict) -> None:
    s["busy"], s["retry"] = None, None


# -- the brief and the commander ------------------------------------------------------


def create(brief: dict) -> str:
    """Starts a build from the form's answers and the player's words; returns its id."""
    build_id = uuid.uuid4().hex[:10]
    _save(
        {
            "id": build_id,
            "created_at": time.time(),
            "brief": brief,
            "stage": "reading",
            "busy": None,
            # What the Doctor has been doing, in order, for the page to show as it goes.
            "steps": [],
            "error": None,
            "retry": None,
            "resolved": None,
            "commander_options": [],
            # What the Doctor has learnt about the commander wanted, and how the rounds went.
            "facts": [],
            "rounds": [],
            "rejected": [],
            "liked": [],
            "commander": None,
            "plan": None,
            "phases": {},
            "current": None,
            "deck": {"locked": []},
            "pool": [],
            "deck_id": None,
        }
    )
    _dispatch(build_id, "start")
    return build_id


def _dispatch(build_id: str, op: str, **args) -> None:
    """Starts one of the steps that run in the background."""
    labels = {
        "start": "Reading what you asked for…",
        "refine": "Taking in what you said…",
        "plan": "Planning how to build it…",
    }
    retry = {"op": op, **args}
    _begin_step(build_id, labels[op], retry)
    steps = {
        "start": lambda: _step_start(build_id),
        "refine": lambda: _step_commanders(build_id, "refine", **args),
        "plan": lambda: _step_plan(build_id),
    }
    _run(build_id, retry, steps[op])


def _answers(s: dict) -> str:
    """What the player has settled, as a sentence: colors, style, power level, budget — only
    what they actually chose, never a default, so the Doctor doesn't take a default for a wish."""
    r = s["resolved"]
    parts = []
    if r["colors"]:
        parts.append("colours " + ", ".join(wizard._COLOR_WORDS[c] for c in wizard.canonical_colors("".join(r["colors"]))))
    elif r["colorless"]:
        parts.append("colourless")
    if r["theme"]:
        parts.append(f"style: {r['theme'].replace('-', ' ')}")
    if r.get("bracket_chosen"):
        parts.append(f"power level: {wizard._BRACKET_LABELS[r['bracket']]} (level {r['bracket']})")
    if r.get("budget_stated"):
        parts.append(f"budget: up to ${r['budget']:,.0f}" if r["budget"] else "budget: no limit")
    if r["niche"]:
        parts.append("wants lesser-known commanders, not the most popular ones")
    return "; ".join(parts) or "nothing chosen on the form"


def _brief_text(s: dict) -> str:
    """The brief as the model reads it: the answers, the player's words, what the
    Doctor made of them, and the commander once there is one."""
    parts = [
        f"The player's answers: {_answers(s)}.",
        f"In their own words: {(s['brief'].get('text') or '').strip() or _NO_WORDS}",
    ]
    r = s["resolved"]
    if r["focus"]:
        parts.append(f"What that comes to: {r['focus']}")
    if s["commander"]:
        parts.append(f"The commander chosen: {s['commander']['name']}.")
    return "\n".join(parts)


def _in_words(combos: list[str]) -> str:
    """Colour combinations for people: "red, black-red and blue-red-green"."""
    words = ["-".join(wizard._COLOR_WORDS[c] for c in combo) if combo else "colorless" for combo in combos]
    return ", ".join(words[:-1]) + (" and " if len(words) > 1 else "") + words[-1] if words else ""


def _menu_for(combo: str, themes: list[str | None], bracket: int, niche: bool) -> list[dict] | None:
    """The commanders worth considering in one colour combination: the first of `themes`
    (an EDHREC theme, or None for none) that has any, topped up from the colors alone when
    that leaves too few to choose between. None if EDHREC couldn't be reached."""
    rows: list[dict] = []
    reached = False
    for theme in themes:
        result = wizard.candidates(combo, theme, bracket, niche)
        if result["unavailable"]:
            continue
        reached = True
        if theme is None:
            return result["commanders"]
        if result["commanders"] and not result["fell_back_from"]:
            rows = result["commanders"]
            break
    if not reached:
        return None
    if len(rows) < _MIN_OPTIONS:
        plain = wizard.candidates(combo, None, bracket, niche)
        known = {c["name"] for c in rows}
        rows = [*rows, *[c for c in plain["commanders"] if c["name"] not in known]][:_MENU_SIZE]
    return rows


def _interleave(lists: list[list[dict]], limit: int) -> list[dict]:
    """Up to `limit` commanders drawn in turn from each list, so every colour combination
    is represented, with no commander twice."""
    out: list[dict] = []
    seen: set[str] = set()
    for i in range(max((len(x) for x in lists), default=0)):
        for rows in lists:
            if i < len(rows) and rows[i]["name"] not in seen and len(out) < limit:
                out.append(rows[i])
                seen.add(rows[i]["name"])
    return out


def _step_start(build_id: str) -> None:
    s = _get(build_id)
    brief = s["brief"]
    text = (brief.get("text") or "").strip()
    given = {
        "commander": brief.get("commander"),
        "colors": brief.get("colors") or [],
        "colorless": bool(brief.get("colorless")),
        "style": brief.get("theme"),
        "power": brief.get("bracket"),
        "budget": brief.get("budget"),
        "lesser_known": bool(brief.get("lesser_known")),
    }
    read = interpret_deck_request(text or _NO_WORDS, brief["styles"], given)

    # The form's answers win; the Doctor fills in what was left open.
    colors = given["colors"] or read["colors"]
    budget_value = given["budget"] if given["budget"] is not None else read["budget"]
    resolved = {
        "colors": colors,
        "colorless": given["colorless"] or (read["colorless"] and not colors),
        "theme": given["style"] or read["style"],
        "bracket": given["power"] or read["power"] or 2,
        # Whether the player (or their words) actually settled these, or they are only defaults.
        "bracket_chosen": bool(given["power"] or read["power"]),
        "budget_stated": budget_value is not None,
        "budget": None if budget_value in (None, "none") else float(budget_value),
        "niche": given["lesser_known"] or read["lesser_known"],
        "focus": read["focus"],
        "understood": read["understood"],
        "color_options": read["color_options"],
        "theme_hints": read["theme_hints"],
        "notes": [],
    }
    commander = given["commander"]
    if not commander and read["commander"]:
        found = wizard.resolve_commander(read["commander"])
        if found:
            commander = found["name"]
        else:
            resolved["notes"].append(f"I couldn't use “{read['commander']}” as a commander, so I'll offer some.")

    def change(s: dict) -> None:
        s["resolved"] = resolved

    _update(build_id, change)

    if commander:
        _set_commander(build_id, commander, None)
        _step_plan(build_id)
        return
    _step_commanders(build_id, "start")


def _step_commanders(
    build_id: str,
    during: str,
    said: str | None = None,
    reject: list[dict] | None = None,
    like: list[str] | None = None,
    drop: list[str] | None = None,
) -> None:
    """One round of finding the commander. The Doctor updates what it knows (the facts) from
    what the player has said — `said`, commanders they `reject` ({"name", "reason"}) or `like`,
    facts they `drop` — turns the facts into Scryfall searches, checks what they find against
    EDHREC, and offers the closest. A round that finds nothing leaves the last one as it was."""
    s = _get(build_id)
    resolved = s["resolved"]
    rejected = [*s["rejected"], *[r for r in (reject or []) if r["name"] not in {x["name"] for x in s["rejected"]}]]
    liked = list(dict.fromkeys([*s["liked"], *(like or [])]))
    facts_in = [f for f in s["facts"] if f not in (drop or [])]
    offered_before = [o["name"] for o in s["commander_options"]]

    _label(build_id, "Working out what to look for…", during)
    plan = plan_commander_search(_brief_text(s), facts_in, said, rejected, liked, offered_before)

    # The colors the commander must have exactly (a Rakdos deck is black-red, not mono-black or
    # mono-red): the Doctor's read of the facts, or, the first time, what the player chose.
    # Whatever the searches wrote, only these come through.
    fixed = [wizard.canonical_colors(c) for c in plan["colors"]]
    if not fixed and not s["rounds"]:
        fixed = [wizard.canonical_colors("".join(resolved["colors"]))] if resolved["colors"] else [""] if resolved["colorless"] else []
    # Colors to fall back on when the searches find too little: those, or the Doctor's guesses.
    if fixed:
        combos = fixed[:3]
    else:
        combos = [wizard.canonical_colors(c) for c in (plan["color_options"] or resolved.get("color_options") or [])][:3] or random.sample(_SURPRISE_COMBOS, 3)
    themes = [resolved["theme"]] if resolved["theme"] else [*plan["theme_hints"], *resolved.get("theme_hints", []), None]

    _label(build_id, f"Searching: {' · '.join(q['why'] or q['q'] for q in plan['queries']) or 'the best-known commanders'}…", during)
    gone = {r["name"] for r in rejected}
    found = [c for c in scryfall_candidates([q["q"] for q in plan["queries"]]) if c["name"] not in gone and (not fixed or c["colors"] in fixed)]
    rows = with_edhrec(found, resolved["bracket"])
    matched, topped_up = len(rows), None
    if len(rows) < _MIN_OPTIONS * 2:
        # Too little from the searches: add what EDHREC shows for the likely colors.
        topped_up = _in_words(combos)
        _label(build_id, f"Adding the best-known in {topped_up}…", during)
        with ThreadPoolExecutor(max_workers=3) as pool:
            menus = list(pool.map(lambda c: _menu_for(c, themes, resolved["bracket"], resolved["niche"]), combos))
        extra = [c for c in _interleave([m for m in menus if m], _MENU_SIZE) if c["name"] not in gone and all(c["name"] != r["name"] for r in rows)]
        if all(m is None for m in menus) and not rows:
            raise BuildError(502, "Couldn't reach EDHREC to look at commanders. Try again in a moment.")
        rows = [*rows, *extra]
    if not rows:
        raise BuildError(422, "Nothing matched all of that. Take one of the facts away (the chips above) or say it differently.")
    rows = rows[: _MENU_SIZE + 6]

    context = wizard.explain_context({"commanders": rows})
    _label(build_id, f"Choosing the closest of {len(rows)} to what you want…", during)
    # What the Doctor works from: the facts it has, or — before it has any — the brief.
    offered = propose_commanders(_brief_text(_get(build_id)), plan["facts"], context, rejected, liked)
    by_name = {c["name"]: c for c in rows}
    colors_of = {c["name"]: c.get("colors", "") for c in context}
    said_about = {o["name"]: o for o in offered}
    names = [o["name"] for o in offered] or [c["name"] for c in rows[:3]]
    options = [
        {
            "name": n,
            "id": by_name[n]["id"],
            "why": (said_about.get(n) or {}).get("why"),
            "fits": (said_about.get(n) or {}).get("fits", []),
            "misses": (said_about.get(n) or {}).get("misses", []),
            "colors": colors_of.get(n, ""),
            "num_decks": by_name[n]["num_decks"],
            "decks_at_bracket": by_name[n]["decks_at_bracket"],
            "themes": [t["name"] for t in by_name[n]["themes"][:4]],
            "signature": by_name[n]["signature"][:4],
        }
        for n in names
    ]

    def offer(s: dict) -> None:
        s["commander_options"], s["stage"] = options, "commander"
        s["facts"], s["rejected"], s["liked"] = plan["facts"], rejected, liked
        s["rounds"] = [
            *s["rounds"],
            {
                "said": (said or "").strip() or None,
                "rejected": [r["name"] for r in (reject or [])],
                "liked": list(like or []),
                "understood": plan["understood"],
                "facts": plan["facts"],
                "colors": fixed,
                "considered": len(rows),
                # How many the searches found, and the colors the rest were added from, if any.
                "matched": matched,
                "topped_up": topped_up,
                "options": names,
            },
        ]
        _end_step(s)

    _update(build_id, offer)


def refine_commanders(build_id: str, said: str, reject: list[dict], like: list[str], drop: list[str]) -> None:
    """The player's answer to the commanders offered: more about what they want, a commander
    that isn't it (and why), one that is close, or a fact to take back. Starts another round."""
    with _lock(build_id):
        s = _get(build_id)
        if s["stage"] != "commander":
            raise BuildError(409, "The commander isn't being chosen now.")
        if s["busy"]:
            raise BuildError(409, "The Doctor is still working on the last step.")
        offered = {o["name"] for o in s["commander_options"]}
        reject = [{"name": r["name"], "reason": (r.get("reason") or "").strip()[:200]} for r in reject if r["name"] in offered]
        like = [n for n in like if n in offered]
        drop = [f for f in drop if f in s["facts"]]
        if not (said.strip() or reject or like or drop):
            raise BuildError(400, "Say what's right or wrong about these, reject one, or ask for more like another.")
    _dispatch(build_id, "refine", said=said.strip() or None, reject=reject, like=like, drop=drop)


def _set_commander(build_id: str, name: str, why: str | None) -> None:
    info = get_card_info(name)
    if info is None:
        raise BuildError(400, f"No card named {name!r} found, or Scryfall couldn't be reached right now.")
    type_line, text = info.get("typeLine") or "", (info.get("oracleText") or "").lower()
    if info.get("legality") != "legal" or not (("Legendary" in type_line and "Creature" in type_line) or "can be your commander" in text):
        raise BuildError(400, f"{name} can't be a commander in Commander.")
    commander = {
        "name": info.get("name") or name,
        "id": info.get("id"),
        "why": why,
        "oracle": (info.get("oracleText") or "").replace("\n", " ")[:600],
        "colors": info.get("colorIdentity", []),
        "price": float(info.get("priceUsd") or 0),
    }

    def change(s: dict) -> None:
        s["commander"], s["stage"] = commander, "planning"

    _update(build_id, change)


def choose_commander(build_id: str, name: str) -> None:
    """The player's choice of commander: one the Doctor offered, or any other legal one."""
    with _lock(build_id):
        s = _get(build_id)
        if s["stage"] != "commander":
            raise BuildError(409, "The commander is already chosen.")
        if s["busy"]:
            raise BuildError(409, "The Doctor is still working on the last step.")
        offered = next((o for o in s["commander_options"] if o["name"] == name), None)
    if offered is None:
        found = wizard.resolve_commander(name)
        if found is None:
            raise BuildError(400, f"{name!r} can't be used as a commander.")
        name = found["name"]
    _set_commander(build_id, name, offered["why"] if offered else None)
    _dispatch(build_id, "plan")


# -- the plan ---------------------------------------------------------------------------


def _constraints(s: dict) -> str:
    r, caps = s["resolved"], s["brief"].get("caps") or {}
    parts = [f"power level {wizard._BRACKET_LABELS[r['bracket']]} ({r['bracket']} of 4)"]
    limit = wizard.GAME_CHANGER_LIMITS.get(r["bracket"])
    parts.append("no Game Changers" if limit == 0 else f"at most {limit} Game Changers" if limit else "Game Changers allowed")
    parts.append(f"budget ${r['budget']:,.0f} for the whole deck" if r["budget"] else "no budget limit")
    parts += [f"{wizard.AREAS[a].lower()} may cost at most ${cap:,.0f}" for a, cap in caps.items()]
    parts += [f"spend more on {wizard.AREAS[a].lower()}" for a in s["brief"].get("invest") or []]
    return "; ".join(parts) + "."


def _build_pool(commander: dict, bracket: int) -> list[dict]:
    """The cards EDHREC players run with this commander that could go in the deck —
    legal, in its colors, not the commander — with what the model needs to judge
    them."""
    includes = get_commander_includes(commander["name"])
    if not includes.get("available"):
        raise BuildError(502, f"EDHREC has no data for {commander['name']}, so there is nothing to build its deck from. Choose another commander.")
    cards = [c for c in includes["cards"] if c["name"] != commander["name"]]
    infos = get_card_info_batch([c["name"] for c in cards])["info"]
    game_changers = wizard.game_changer_names() or set()
    pool = []
    for c in cards:
        info = infos.get(c["name"])
        if info is None or info.get("legality") != "legal" or not set(info.get("colorIdentity", [])) <= set(commander["colors"]):
            continue
        type_line = info.get("typeLine") or ""
        pool.append(
            {
                "name": c["name"],
                "id": info.get("id"),
                "category": c["category"],
                "type": type_line,
                "land": "Land" in type_line,
                "cmc": float(info.get("cmc") or 0),
                "cost": info.get("manaCost") or "",
                "price": float(info.get("priceUsd") or 0),
                "inclusion": c["inclusion"],
                "gc": c["name"] in game_changers,
                "oracle": (info.get("oracleText") or "").replace("\n", " ")[:_ORACLE_CHARS],
            }
        )
    return pool


def _step_plan(build_id: str) -> None:
    s = _get(build_id)
    commander = s["commander"]
    _label(build_id, f"Reading what players run with {commander['name'].split(',')[0]}…", "plan")
    pool = _build_pool(commander, s["resolved"]["bracket"])
    _label(build_id, f"Deciding the phases and their order, from {len(pool)} cards that could go in…", "plan")
    plan = plan_phases(_brief_text(s), commander, _constraints(s))
    phases = []
    for p in plan["phases"]:
        label, goal = PHASE_KINDS[p["kind"]]
        phases.append({"id": p["kind"], "kind": p["kind"], "label": label, "goal": goal, "count": p["count"], "why": p["why"]})

    def change(s: dict) -> None:
        s["pool"] = pool
        s["plan"] = {"strategy": plan["strategy"], "order_reason": plan["order_reason"], "phases": phases}
        s["phases"] = {p["id"]: {"status": "pending", "proposal": None, "gen": 0, "working_gen": None, "working_based_on": None, "locked": []} for p in phases}
        s["stage"], s["current"] = "plan", None
        _end_step(s)

    _update(build_id, change)


# -- the phases ---------------------------------------------------------------------------


def _hash(names: set[str]) -> str:
    return hashlib.sha1(json.dumps(sorted(names)).encode()).hexdigest()[:12]


def _locked_names(s: dict) -> set[str]:
    return {e["name"] for e in s["deck"]["locked"]}


def _locked_count(s: dict) -> int:
    return sum(e["qty"] for e in s["deck"]["locked"])


def _pips(names: list[str], pool_by_name: dict) -> Counter:
    counts: Counter = Counter()
    for name in names:
        cost = (pool_by_name.get(name) or {}).get("cost", "")
        for symbol in cost.replace("{", " ").replace("}", " ").split():
            for color in symbol.split("/"):
                if color in "WUBRG" and len(color) == 1:
                    counts[color] += 1
    return counts


def _basics_for(count: int, colors: list[str], pips: Counter) -> dict[str, int]:
    """`count` basic lands split among the commander's colors by how much of each the
    deck's cards ask for (a little weight to every color, so none is left with
    none), largest remainder."""
    if count <= 0:
        return {}
    wanted = [c for c in colors if c in _BASIC_FOR_COLOR] or []
    if not wanted:
        return {"Wastes": count}
    weights = {c: pips[c] + 1 for c in wanted}
    total = sum(weights.values())
    shares = {c: count * w / total for c, w in weights.items()}
    result = {c: int(v) for c, v in shares.items()}
    for c in sorted(shares, key=lambda c: shares[c] - result[c], reverse=True)[: count - sum(result.values())]:
        result[c] += 1
    return {_BASIC_FOR_COLOR[c]: n for c, n in result.items() if n}


def _budget(s: dict, phase: dict, take: int, taken: set[str], pool_by_name: dict, slots_left: int, fixed_price: float) -> tuple[str, float | None]:
    """The money guidance for choosing `take` more cards for a phase, in words, and the
    most those picks may cost in all (None for no limit). `taken` is everything
    already in the deck, assumed or kept for this phase (their prices are spent
    already), `slots_left` the places still to fill, `fixed_price` what the phase's
    own kept cards cost. A spending limit the player set on lands or mana rocks is
    that phase's limit in all; otherwise the phase gets its share of what's left of
    the budget, with some room."""
    caps = s["brief"].get("caps") or {}
    kind = phase["kind"]
    capped = {"lands": "lands", "ramp": "rocks"}.get(kind)
    if capped and capped in caps:
        room = max(float(caps[capped]) - fixed_price, 0)
        return f"The player wants the {capped if capped == 'lands' else 'mana rocks'} to cost at most ${caps[capped]:,.0f} in all; ${room:,.0f} of that is left.", room
    budget = s["resolved"]["budget"]
    if not budget:
        return "No limit.", None
    spent = s["commander"]["price"] + sum(pool_by_name[n]["price"] for n in taken if n in pool_by_name)
    left = max(budget - spent, 0)
    share = left * take / max(slots_left, 1)
    # Some room over the phase's share, but never more than is left.
    limit = min(share * _BUDGET_SLACK, left)
    return (
        f"The deck's budget is ${budget:,.0f} in all, with ${left:,.0f} left. Spend about ${share:,.0f} on this phase "
        f"(no more than ${limit:,.0f}); cheap cards are good cards here.",
        limit,
    )


def _deck_lines(s: dict, assumed: list[str]) -> list[str]:
    by_phase: dict[str, list[str]] = {}
    for e in s["deck"]["locked"]:
        by_phase.setdefault(e["phase"], []).append(e["name"] if e["qty"] == 1 else f"{e['name']} ×{e['qty']}")
    lines = [f"{PHASE_KINDS[p][0]}: {', '.join(names)}" for p, names in by_phase.items()]
    if assumed:
        lines.append(f"(being chosen with this phase: {', '.join(assumed)})")
    return lines


def _card_entry(c: dict, why: str) -> dict:
    return {"name": c["name"], "id": c["id"], "why": why, "price": c["price"], "category": c["category"], "type": c["type"], "cmc": c["cmc"]}


def _step_phase(build_id: str, phase_id: str, gen: int, note: str, exclude: list[str], fixed: list[dict], assumed: list[str]) -> None:
    """Makes the proposal for one phase and stores it, unless a newer attempt at the
    same phase has superseded this one meanwhile. `fixed` are cards the player kept
    from an earlier proposal (they stay, and count toward the phase); `assumed` are
    cards being chosen in the phase before this one, taken as kept."""
    s = _get(build_id)
    plan_phase = next(p for p in s["plan"]["phases"] if p["id"] == phase_id)
    r, commander = s["resolved"], s["commander"]
    pool_by_name = {c["name"]: c for c in s["pool"]}
    fixed_names = [f["name"] for f in fixed]
    taken = _locked_names(s) | set(assumed) | set(fixed_names)
    based_on = _hash(_locked_names(s) | set(assumed))

    lands = plan_phase["kind"] == "lands"
    count = plan_phase["count"]
    if plan_phase["kind"] == "flex":
        count = max(DECK_SIZE - _locked_count(s) - len(assumed), 0)

    # What may be chosen: not already in the deck, not turned down, of the right
    # kind, and not a Game Changer the bracket's limit has no room for.
    limit = wizard.GAME_CHANGER_LIMITS.get(r["bracket"])
    gc_used = sum(1 for n in taken if (pool_by_name.get(n) or {}).get("gc"))
    refused = set(exclude)
    available = [
        c
        for c in s["pool"]
        if c["name"] not in taken and c["name"] not in refused and c["land"] == lands and not (limit is not None and c["gc"] and gc_used >= limit)
    ]

    if lands:
        room = max(count - len(commander["colors"]), 0) - len([n for n in fixed_names])
        take = max(room, 0)
    else:
        take = max(count - len(fixed), 0)

    notes: list[str] = []
    result = {"summary": "", "picks": []}
    if take > 0 and available:
        budget_text, hard_limit = _budget(
            s, plan_phase, take, taken, pool_by_name, DECK_SIZE - _locked_count(s) - len(assumed) - len(fixed), sum(f["price"] for f in fixed)
        )
        result = propose_phase(
            _brief_text(s),
            commander,
            plan_phase,
            _deck_lines(s, assumed),
            available,
            _constraints(s),
            budget_text,
            note,
            take,
        )
    else:
        hard_limit = None

    picks = [_card_entry(pool_by_name[p["name"]], p["why"]) for p in result["picks"]]
    # Game Changers past the limit, and money past the phase's room, are dropped here.
    if limit is not None:
        kept, used = [], gc_used
        for c in picks:
            if pool_by_name[c["name"]]["gc"]:
                if used >= limit:
                    notes.append(f"Left out {c['name']}: this power level allows {limit} Game Changers.")
                    continue
                used += 1
            kept.append(c)
        picks = kept
    if hard_limit is not None:
        while picks and sum(c["price"] for c in picks) > hard_limit:
            dearest = max(picks, key=lambda c: c["price"])
            picks.remove(dearest)
            notes.append(f"Left out {dearest['name']} (${dearest['price']:.0f}): it didn't fit this phase's share of the budget.")

    cards = [*fixed, *picks]
    # With some cards kept, the model's summary covers only the new ones; the
    # phase keeps the summary it had.
    summary = (s["phases"][phase_id].get("summary_hint") if fixed else None) or result["summary"]
    proposal = {
        "summary": summary,
        "cards": cards,
        "count": count,
        "notes": notes,
        "based_on": based_on,
        "basics": None,
    }
    if lands:
        everyone = _locked_names(s) | set(assumed) | {c["name"] for c in cards}
        proposal["basics"] = _basics_for(count - len(cards), commander["colors"], _pips(list(everyone), pool_by_name))

    def change(s: dict) -> None:
        phase = s["phases"][phase_id]
        if phase["working_gen"] != gen:
            return  # a newer attempt has taken over
        phase.update(proposal=proposal, working_gen=None, working_based_on=None, status="ready")
        if s["error"] and (s["error"].get("retry") or {}).get("phase") == phase_id:
            s["error"] = None
        if s["stage"] == "building" and (launch := _prefetch_next(s, phase_id)):
            launches.append(launch)

    launches: list = []
    _update(build_id, change)
    # Only once the change is saved: a step reads the session as it is on disk.
    for launch in launches:
        launch()


def _next_phase_id(s: dict, after: str) -> str | None:
    ids = [p["id"] for p in s["plan"]["phases"]]
    later = ids[ids.index(after) + 1 :]
    return next((i for i in later if s["phases"][i]["status"] != "locked"), None)


def _prefetch_next(s: dict, phase_id: str):
    """Called with the session lock held and `s` about to be saved: prepares the phase
    after `phase_id`, assuming the player keeps what was proposed. Returns what
    starts it, to be called once `s` is saved, or None if there is nothing to do."""
    following = _next_phase_id(s, phase_id)
    if following is None or s["current"] != phase_id:
        return None
    nxt = s["phases"][following]
    if nxt["proposal"] is not None or nxt["working_gen"] is not None:
        return None
    assumed = [c["name"] for c in s["phases"][phase_id]["proposal"]["cards"]]
    return _prepare_phase(s, following, "", [], [], assumed, foreground=False)


def _prepare_phase(s: dict, phase_id: str, note: str, exclude: list[str], fixed: list[dict], assumed: list[str], foreground: bool):
    """Marks a phase as being worked on and returns what starts the Doctor on its
    proposal. Changes `s`; the caller saves it, and only then calls the result — the
    work reads the session from disk. A foreground attempt that fails is shown to
    the player with a way to retry; a prefetch that fails is dropped quietly and
    redone when the phase comes up."""
    phase = s["phases"][phase_id]
    phase["gen"] += 1
    gen = phase["gen"]
    phase["working_gen"] = gen
    phase["working_based_on"] = _hash(_locked_names(s) | set(assumed))
    build_id = s["id"]
    retry = {"op": "phase", "phase": phase_id, "note": note, "exclude": exclude, "fixed": fixed}

    def step() -> None:
        try:
            _step_phase(build_id, phase_id, gen, note, exclude, fixed, assumed)
        except BaseException:
            def clear(s2: dict) -> None:
                if s2["phases"][phase_id]["working_gen"] == gen:
                    s2["phases"][phase_id]["working_gen"] = None

            try:
                _update(build_id, clear)
            except BuildError:
                pass
            if foreground:
                raise

    if foreground:
        s["error"] = None
        return lambda: _run(build_id, retry, step)

    def quiet() -> None:
        try:
            step()
        except Exception:
            logger.info("prefetch of %s failed", phase_id, exc_info=True)

    return lambda: threading.Thread(target=quiet, daemon=True).start()


def begin(build_id: str) -> None:
    """The player has seen the plan: start on the first phase."""
    with _lock(build_id):
        s = _get(build_id)
        if s["stage"] != "plan":
            raise BuildError(409, "This build isn't waiting at the plan.")
        first = s["plan"]["phases"][0]["id"]
        s["stage"], s["current"] = "building", first
        launch = _prepare_phase(s, first, "", [], [], [], foreground=True)
        _save(s)
        launch()


def lock_phase(build_id: str, phase_id: str, keep: list[str]) -> None:
    """The player is happy with `keep` from the current phase's proposal: lock them
    in and move to the next phase — the one already being prepared, if what they kept
    is what it assumed."""
    with _lock(build_id):
        s = _get(build_id)
        if s["stage"] != "building" or s["current"] != phase_id:
            raise BuildError(409, "That isn't the phase being built.")
        phase = s["phases"][phase_id]
        proposal = phase["proposal"]
        if proposal is None:
            raise BuildError(409, "The Doctor hasn't chosen this phase's cards yet.")
        by_name = {c["name"]: c for c in proposal["cards"]}
        if any(n not in by_name for n in keep):
            raise BuildError(400, "That card isn't one of this phase's.")
        kept = [by_name[n] for n in dict.fromkeys(keep)]
        plan_phase = next(p for p in s["plan"]["phases"] if p["id"] == phase_id)

        for c in kept:
            s["deck"]["locked"].append({**c, "phase": phase_id, "qty": 1})
        if plan_phase["kind"] == "lands":
            pool_by_name = {c["name"]: c for c in s["pool"]}
            everyone = [e["name"] for e in s["deck"]["locked"]]
            basics = _basics_for(plan_phase["count"] - len(kept), s["commander"]["colors"], _pips(everyone, pool_by_name))
            for name, qty in basics.items():
                s["deck"]["locked"].append({"name": name, "id": None, "why": "", "price": 0.1, "category": "Basic Land", "type": "Basic Land", "cmc": 0, "phase": phase_id, "qty": qty})
        phase.update(status="locked", locked=[c["name"] for c in kept])

        following = _next_phase_id(s, phase_id)
        if following is None:
            s["stage"], s["current"] = "review", None
            _save(s)
            return
        s["current"] = following
        nxt = s["phases"][following]
        actual = _hash(_locked_names(s))
        ready = nxt["proposal"] is not None and nxt["proposal"]["based_on"] == actual
        running = nxt["working_gen"] is not None and nxt["working_based_on"] == actual
        launch = None
        if not ready and not running:
            nxt["proposal"], nxt["status"] = None, "pending"
            launch = _prepare_phase(s, following, "", [], [], [], foreground=True)
        elif ready:
            launch = _prefetch_next(s, following)
        _save(s)
        if launch:
            launch()


def redo_phase(build_id: str, phase_id: str, remove: list[str], note: str) -> None:
    """The player wants different cards: the ones they removed are replaced (and not
    offered again), the rest stay; with nothing removed and a note, the whole phase
    is chosen again with the note in mind."""
    with _lock(build_id):
        s = _get(build_id)
        if s["stage"] != "building" or s["current"] != phase_id:
            raise BuildError(409, "That isn't the phase being built.")
        phase = s["phases"][phase_id]
        proposal = phase["proposal"]
        if proposal is None:
            raise BuildError(409, "The Doctor hasn't chosen this phase's cards yet.")
        removed = set(remove) & {c["name"] for c in proposal["cards"]}
        if not removed and not note.strip():
            raise BuildError(400, "Remove some cards or say what you'd like different.")
        # Cards removed are replaced and not offered again; the rest stay. With
        # nothing removed, the whole phase is chosen again with the note in mind.
        fixed = [c for c in proposal["cards"] if c["name"] not in removed] if removed else []
        refused = list(dict.fromkeys([*removed, *phase.get("refused", [])]))
        phase["refused"] = refused
        phase["summary_hint"] = proposal["summary"]
        phase["proposal"], phase["status"] = None, "pending"
        launch = _prepare_phase(s, phase_id, note.strip(), refused, fixed, [], foreground=True)
        _save(s)
        launch()


def retry(build_id: str) -> None:
    """Tries again what failed."""
    with _lock(build_id):
        s = _get(build_id)
        step = (s["error"] or {}).get("retry")
        if not step:
            raise BuildError(409, "There's nothing to retry.")
        s["error"] = None
        if step["op"] == "phase":
            phase_id = step["phase"]
            s["phases"][phase_id]["proposal"] = None
            launch = _prepare_phase(s, phase_id, step["note"], step["exclude"], step["fixed"], [], foreground=True)
            _save(s)
            launch()
            return
        _save(s)
    _dispatch(build_id, step["op"], **{k: v for k, v in step.items() if k != "op"})


# -- the finished deck ---------------------------------------------------------------------


def final_cards(s: dict) -> list[str]:
    """Every card of the deck (not the commander), a name once per copy. Basic lands
    make up whatever the phases left short of 99."""
    names = [e["name"] for e in s["deck"]["locked"] for _ in range(e["qty"])]
    if len(names) < DECK_SIZE:
        pool_by_name = {c["name"]: c for c in s["pool"]}
        basics = _basics_for(DECK_SIZE - len(names), s["commander"]["colors"], _pips(list(set(names)), pool_by_name))
        names += [n for n, q in basics.items() for _ in range(q)]
    return names[:DECK_SIZE]


def conversation(s: dict) -> list[dict]:
    """The deck's first messages: the player's brief, then the Doctor's account of the
    build — the plan and what each phase put in and why — so the Correspondence tab
    opens on why the deck is the way it is."""
    plan, commander = s["plan"], s["commander"]
    asked = (s["brief"].get("text") or "").strip() or "Build me a deck."
    reply = [plan["strategy"] or f"Here's a deck built around {commander['name']}."]
    if commander["why"]:
        reply.append(f"**Why {commander['name']}.** {commander['why']}")
    if plan["order_reason"]:
        reply.append(f"**How we built it.** {plan['order_reason']}")
    for p in plan["phases"]:
        state = s["phases"][p["id"]]
        entries = [e for e in s["deck"]["locked"] if e["phase"] == p["id"] and e["qty"] == 1 and e["why"]]
        basics = [e for e in s["deck"]["locked"] if e["phase"] == p["id"] and e["category"] == "Basic Land"]
        if not entries and not basics:
            continue
        section = [f"**{p['label']}** — {(state['proposal'] or {}).get('summary') or p['why']}"]
        section += [f"- {e['name']} — {e['why']}" for e in entries]
        if basics:
            section.append("- " + ", ".join(f"{e['name']} ×{e['qty']}" for e in basics))
        reply.append("\n".join(section))
    return [
        {"role": "user", "content": f"{asked}\n\n(Answers: {_answers(s)}.)"},
        {"role": "assistant", "content": "\n\n".join(reply)},
    ]


def mark_done(build_id: str, deck_id: str) -> None:
    def change(s: dict) -> None:
        s["deck_id"], s["stage"] = deck_id, "done"

    _update(build_id, change)


# -- what the page sees -----------------------------------------------------------------------


def public(s: dict) -> dict:
    """The session as the page needs it: no candidate pool, the current phase's proposal
    beside the plan, and the deck so far."""
    plan = None
    if s["plan"]:
        plan = {
            "strategy": s["plan"]["strategy"],
            "order_reason": s["plan"]["order_reason"],
            "phases": [
                {
                    "id": p["id"],
                    "kind": p["kind"],
                    "label": p["label"],
                    "goal": p["goal"],
                    "count": p["count"],
                    "why": p["why"],
                    "status": s["phases"][p["id"]]["status"],
                    "locked": len(s["phases"][p["id"]]["locked"]),
                    "summary": (s["phases"][p["id"]]["proposal"] or {}).get("summary", ""),
                }
                for p in s["plan"]["phases"]
            ],
        }
    current = s["phases"].get(s["current"]) if s["current"] else None
    working_label = None
    if current and current["working_gen"] is not None:
        phase = next(p for p in s["plan"]["phases"] if p["id"] == s["current"])
        candidates = sum(1 for c in s["pool"] if c["land"] == (phase["kind"] == "lands"))
        working_label = f"Choosing the {phase['label'].lower()} from {candidates} cards EDHREC players run…"
    locked = s["deck"]["locked"]
    by_category = Counter()
    for e in locked:
        by_category["Land" if e["category"] in ("Lands", "Utility Lands", "Basic Land") else e["category"]] += e["qty"]
    return {
        "id": s["id"],
        "stage": s["stage"],
        "busy": s["busy"],
        "steps": s.get("steps", []),
        "working_label": working_label,
        "brief": {k: v for k, v in s["brief"].items() if k != "styles"},
        "error": None if not s["error"] else {k: v for k, v in s["error"].items() if k != "retry"},
        "resolved": s["resolved"],
        "commander_options": s["commander_options"],
        "facts": s.get("facts", []),
        "rounds": s.get("rounds", []),
        "rejected": s.get("rejected", []),
        "liked": s.get("liked", []),
        "commander": s["commander"],
        "plan": plan,
        "current": s["current"],
        "proposal": current["proposal"] if current else None,
        "working": bool(current and current["working_gen"] is not None),
        "deck": {
            "count": sum(e["qty"] for e in locked),
            "price": round(sum(e["price"] * e["qty"] for e in locked) + (s["commander"] or {}).get("price", 0), 2),
            "by_category": dict(by_category),
            "cards": [{"name": e["name"], "id": e["id"], "phase": e["phase"], "qty": e["qty"], "price": e["price"]} for e in locked],
        },
        "budget": (s["resolved"] or {}).get("budget"),
        "deck_id": s["deck_id"],
    }
