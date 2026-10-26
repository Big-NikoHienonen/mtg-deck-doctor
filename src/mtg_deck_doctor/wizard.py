"""The new-deck helper: finding commanders for a set of answers (colours, style,
power level, budget) and building a starting list for the one picked.

Everything here is rules over data, with no model in the loop: EDHREC says which
commanders players build in a colour combination and a theme, how their decks
split across power levels (the Commander Brackets), and what the average list
looks like at each; Scryfall says what the cards cost. The model is not needed
to navigate any of it, and nothing here spends tokens.

EDHREC's JSON is undocumented, so every read is bounded: a timeout, one retry, a
stale copy if it still fails. Pages are cached trimmed to what this needs — the
full ones are large, and a commander list is read many times.
"""

import json
import os
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from mtg_deck_doctor.card_cache import API_HEADERS, BASIC_LAND_NAMES, get_card_info, get_card_info_batch, throttle_scryfall
from mtg_deck_doctor.edhrec import commander_slug, get_commander_includes

CACHE_PATH = Path("data/wizard_cache.json")
CACHE_TTL_SECONDS = 24 * 60 * 60

# EDHREC's page names for each exact colour identity, in WUBRG order. Verified
# against the live site (all 32 resolve); the four-colour names are its own.
_RAW_COLOR_SLUGS = {
    "": "colorless",
    "W": "mono-white", "U": "mono-blue", "B": "mono-black", "R": "mono-red", "G": "mono-green",
    "WU": "azorius", "UB": "dimir", "BR": "rakdos", "RG": "gruul", "GW": "selesnya",
    "WB": "orzhov", "UR": "izzet", "BG": "golgari", "RW": "boros", "GU": "simic",
    "GWU": "bant", "WUB": "esper", "UBR": "grixis", "BRG": "jund", "RGW": "naya",
    "WBG": "abzan", "URW": "jeskai", "BGU": "sultai", "RWB": "mardu", "GUR": "temur",
    "WUBR": "yore-tiller", "UBRG": "glint-eye", "BRGW": "dune-brood", "RGWU": "ink-treader", "GWUB": "witch-maw",
    "WUBRG": "five-color",
}
_COLOR_ORDER = "WUBRG"

# EDHREC's names for the power levels (the Commander Brackets), by bracket number.
BRACKET_PAGES = {1: "exhibition", 2: "core", 3: "upgraded", 4: "optimized"}

# Game Changers a list may hold at each bracket. From the published Commander
# Brackets guidance as of when this was written — confirm against the current
# wording before leaning on it; bracket 4 has no limit.
GAME_CHANGER_LIMITS = {1: 0, 2: 0, 3: 3}

DECK_SIZE = 99  # cards besides the commander
# How many commanders get a summary fetched (one request each), and how many a
# list shows.
_SUMMARIZE = 14
_SHOW = 8
# Fewer decks than this at the chosen power level and the commander is left out
# of the list — unless that would leave almost nothing.
_MIN_DECKS_AT_BRACKET = 5
# What a commander's decks must show of the chosen theme: a share of them, and
# enough in absolute terms to be more than a stray few.
_MIN_THEME_SHARE = 0.02
_MIN_THEMED_DECKS = 10
# "Well known" for a colour combination: the commanders at the top of EDHREC's
# list for it. Asking for lesser-known commanders starts below them, at ones
# with enough decks (an average list from three decks is noise).
_FAMOUS = 5
_NICHE_MIN_DECKS = 100
_NICHE_POOL = 18  # how many lesser-known commanders to look into, of which _SHOW are shown

_lock = threading.Lock()
_MISSING = {"missing": True}


class WizardDataError(Exception):
    """EDHREC (or Scryfall) couldn't be reached and nothing is cached."""


def canonical_colors(colors: str) -> str:
    """`colors` as the letters WUBRG in that order, no repeats; raises
    ValueError on anything else."""
    letters = set(colors.upper())
    if not letters <= set(_COLOR_ORDER):
        raise ValueError(f"unknown colour in {colors!r}")
    return "".join(c for c in _COLOR_ORDER if c in letters)


# Keyed by canonical colours, whatever order the table above was written in.
COLOR_SLUGS = {canonical_colors(k): v for k, v in _RAW_COLOR_SLUGS.items()}


# -- trimmed cache ----------------------------------------------------------


def _load() -> dict:
    return json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}


def _store(key: str, data) -> None:
    # Re-read under the lock rather than writing back a copy loaded before a
    # slow fetch: pages are fetched in parallel, and each would otherwise
    # discard the others' entries (the same race card_cache.py documents).
    with _lock:
        cache = _load()
        cache[key] = {"fetchedAt": time.time(), "data": data}
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cache))
        os.replace(tmp, CACHE_PATH)


def _fetch_page(path: str) -> dict | None:
    """One EDHREC page's JSON; None if there is no such page (EDHREC answers a
    missing page with 403 or 404); raises httpx.HTTPError if it can't be read."""
    for attempt in (1, 2):
        try:
            response = httpx.get(f"https://json.edhrec.com/pages/{path}", headers=API_HEADERS, timeout=12)
            if response.status_code in (403, 404):
                return None
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError:
            if attempt == 2:
                raise
    raise AssertionError("unreachable")


def _cached(key: str, build):
    """The trimmed result of `build()` (which reads pages), cached for a day. A
    page that doesn't exist is cached too, as an empty result from `build`. A
    failure serves the stale entry, or None when there is none — None means
    "couldn't find out", never "nothing there"."""
    entry = _load().get(key)
    if entry and time.time() - entry["fetchedAt"] < CACHE_TTL_SECONDS:
        return entry["data"]
    try:
        data = build()
    except (httpx.HTTPError, KeyError, ValueError):
        return entry["data"] if entry else None
    _store(key, data)
    return data


def game_changer_names() -> set[str] | None:
    """The cards on the Commander Brackets' Game Changers list, from Scryfall
    (`is:gamechanger` — the authoritative source; EDHREC's own flag for them
    never appears on its commander pages). None if it couldn't be read."""

    def build() -> list[str]:
        names: list[str] = []
        url, params = "https://api.scryfall.com/cards/search", {"q": "is:gamechanger", "unique": "cards"}
        while url:
            throttle_scryfall()
            response = httpx.get(url, params=params, headers=API_HEADERS, timeout=15)
            response.raise_for_status()
            body = response.json()
            names += [c["name"] for c in body["data"]]
            url, params = body.get("next_page") if body.get("has_more") else None, None
        return names

    names = _cached("gamechangers", build)
    return None if names is None else set(names)


# -- commanders for a set of answers ----------------------------------------


def commanders_for(colors: str, theme: str | None = None) -> list[dict] | None:
    """The commanders players build in exactly these colours, most-built first —
    for one theme if given — as [{"name", "id", "num_decks"}]. [] if EDHREC has
    nothing for the combination; None if it couldn't be read."""
    slug = COLOR_SLUGS[colors]
    path = f"tags/{theme}/{slug}.json" if theme else f"commanders/{slug}.json"

    def build() -> list[dict]:
        page = _fetch_page(path)
        if page is None:
            return []
        lists = page["container"]["json_dict"]["cardlists"]
        wanted = next((l for l in lists if l.get("tag") == "topcommanders" or str(l.get("tag", "")).endswith("commanders")), None)
        views = (wanted or {}).get("cardviews", [])
        return [{"name": v["name"], "id": v.get("id"), "num_decks": v.get("num_decks", 0)} for v in views]

    return _cached(f"commanders:{theme or '-'}:{colors}", build)


def _legal(entries: list[dict], infos: dict) -> list[dict]:
    """The commanders among `entries` that are legal as commanders. EDHREC lists
    decks for cards that aren't (playtest cards, say), so each is checked against
    Scryfall; one whose legality couldn't be found out is kept — failing to look
    must not hide it."""
    return [e for e in entries if (infos.get(e["name"]) or {}).get("legality", "legal") == "legal"]


def theme_counts(colors: str, themes: list[str]) -> dict[str, int | None]:
    """How many legal commanders each theme has in these colours (None: couldn't
    be read), fetched in parallel — the first time for a colour combination it is
    one request per theme, plus a few to check legality."""
    with ThreadPoolExecutor(max_workers=4) as pool:
        lists = list(pool.map(lambda t: commanders_for(colors, t), themes))
    names = sorted({e["name"] for l in lists if l for e in l[: _SUMMARIZE + 6]})
    infos = get_card_info_batch(names)["info"] if names else {}
    return {t: (None if l is None else len(_legal(l[: _SUMMARIZE + 6], infos))) for t, l in zip(themes, lists)}


def commander_summary(name: str) -> dict | None:
    """What the list needs to say about one commander: how many decks, how they
    split by power level and budget, its top themes and the cards that most set
    its decks apart. None if EDHREC has no page for it or can't be read."""
    slug = commander_slug(name)

    def build() -> dict:
        page = _fetch_page(f"commanders/{slug}.json")
        if page is None:
            return _MISSING
        container = page["container"]["json_dict"]
        card = container.get("card", {})
        views = [
            v
            for cl in container["cardlists"]
            if cl.get("tag") in ("creatures", "instants", "sorceries", "utilityartifacts", "enchantments", "planeswalkers")
            for v in cl.get("cardviews", [])
        ]
        # The cards played here far more than in other decks of these colours,
        # among those a good share of decks actually run.
        signature = sorted(
            (v for v in views if v.get("potential_decks") and v.get("num_decks", 0) / v["potential_decks"] >= 0.25),
            key=lambda v: -v.get("synergy", 0),
        )[:4]
        return {
            "name": card.get("name", name),
            "num_decks": card.get("num_decks", 0),
            "bracket_counts": {str(k): v for k, v in (page.get("bracket_counts") or {}).items()},
            "budget_counts": page.get("budget_counts") or {},
            "themes": [{"name": t["value"], "slug": t["slug"], "count": t["count"]} for t in (page.get("tag_counts") or [])[:5]],
            "signature": [v["name"] for v in signature],
        }

    summary = _cached(f"summary:{slug}", build)
    return None if summary is None or summary == _MISSING else summary


def _spread(items: list, n: int) -> list:
    """`n` items spread evenly along `items` (all of them if there are no more
    than `n`), keeping the first and last."""
    if len(items) <= n:
        return list(items)
    return [items[round(i * (len(items) - 1) / (n - 1))] for i in range(n)]


def _lesser_known(base: list[dict], colour_base: list[dict], themed: bool) -> list[dict]:
    """The commanders in `base` that aren't well known — not among the `_FAMOUS`
    most-built in these colours (`colour_base`, most-built first) — and still
    have enough decks to learn from, spread evenly from the better-known of them
    to the most obscure, so a few of each show, not only the ones just outside
    the spotlight."""
    famous = {e["name"] for e in colour_base[:_FAMOUS]}
    floor = _MIN_THEMED_DECKS if themed else _NICHE_MIN_DECKS
    eligible = sorted((e for e in base if e["name"] not in famous and e["num_decks"] >= floor), key=lambda e: -e["num_decks"])
    return _spread(eligible, _NICHE_POOL)


def candidates(colors: str, theme: str | None, bracket: int | None, niche: bool = False) -> dict:
    """Commanders to show for the answers so far: the most-built in these
    colours (and theme) — or, with `niche`, the lesser-known ones below the most
    built — each with how many decks exist at the chosen power level, ranked by
    that when one is chosen. Returns {"commanders": [...], "relaxed": bool}
    — relaxed when few commanders have decks at that level and the cut-off was
    dropped — plus "niche_fallback" when lesser-known commanders were asked for
    and there were none to show, or {"unavailable": True} if EDHREC couldn't be
    read."""
    base = commanders_for(colors, theme)
    if base is None:
        return {"unavailable": True, "commanders": [], "relaxed": False, "fell_back_from": None, "niche_fallback": False}
    niche_fallback = False
    head = base[: _SUMMARIZE + 6]
    if niche:
        colour_base = (commanders_for(colors, None) if theme else base) or []
        lesser = _lesser_known(base, colour_base, themed=bool(theme))
        if lesser:
            head = lesser
        else:
            niche_fallback = True
    top = _legal(head, get_card_info_batch([c["name"] for c in head])["info"])
    top = top if niche and not niche_fallback else top[:_SUMMARIZE]
    if theme and not top:
        # Nothing legal for this theme in these colours: show the most-built
        # commanders in them instead, and say so.
        return {**candidates(colors, None, bracket, niche), "fell_back_from": theme}
    with ThreadPoolExecutor(max_workers=4) as pool:
        summaries = list(pool.map(lambda c: commander_summary(c["name"]), top))

    rows = []
    for entry, summary in zip(top, summaries):
        if summary is None:
            continue
        at_bracket = summary["bracket_counts"].get(str(bracket), 0) if bracket else None
        rows.append(
            {
                "name": entry["name"],
                "id": entry["id"],
                "num_decks": summary["num_decks"] or entry["num_decks"],
                "themed_decks": entry["num_decks"] if theme else None,
                "decks_at_bracket": at_bracket,
                "bracket_counts": summary["bracket_counts"],
                "themes": summary["themes"],
                "signature": summary["signature"],
            }
        )
    # A theme is only worth choosing a commander for if it is a real share of
    # that commander's decks — a big commander with a handful of Dragons decks
    # shouldn't outrank one that is built around them.
    if theme:
        real = [
            r
            for r in rows
            if r["themed_decks"] >= _MIN_THEMED_DECKS and r["themed_decks"] / max(r["num_decks"], 1) >= _MIN_THEME_SHARE
        ]
        rows = real or rows[:3]
    # And at the chosen power level there have to be decks to learn from. If
    # nothing qualifies, show the closest few and say the cut-off was dropped.
    relaxed = False
    if bracket:
        enough = [r for r in rows if r["decks_at_bracket"] >= _MIN_DECKS_AT_BRACKET]
        relaxed = not enough
        rows = enough or rows[:3]
    if niche and not niche_fallback:
        # Evenly along the way from better known to obscure, not the best-known few.
        rows.sort(key=lambda r: -r["num_decks"])
        shown = _spread(rows, _SHOW)
    else:
        rows.sort(key=lambda r: (-(r["themed_decks"] if theme else (r["decks_at_bracket"] or 0)), -r["num_decks"]))
        shown = rows[:_SHOW]
    return {
        "commanders": shown,
        "relaxed": relaxed,
        "unavailable": False,
        "fell_back_from": None,
        "niche_fallback": niche_fallback,
    }


_COLOR_WORDS = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}
_BRACKET_LABELS = {1: "Exhibition", 2: "Core", 3: "Upgraded", 4: "Optimized"}


def answers_in_words(colors: str | None, theme: str | None, bracket: int | None, budget: float | None, niche: bool = False) -> str:
    """The form's answers as a sentence, for the model to read. `colors` None means
    they haven't been decided; "" means colourless."""
    return "; ".join(
        [
            *(["wants lesser-known commanders, not the most popular ones"] if niche else []),
            "colours " + ("open" if colors is None else ", ".join(_COLOR_WORDS[c] for c in colors) if colors else "colourless"),
            f"style: {theme.replace('-', ' ')}" if theme else "no particular style",
            f"power level: {_BRACKET_LABELS[bracket]} (level {bracket})" if bracket else "power level not chosen",
            f"budget: up to ${budget:,.0f}" if budget else "no budget limit",
        ]
    )


def cached_get(key: str):
    """A stored result of this module's own (an explanation, say), if it is under
    a day old."""
    entry = _load().get(key)
    return entry["data"] if entry and time.time() - entry["fetchedAt"] < CACHE_TTL_SECONDS else None


def cached_put(key: str, data) -> None:
    _store(key, data)


def resolve_commander(name: str) -> dict | None:
    """The commander a player named, as Scryfall resolves the name (a close
    spelling is fine), if it is legal as one: {"name", "id"}. None if it isn't a
    card, isn't legal as a commander, or can't be checked right now."""
    try:
        throttle_scryfall()
        response = httpx.get(
            "https://api.scryfall.com/cards/named", params={"fuzzy": name}, headers=API_HEADERS, timeout=12
        )
        if response.status_code == 200:
            card = response.json()
        else:
            # A first name alone ("Sivitri") is ambiguous to the fuzzy match; among
            # cards that can be commanders, the most-played match is what was meant.
            words = re.sub(r"[^\w' ,-]", "", name).strip()
            if not words:
                return None
            throttle_scryfall()
            found = httpx.get(
                "https://api.scryfall.com/cards/search",
                params={"q": f'name:"{words}" is:commander legal:commander', "order": "edhrec", "unique": "cards"},
                headers=API_HEADERS,
                timeout=12,
            )
            if found.status_code != 200 or not found.json().get("data"):
                return None
            card = found.json()["data"][0]
    except httpx.HTTPError:
        return None
    type_line = card.get("type_line", "")
    can_lead = ("Legendary" in type_line and "Creature" in type_line) or "can be your commander" in (card.get("oracle_text") or "")
    if card.get("legalities", {}).get("commander") != "legal" or not can_lead:
        return None
    return {"name": card["name"], "id": card["id"]}


def explain_context(result: dict) -> list[dict]:
    """What the model is shown about each commander of a `candidates` result:
    its text and type from Scryfall, and what EDHREC shows for it."""
    infos = get_card_info_batch([c["name"] for c in result["commanders"]])["info"]
    return [
        {
            "name": c["name"],
            "type_line": (infos.get(c["name"]) or {}).get("typeLine"),
            "mana_cost": (infos.get(c["name"]) or {}).get("manaCost"),
            "colors": "".join(sorted((infos.get(c["name"]) or {}).get("colorIdentity", []), key="WUBRG".index)),
            "oracle": ((infos.get(c["name"]) or {}).get("oracleText") or "").replace("\n", " ")[:500],
            "themes": [t["name"] for t in c["themes"][:4]],
            "signature": c["signature"],
            "num_decks": c["num_decks"],
            "decks_at_bracket": c["decks_at_bracket"],
        }
        for c in result["commanders"]
    ]


# -- a starting list ---------------------------------------------------------


def _group(type_line: str | None) -> str:
    t = type_line or ""
    if "Land" in t:
        return "Land"
    if "Creature" in t:
        return "Creature"
    if "Planeswalker" in t:
        return "Planeswalker"
    if "Instant" in t:
        return "Instant"
    if "Sorcery" in t:
        return "Sorcery"
    if "Artifact" in t:
        return "Artifact"
    if "Enchantment" in t:
        return "Enchantment"
    return "Other"


_BASIC_FOR_COLOR = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}

# The parts of a deck a player can say how to spend on. Lands and mana rocks
# are split out because that is where budgets usually go wrong: a mana base can
# cost more than every spell in the deck.
AREAS = {"lands": "Lands", "rocks": "Mana rocks", "creatures": "Creatures", "spells": "Other spells"}

# Basics a "spend more on lands" list never trades away: the deck still wants
# a few of them for fixing and for fetch targets.
_MIN_BASICS = 4


def _check_spend(caps: dict[str, float] | None, invest: list[str] | None) -> tuple[dict[str, float], set[str]]:
    caps = dict(caps or {})
    invest_set = set(invest or [])
    unknown = (set(caps) | invest_set) - set(AREAS)
    if unknown:
        raise ValueError(f"Unknown part of the deck: {', '.join(sorted(unknown))}.")
    if any(cap < 0 for cap in caps.values()):
        raise ValueError("A spending limit can't be negative.")
    if set(caps) & invest_set:
        raise ValueError("A part of the deck can't be both capped and spent more on.")
    return caps, invest_set


def _average_deck(slug: str, bracket: int, cheap: bool) -> tuple[Counter, str] | None:
    """The average list for this commander at this power level — from the
    budget end of that level when the budget is small — falling back to the
    commander's average list overall. (counts, label), or None if none exists."""
    page_name = BRACKET_PAGES[bracket]
    variants = ([(f"{page_name}/budget", f"{page_name} power level, budget decks")] if cheap else []) + [
        (page_name, f"{page_name} power level"),
        ("", "all decks"),
    ]
    for suffix, label in variants:
        path = f"average-decks/{slug}/{suffix}.json" if suffix else f"average-decks/{slug}.json"

        def build() -> list:
            page = _fetch_page(path)
            if page is None:
                return []
            cards = page["deck"]["cards"]
            return [[name, qty] for lst in cards.values() for name, qty in lst]

        pairs = _cached(f"avg:{slug}:{suffix or '-'}", build)
        if pairs:
            return Counter({name: qty for name, qty in pairs}), label
    return None


def starter_list(
    commander: str,
    bracket: int,
    budget: float | None,
    caps: dict[str, float] | None = None,
    invest: list[str] | None = None,
) -> dict:
    """A 99-card starting list for `commander`: the average list at this power
    level, with Game Changers kept within the bracket's limit and — when there is
    a budget — the priciest cards swapped for cheaper, similar ones until it fits
    or there is nothing sensible left to swap.

    `caps` limits what a part of the deck (a key of AREAS) may cost, in dollars,
    whatever the budget. `invest` names parts to spend more on: they are the last
    to lose expensive cards, and money the cheaper parts free up goes into them.
    Raises ValueError for bad input and WizardDataError if EDHREC has no list
    for the commander or couldn't be read."""
    if bracket not in BRACKET_PAGES:
        raise ValueError("bracket must be 1-4")
    caps, invest_set = _check_spend(caps, invest)
    commander_info = get_card_info(commander)
    if commander_info is not None and commander_info.get("legality") != "legal":
        raise ValueError(f"{commander} isn't legal as a commander in Commander.")
    slug = commander_slug(commander)
    averaged = _average_deck(slug, bracket, cheap=budget is not None and budget <= 100)
    if averaged is None:
        raise WizardDataError(f"EDHREC has no list for {commander!r}, or couldn't be reached.")
    counts, variant = averaged
    counts.pop(commander, None)

    includes = get_commander_includes(commander)
    by_name = {c["name"]: c for c in includes["cards"]} if includes.get("available") else {}
    colors = (commander_info or {}).get("colorIdentity", [])
    notes: list[str] = []

    # The pool replacements come from: the cards EDHREC players run most that
    # the list lacks, best first.
    pool = [c for c in includes.get("cards", []) if c["name"] not in counts][:150]
    infos = get_card_info_batch([commander, *counts, *(c["name"] for c in pool)])["info"]

    def price(name: str) -> float:
        return float((infos.get(name) or {}).get("priceUsd") or 0)

    def group(name: str) -> str:
        return _group((infos.get(name) or {}).get("typeLine"))

    def area(name: str) -> str:
        if name in BASIC_LAND_NAMES or group(name) == "Land":
            return "lands"
        if by_name.get(name, {}).get("category") == "Mana Artifacts":
            return "rocks"
        return "creatures" if group(name) == "Creature" else "spells"

    # Only cards that are legal here and inside the commander's colours.
    def allowed(name: str) -> bool:
        info = infos.get(name)
        if info is None:
            return name in BASIC_LAND_NAMES
        return info.get("legality") == "legal" and set(info.get("colorIdentity", [])) <= set(colors)

    for name in [n for n in counts if not allowed(n)]:
        counts.pop(name)
    pool = [c for c in pool if allowed(c["name"])]

    limit = GAME_CHANGER_LIMITS.get(bracket)
    known = game_changer_names()
    game_changers = known or set()
    if known is None:
        notes.append("Couldn't check the Game Changers list just now, so this list hasn't been checked against it.")
    if limit is not None:
        pool = [c for c in pool if c["name"] not in game_changers]

    swaps: list[dict] = []

    def swap(out: str, replacement: str) -> None:
        qty = counts.pop(out)
        counts[replacement] += qty
        swaps.append({"out": out, "in": replacement, "saved": round(price(out) - price(replacement), 2)})

    def best_replacement(like: str, max_price: float, within: str | None = None) -> str | None:
        """The most-played unused card that costs at most `max_price`, of the
        same kind as `like` if there is one, otherwise any spell. With `within`
        (a key of AREAS) only cards of that part of the deck count."""
        usable = [c["name"] for c in pool if c["name"] not in counts and price(c["name"]) <= max_price]
        if within:
            return next((n for n in usable if area(n) == within), None)
        same = [n for n in usable if group(n) == group(like)]
        return (same or [n for n in usable if group(n) != "Land"] or [None])[0]

    def basic() -> str:
        options = [_BASIC_FOR_COLOR[c] for c in colors if c in _BASIC_FOR_COLOR] or ["Wastes"]
        return min(options, key=lambda b: counts.get(b, 0))

    # Game Changers over the bracket's limit, least-played first.
    over = sorted((n for n in counts if n in game_changers), key=lambda n: by_name.get(n, {}).get("inclusion", 0))
    if limit is not None and len(over) > limit:
        for name in over[: len(over) - limit]:
            repl = best_replacement(name, float("inf"))
            if repl:
                swap(name, repl)
                notes.append(f"Swapped {name} out — it is a Game Changer and this power level allows {limit}.")
            else:
                counts.pop(name)

    commander_price = price(commander)
    total = lambda: sum(price(n) * q for n, q in counts.items())  # noqa: E731
    deck_total = lambda: total() + commander_price  # noqa: E731
    area_total = lambda a: sum(price(n) * q for n, q in counts.items() if area(n) == a)  # noqa: E731

    # Spending limits per part of the deck, before the overall budget: each part
    # sheds its priciest cards for cheaper ones of the same part (a land for a
    # land, falling back to basics) until it fits. Doing this first means the
    # money a capped part gives up is left for everything else.
    for a, cap in caps.items():
        for name in sorted(
            (n for n in counts if area(n) == a and n not in BASIC_LAND_NAMES and price(n) >= 1.0),
            key=lambda n: -price(n),
        ):
            if area_total(a) <= cap:
                break
            repl = best_replacement(name, min(5.0, price(name) * 0.4), within=a)
            if repl:
                swap(name, repl)
            elif a == "lands":
                b = basic()
                counts[b] += counts.pop(name)
                swaps.append({"out": name, "in": b, "saved": round(price(name) - price(b), 2)})
        if area_total(a) > cap:
            notes.append(f"Couldn't keep {AREAS[a].lower()} under ${cap:,.0f} — they come to ${area_total(a):,.0f}, and the cheaper options ran out.")

    # Fit the budget: swap the most expensive cards first, keeping cheap
    # staples that nearly every list plays, and leaving the parts the player
    # chose to spend on until last. The budget is for the whole deck, so the
    # commander — which can't be swapped — comes out of it first, and only the
    # 99 cards are fitted to what's left.
    reached = True
    if budget is not None and deck_total() > budget:
        protected = {n for n in counts if by_name.get(n, {}).get("inclusion", 0) >= 0.7 and price(n) <= 0.08 * budget}
        order = sorted(
            (n for n in counts if n not in BASIC_LAND_NAMES and n not in protected and price(n) >= 2.0),
            key=lambda n: (area(n) in invest_set, -price(n)),
        )
        for name in order:
            if deck_total() <= budget:
                break
            cap = min(5.0, price(name) * 0.4)
            repl = best_replacement(name, cap)
            if repl:
                swap(name, repl)
            elif group(name) == "Land":
                b = basic()
                qty = counts.pop(name)
                counts[b] += qty
                swaps.append({"out": name, "in": b, "saved": round(price(name), 2)})
        reached = deck_total() <= budget
        if not reached:
            if commander_price >= budget:
                notes.append(
                    f"{commander} alone costs ${commander_price:,.0f}, which is more than your ${budget:,.0f} budget — "
                    f"the cheapest list around it comes to ${deck_total():,.0f}."
                )
            else:
                notes.append(
                    f"Couldn't get under ${budget:,.0f} without gutting the list — this comes to ${deck_total():,.0f}"
                    + (f", ${commander_price:,.0f} of it the commander" if commander_price >= 0.15 * budget else "")
                    + ". A cheaper commander or a lower power level would get closer."
                )

    # Whatever the budget has left goes to the parts the player wants to spend
    # on: each takes the most-played cards it lacks in place of its least-played
    # ones (for lands, in place of basics), while they fit.
    if budget is not None and invest_set:
        for a in (a for a in AREAS if a in invest_set):
            wanted = [c["name"] for c in pool if c["name"] not in counts and area(c["name"]) == a and price(c["name"]) > 0]
            for new in wanted:
                if a == "lands":
                    basics = [n for n in counts if n in BASIC_LAND_NAMES and counts[n] > 0]
                    out = max(basics, key=lambda n: counts[n]) if sum(counts[n] for n in basics) > _MIN_BASICS else None
                else:
                    own = [n for n in counts if area(n) == a and n not in BASIC_LAND_NAMES]
                    out = min(own, key=lambda n: by_name.get(n, {}).get("inclusion", 0)) if own else None
                    if out and by_name.get(out, {}).get("inclusion", 0) >= by_name.get(new, {}).get("inclusion", 0):
                        out = None
                if out is None:
                    break
                if deck_total() - price(out) + price(new) > budget:
                    continue
                counts[out] -= 1
                if counts[out] <= 0:
                    counts.pop(out)
                counts[new] += 1
                swaps.append({"out": out, "in": new, "saved": round(price(out) - price(new), 2)})

    # Land on exactly 99: trim the least-played spells, or fill with the best
    # unused cards and then basics.
    size = sum(counts.values())
    while size > DECK_SIZE:
        trim = [n for n in counts if n not in BASIC_LAND_NAMES]
        drop = min(trim, key=lambda n: by_name.get(n, {}).get("inclusion", 0)) if trim else basic()
        counts[drop] -= 1
        if counts[drop] <= 0:
            counts.pop(drop)
        size -= 1
    while size < DECK_SIZE:
        fill = next((c["name"] for c in pool if c["name"] not in counts and (budget is None or price(c["name"]) <= 3)), None)
        counts[fill or basic()] += 1
        size += 1

    cards = [
        {
            "name": name,
            "quantity": qty,
            "category": group(name) if name in infos else ("Land" if name in BASIC_LAND_NAMES else "Other"),
            "price_usd": round(price(name), 2),
            "id": (infos.get(name) or {}).get("id"),
        }
        for name, qty in sorted(counts.items(), key=lambda kv: (kv[0] in BASIC_LAND_NAMES, kv[0]))
    ]
    category_counts: Counter = Counter()
    for card in cards:
        category_counts[card["category"]] += card["quantity"]
    summary = commander_summary(commander)
    at_bracket = (summary or {}).get("bracket_counts", {}).get(str(bracket))
    if at_bracket is not None and at_bracket < 30:
        notes.append(f"Only {at_bracket} {commander.split(',')[0]} decks sit at this power level, so this list leans on the nearest data.")
    return {
        "commander": {"name": commander, "id": (commander_info or {}).get("id"), "price_usd": round(price(commander), 2)},
        "cards": cards,
        "card_count": sum(counts.values()),
        # The whole deck, commander included — what the deck page will show.
        "total_price": round(deck_total(), 2),
        "cards_price": round(total(), 2),
        "budget": budget,
        "budget_reached": reached,
        "game_changers": sorted(n for n in counts if n in game_changers),
        "category_counts": category_counts,
        "spend": [
            {
                "area": a,
                "label": label,
                "price": round(area_total(a), 2),
                "cap": caps.get(a),
                "invest": a in invest_set,
            }
            for a, label in AREAS.items()
        ],
        "variant": variant,
        "swaps": swaps,
        "notes": notes,
    }
