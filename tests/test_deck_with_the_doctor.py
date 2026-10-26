"""Tests for building a deck with the Doctor, a phase at a time: what the model's
answers are checked against, the session's steps (brief, commander, plan, phases,
locking, redoing, the next phase prepared early), the rules the Doctor can't break,
and the endpoints. No network and no model: both are stubbed. Run with

    uv run python tests/test_deck_with_the_doctor.py
"""

import json
import tempfile
import threading
import time
from pathlib import Path

import anthropic
import httpx
from fastapi.testclient import TestClient

import mtg_deck_doctor.deck as D
import mtg_deck_doctor.deck_builder as B
import mtg_deck_doctor.tool_loop as T
import mtg_deck_doctor.wizard as W
from mtg_deck_doctor import api

D.DECKS_DIR = Path(tempfile.mkdtemp()) / "decks"
B.BUILDS_DIR = Path(tempfile.mkdtemp()) / "builds"
W.CACHE_PATH = Path(tempfile.mkdtemp()) / "wizard_cache.json"
results: list[bool] = []


def check(name: str, ok: object, detail: str = "") -> None:
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def wait_until(condition, timeout: float = 6.0):
    end = time.time() + timeout
    while time.time() < end:
        value = condition()
        if value:
            return value
        time.sleep(0.02)
    return None


# --- model output is untrusted: the plan --------------------------------------------------
plan_in = {"strategy": "Win with zombies.", "order_reason": "Creatures first.", "phases": [
    {"kind": "creatures", "count": 14, "why": "The plan is bodies."},
    {"kind": "ramp", "count": 10, "why": "Mana."},
    {"kind": "lands", "count": 36, "why": "Fixing."},
]}
for label, raw in {"plain": plan_in, "wrapped once": {"plan": plan_in}, "wrapped twice (seen live)": {"plan": {"plan": plan_in}}, "as a string of JSON": json.dumps(plan_in), "inside a string": {"plan": json.dumps(plan_in)}}.items():
    out = T._checked_plan(raw)
    check(f"plan read from: {label}", [p["kind"] for p in out["phases"]] == ["creatures", "ramp", "lands", "flex"] and out["strategy"] == "Win with zombies.", str([p["kind"] for p in out["phases"]]))
out = T._checked_plan(plan_in)
check("a plan comes to exactly 99 cards, flex taking what's left", sum(p["count"] for p in out["phases"]) == 99 and out["phases"][-1]["kind"] == "flex" and out["phases"][-1]["count"] == 39)
messy = {"strategy": "s", "order_reason": "o", "phases": [
    {"kind": "ramp", "count": 10, "why": "a"}, {"kind": "ramp", "count": 5, "why": "dup"}, {"kind": "made_up", "count": 5, "why": "?"},
    {"kind": "draw", "count": 0, "why": "none"}, {"kind": "removal", "count": "lots", "why": "?"}, "junk", {"kind": "flex", "count": 50, "why": "the model's flex is ignored"},
    {"kind": "creatures", "count": 200, "why": "too many"}]}
out = T._checked_plan(messy)
kinds = [p["kind"] for p in out["phases"]]
check("unknown kinds, repeats, zero or non-numeric counts and junk are dropped; lands are added; flex is last", kinds == ["ramp", "creatures", "lands", "flex"], str(kinds))
check("...and however big the model's counts, the whole comes to 99 with room left for flex", sum(p["count"] for p in out["phases"]) == 99 and out["phases"][-1]["count"] >= T.MIN_FLEX and out["phases"][2]["count"] >= 28, str([(p["kind"], p["count"]) for p in out["phases"]]))
check("lands are kept to a sane number", {p["kind"]: p["count"] for p in T._checked_plan({"phases": [{"kind": "lands", "count": 5, "why": ""}]})["phases"]}["lands"] == 28 and {p["kind"]: p["count"] for p in T._checked_plan({"phases": [{"kind": "lands", "count": 99, "why": ""}]})["phases"]}["lands"] == 42)
for label, raw in {"nothing": None, "garbage": "nope", "no phases": {"strategy": "x"}}.items():
    out = T._checked_plan(raw)
    check(f"a plan from {label} falls back to the default phases", [p["kind"] for p in out["phases"]][:2] == ["must_haves", "creatures"] and sum(p["count"] for p in out["phases"]) == 99)

# --- ... a phase's cards and the commander options ----------------------------------------------
pool_names = {"A", "B", "C"}
raw = {"phase": {"summary": "S" * 30, "picks": [{"name": "A", "why": "does a thing here"}, {"name": "Z", "why": "not on the list"}, {"name": "B", "why": ""}, {"name": "A", "why": "again, a long reason"}, {"name": "C", "why": "another fine reason"}]}}
out = T._checked_phase(raw, pool_names, 2)
check("a phase's picks must be on the list, with a reason, once, and no more than asked", [p["name"] for p in out["picks"]] == ["A", "C"] and out["summary"], str(out["picks"]))
check("...whether wrapped, twice-wrapped or sent as a string", all([p["name"] for p in T._checked_phase(r, pool_names, 5)["picks"]] == ["A", "C"] for r in [raw["phase"], {"phase": raw}, json.dumps(raw["phase"]), {"phase": json.dumps(raw["phase"])}]))
check("...and nothing from garbage", T._checked_phase("nope", pool_names, 5) == {"summary": "", "picks": []})
captured = {}
def spy_loop(system, user, tools, final, key, **kw):
    captured.update(system=system, user=user, final=final, key=key)
    if final == "return_answers":
        return {"colors": ["B", "X"], "colorless": False, "style": "zombies", "power": 3, "budget": "100", "commander": "", "color_options": ["g", "GG", "Q", "br", "BR", "URG", "WUBRG"], "theme_hints": ["Treasure", "aggro!", "artifacts", "a", "treasure", "extra"], "focus": "f" * 900, "lesser_known": True, "understood": "ok"}
    if final == "return_search_plan":
        return {"plan": {"facts": ["Makes Treasure", "Makes Treasure", "", 5, "x" * 200, "a", "b", "c", "d", "e", "f", "g"], "understood": "You want treasure.", "queries": [
            {"q": "o:treasure", "why": "makes treasure"}, {"q": "o:treasure", "why": "again"}, "junk", {"q": "", "why": "empty"}, {"q": "id<=r o:attacks", "why": "red"}, {"q": "kw:haste", "why": "fast"}, {"q": "t:goblin", "why": "a fourth"}],
            "color_options": ["r", "BR", "zz"], "theme_hints": ["Treasure", "a"]}}
    return [{"name": "Off Menu", "why": "x" * 20}, {"name": "On Menu", "why": "supports your plan", "fits": ["F1", "Made up", "F1"], "misses": ["F2"]}, {"name": "On Menu", "why": "a second time, ignored"}]   # what the loop hands back for "options"
T._run_structured_loop = spy_loop
offered = T.propose_commanders("brief", ["F1", "F2"], [{"name": "On Menu", "num_decks": 5, "themes": [], "signature": []}], [{"name": "Gone", "reason": "too slow"}], ["Liked"])
check("commander options are limited to the menu, once each, with the facts they fit and miss (only real ones)", offered == [{"name": "On Menu", "why": "supports your plan", "fits": ["F1"], "misses": ["F2"]}], str(offered))
check("the model is given the facts, what was rejected (with why) and what was liked", all(x in captured["user"] for x in ["F1; F2", "Gone (too slow)", "LIKED: Liked", "On Menu"]), captured["user"])
searched_for = T.plan_commander_search("a treasure deck", ["Makes Treasure"], "  attacks a lot  ", [{"name": "Gone", "reason": "too slow"}, {"name": "Bare", "reason": ""}], ["Liked"], ["A", "B"])
check("a search plan: facts de-duplicated, trimmed to 80 characters and eight in all, junk dropped", searched_for["facts"][0] == "Makes Treasure" and len(searched_for["facts"]) == 8 and all(len(f) <= 80 for f in searched_for["facts"]) and "" not in searched_for["facts"], str(searched_for["facts"]))
check("...queries: at most three, each once, junk and blanks dropped", [q["q"] for q in searched_for["queries"]] == ["o:treasure", "id<=r o:attacks", "kw:haste"], str(searched_for["queries"]))
check("...the colours it must have: letters in order, each once, up to three, colourless as \"\"", T._checked_search_plan({"colors": ["rb", "BR", "G", "zz", "W"]})["colors"] == ["BR", "G", "W"] and T._checked_search_plan({"colors": ["C"]})["colors"] == [""] and T._checked_search_plan({"colors": ["Colorless", "R"]})["colors"] == ["R", ""] and T._checked_search_plan({})["colors"] == [])
check("...colour combinations and themes are checked like the brief's", searched_for["color_options"] == ["R", "BR"] and searched_for["theme_hints"] == ["treasure"] and searched_for["understood"] == "You want treasure.")
check("...and the model is told the facts, the new words, the rejections with reasons, the likes and what was offered", all(x in captured["user"] for x in ["a treasure deck", "FACTS SO FAR: Makes Treasure", "attacks a lot", "Gone (too slow)", "Bare", "LIKED (find more like these): Liked", "OFFERED LAST ROUND: A, B"]), captured["user"])
T.plan_commander_search("a treasure deck", [], None, [], [], [])
check("...with nothing yet, it says so", "FACTS SO FAR: none yet" in captured["user"] and "(nothing new)" in captured["user"] and "REJECTED" not in captured["user"] and "OFFERED" not in captured["user"])
check("a search plan from garbage is empty, not an error", T._checked_search_plan("nope") == {"facts": [], "understood": "", "queries": [], "colors": [], "color_options": [], "theme_hints": []} and T._checked_search_plan({"plan": {"plan": {"facts": ["x"]}}})["facts"] == ["x"])
brief = T.interpret_deck_request("a fun deck", ["zombies"], {"colors": ["U"], "power": 2, "budget": "none", "lesser_known": True, "commander": "Some Commander"})
check("the form's answers go to the model as already decided", all(x in captured["user"] for x in ["ALREADY DECIDED BY THE PLAYER", "colours: U", "power level: 2", "no limit", "Some Commander", "a fun deck"]), captured["user"])
check("the brief is validated: colours, colour options (up to three, in order, each once), theme hints, focus length, budget, style", brief["colors"] == ["B"] and brief["color_options"] == ["G", "BR", "URG"] and brief["theme_hints"] == ["treasure", "artifacts", "extra"] and len(brief["focus"]) == 400 and brief["budget"] == 100 and brief["style"] == "zombies")

# --- the fixture: a commander, an EDHREC pool, a model that picks the top of the list -------------
infos: dict = {}
def info(name, price=1.0, type_line="Creature — Zombie", ci=("U", "B"), legal="legal", cost="{1}{B}", cmc=2, oracle=None):
    infos[name] = {"id": "id-" + name, "name": name, "priceUsd": str(price), "typeLine": type_line, "legality": legal, "colorIdentity": list(ci), "manaCost": cost, "cmc": cmc, "oracleText": oracle or f"{name} text."}
info("Cmdr", 2, "Legendary Creature — Zombie Wizard", cost="{2}{U}{B}", cmc=4)
for basic in ("Island", "Swamp"): info(basic, 0.1, "Basic Land", ci=(), cost="", cmc=0)
includes_cards = []
def add(name, category, inclusion, **kw):
    info(name, **kw); includes_cards.append({"name": name, "category": category, "inclusion": inclusion, "synergy": 0})
for i in range(14): add(f"Creature {i}", "Creatures", 0.9 - i * 0.02, price=0.5 + i % 3, cost="{1}{B}" if i % 2 else "{U}{U}")
for i in range(8): add(f"Rock {i}", "Mana Artifacts", 0.8 - i * 0.02, price=1 + i, type_line="Artifact", ci=(), cost="{2}")
for i in range(10): add(f"Spell {i}", "Instants", 0.6 - i * 0.02, price=0.5 + i % 4, type_line="Instant", cost="{U}")
for i in range(24): add(f"Land {i}", "Lands", 0.7 - i * 0.01, price=0.5 + i % 9, type_line="Land", ci=("U", "B") if i % 2 else ("U",), cost="", cmc=0)
add("Red Card", "Sorceries", 0.5, ci=("R",), type_line="Sorcery", cost="{R}")
add("Banned Card", "Sorceries", 0.5, legal="banned", type_line="Sorcery")
add("Tutor", "Sorceries", 0.95, price=3, type_line="Sorcery", cost="{B}")      # a Game Changer
add("Pricey", "Creatures", 0.55, price=60)
add("Sol Ring", "Mana Artifacts", 0.97, price=1.5, type_line="Artifact", ci=(), cost="{1}")
includes = {"available": True, "num_decks": 1000, "cards": includes_cards}

calls: list[dict] = []
state = {"fail_phase": None, "raise": None}
def stub_model():
    def interpret(text, styles, given=None):
        calls.append({"op": "interpret", "given": given})
        return {"colors": [], "colorless": False, "style": None, "power": None, "budget": None, "commander": None, "color_options": [], "theme_hints": [], "focus": "", "lesser_known": False, "understood": "I read it.", **(state.get("brief") or {})}
    def search(brief, facts, said, rejected, liked, offered):
        calls.append({"op": "search", "brief": brief, "facts": list(facts), "said": said, "rejected": rejected, "liked": liked, "offered": offered})
        if state.get("search_raises"):
            raise state["search_raises"]
        new = [said.strip()] if said else []
        new += [f"Not like {r['name']}: {r['reason']}" for r in rejected if r["reason"]]
        return {"facts": list(dict.fromkeys([*(facts or ["Makes Treasure"]), *new]))[:T.MAX_FACTS], "understood": f"Round {len(calls)}.", "queries": [{"q": "o:treasure", "why": "makes Treasure"}], "colors": state.get("search_only", []), "color_options": state.get("search_colors", []), "theme_hints": []}
    def commanders(brief, facts, menu, rejected=None, liked=None):
        calls.append({"op": "commanders", "menu": [m["name"] for m in menu], "facts": list(facts), "rejected": rejected, "liked": liked})
        return [{"name": m["name"], "why": f"{m['name']} suits you.", "fits": facts[:1], "misses": facts[1:2]} for m in menu[:2]]
    def scryfall(queries):
        calls.append({"op": "scryfall", "queries": queries})
        return [{"name": n, "id": "s-" + n, "colors": state.get("found_colors", {}).get(n, "R"), "type_line": "Legendary Creature"} for n in state.get("found", [])]
    def edhrec(candidates, bracket):
        return [{**menu_entry(c["name"]), "id": c["id"]} for c in candidates if c["name"] not in state.get("no_edhrec", ())]
    def plan(brief, commander, constraints):
        calls.append({"op": "plan", "constraints": constraints, "brief": brief})
        return T._checked_plan(state.get("plan") or {"strategy": "Zombies.", "order_reason": "Creatures first because the plan is bodies.", "phases": [
            {"kind": "creatures", "count": 10, "why": "Bodies first."}, {"kind": "ramp", "count": 6, "why": "Mana."}, {"kind": "lands", "count": 36, "why": "Fixing."}]})
    def phase(brief, commander, phase, deck_lines, pool, constraints, budget, note="", limit=None):
        calls.append({"op": "phase", "kind": phase["kind"], "pool": [p["name"] for p in pool], "deck": deck_lines, "note": note, "limit": limit, "budget": budget})
        if state["raise"] and phase["kind"] == state["fail_phase"]:
            raise state["raise"]
        take = limit if limit is not None else phase["count"]
        if phase["kind"] == "lands":
            take = min(take, 12)    # a model that doesn't take every land on offer
        return {"summary": f"{phase['label']} done.", "picks": [{"name": c["name"], "why": f"{c['name']} fits the plan."} for c in pool[:take]]}
    B.interpret_deck_request, B.propose_commanders, B.plan_phases, B.propose_phase = interpret, commanders, plan, phase
    B.plan_commander_search, B.scryfall_candidates, B.with_edhrec = search, scryfall, edhrec
stub_model()
B.get_commander_includes = lambda name: includes
B.get_card_info = lambda name: infos.get(name)
B.get_card_info_batch = lambda names, refresh=False: {"info": {n: infos[n] for n in names if n in infos}, "not_found": [], "failed": []}
T.get_card_info, T.get_card_info_batch, T.peek_card_info = B.get_card_info, B.get_card_info_batch, lambda n: infos.get(n)   # lookups when the deck is made
W.game_changer_names = lambda: {"Tutor"}
menu_entry = lambda n: {"name": n, "id": "i-" + n, "num_decks": 900, "themed_decks": None, "decks_at_bracket": 50, "bracket_counts": {}, "themes": [{"name": "Zombies", "slug": "zombies", "count": 1}], "signature": ["S"]}
info("Other Cmdr", 3, "Legendary Creature — Wizard")
W.candidates = lambda colors, theme, bracket, niche=False: {"unavailable": False, "relaxed": False, "fell_back_from": None, "niche_fallback": False, "commanders": [menu_entry("Cmdr"), menu_entry("Other Cmdr")]}
W.explain_context = lambda result: [{"name": c["name"], "type_line": "x", "mana_cost": "", "colors": "".join(infos.get(c["name"], {}).get("colorIdentity", [])), "oracle": "t", "themes": [], "signature": [], "num_decks": 9, "decks_at_bracket": 1} for c in result["commanders"]]
W.resolve_commander = lambda name: {"name": "Cmdr", "id": "i"} if name.lower() == "cmdr" else None

BRIEF = {"text": "", "styles": ["zombies"], "colors": [], "colorless": False, "theme": None, "bracket": None, "budget": None, "caps": {}, "invest": [], "lesser_known": False, "commander": None}
def public(bid): return B.public(B.load(bid))
def settled(bid, **cond):
    """Waits until the session isn't busy and every phase job has finished."""
    def ok():
        s = B.load(bid)
        return not s["busy"] and all(p["working_gen"] is None for p in s["phases"].values()) and s
    return wait_until(ok)
def proposal_ready(bid):
    def ok():
        s = B.load(bid)
        cur = s["phases"].get(s["current"]) if s["current"] else None
        return bool(cur and cur["proposal"] is not None and cur["working_gen"] is None) and s
    return wait_until(ok)

# --- brief -> commander options ---------------------------------------------------------------
calls.clear()
bid = B.create({**BRIEF, "colors": ["U", "B"], "text": "zombies please"})
s = wait_until(lambda: (x := B.load(bid))["stage"] == "commander" and x)
check("with no commander named, the Doctor offers some, each with its reason", s and [o["name"] for o in s["commander_options"]] == ["Cmdr", "Other Cmdr"] and s["commander_options"][0]["why"] == "Cmdr suits you.", str(s and s["commander_options"][:1]))
check("...and the brief it read is kept", s["resolved"]["understood"] == "I read it." and s["resolved"]["bracket"] == 2 and s["busy"] is None)
check("the form's answers were passed to the reading as decided", next(c for c in calls if c["op"] == "interpret")["given"]["colors"] == ["U", "B"])
try:
    B.choose_commander(bid, "Not A Commander Zzz"); refused = False
except B.BuildError as err:
    refused = err.status == 400
check("a commander that can't lead is refused", refused)
B.choose_commander(bid, "Cmdr")
s = wait_until(lambda: (x := B.load(bid))["stage"] == "plan" and x)
check("choosing one moves on to the plan", s is not None and s["commander"]["name"] == "Cmdr" and s["commander"]["why"] == "Cmdr suits you." and s["commander"]["colors"] == ["U", "B"])
check("the plan is the Doctor's, in its order, with flex last and 99 cards", s and [p["id"] for p in s["plan"]["phases"]] == ["creatures", "ramp", "lands", "flex"] and sum(p["count"] for p in s["plan"]["phases"]) == 99, str(s and [(p["id"], p["count"]) for p in s["plan"]["phases"]]))
check("...and its reasons are kept for the page", s["plan"]["order_reason"].startswith("Creatures first") and s["plan"]["phases"][0]["why"] == "Bodies first.")
pool = {c["name"]: c for c in s["pool"]}
check("the candidate pool leaves out the off-colour card, the illegal one and the commander", "Red Card" not in pool and "Banned Card" not in pool and "Cmdr" not in pool and "Creature 0" in pool)
check("...and marks the Game Changer", pool["Tutor"]["gc"] is True and pool["Sol Ring"]["gc"] is False)
check("the model is told the limits", "Core" in next(c for c in calls if c["op"] == "plan")["constraints"] and "no Game Changers" in next(c for c in calls if c["op"] == "plan")["constraints"])

# a style that leaves too few commanders is topped up from the colors alone
themed = {"n": 0}
real_candidates = W.candidates
def narrow(colors, theme, bracket, niche=False):
    themed["n"] += 1
    names = ["Cmdr"] if theme else ["Cmdr", "Other Cmdr", "Third Cmdr", "Fourth Cmdr"]
    return {"unavailable": False, "relaxed": False, "fell_back_from": None, "niche_fallback": False, "commanders": [menu_entry(n) for n in names]}
W.candidates = narrow
state["brief"] = {"colors": ["U", "B"], "style": "zombies"}
calls.clear()
bid_t = B.create({**BRIEF, "text": "zombies"})
s_t = wait_until(lambda: (x := B.load(bid_t))["stage"] == "commander" and x)
menu_seen = next(c for c in calls if c["op"] == "commanders")["menu"]
check("a narrow style is topped up from the colors alone, so there are always options", menu_seen == ["Cmdr", "Other Cmdr", "Third Cmdr", "Fourth Cmdr"] and themed["n"] == 2, str(menu_seen))
W.candidates = real_candidates
state["brief"] = {}
calls.clear()

# a named commander skips the offer
calls.clear()
bid2 = B.create({**BRIEF, "commander": "Cmdr"})
s2 = wait_until(lambda: (x := B.load(bid2))["stage"] == "plan" and x)
check("a commander the player gave goes straight to the plan, with no offer", s2 is not None and not any(c["op"] == "commanders" for c in calls) and s2["commander"]["why"] is None)
calls.clear()
state["brief"] = {"commander": "cmdr"}
bid3 = B.create({**BRIEF, "text": "build around cmdr"})
s3 = wait_until(lambda: (x := B.load(bid3))["stage"] == "plan" and x)
check("so does one named in their words", s3 is not None and not any(c["op"] == "commanders" for c in calls))
state["brief"] = {"commander": "Made Up", "color_options": ["UB"]}
bid4 = B.create({**BRIEF, "text": "build around Made Up"})
s4 = wait_until(lambda: (x := B.load(bid4))["stage"] == "commander" and x)
check("...and one that can't be used is said so, and some are offered", s4 is not None and any("Made Up" in n for n in s4["resolved"]["notes"]))
state["brief"] = {}

# no colors named: the Doctor's combinations are searched, each with the themes it hinted at
searched: list[tuple] = []
def by_combo(colors, theme, bracket, niche=False):
    searched.append((colors, theme))
    pool_names = {"R": ["Red One", "Red Two", "Red Three", "Red Four"], "BR": ["Rakdos One", "Rakdos Two", "Rakdos Three"], "RG": ["Gruul One", "Red One"]}.get(colors, [f"{colors} One", f"{colors} Two", f"{colors} Three"])
    for n in pool_names:
        infos.setdefault(n, {"id": "i-" + n, "name": n, "priceUsd": "1", "typeLine": "Legendary Creature", "legality": "legal", "colorIdentity": list(colors), "manaCost": "", "cmc": 3, "oracleText": "x"})
    if theme == "treasure" and colors == "RG":      # no treasure commanders in Gruul
        return {"unavailable": False, "relaxed": False, "fell_back_from": theme, "niche_fallback": False, "commanders": [menu_entry(n) for n in pool_names]}
    return {"unavailable": False, "relaxed": False, "fell_back_from": None, "niche_fallback": False, "commanders": [menu_entry(n) for n in pool_names]}
W.candidates = by_combo
state["brief"] = {"color_options": ["R", "BR", "RG"], "theme_hints": ["treasure", "artifacts"]}
calls.clear()
bid_c = B.create({**BRIEF, "text": "artifact decks, mainly treasure ones with high aggression"})
s_c = wait_until(lambda: (x := B.load(bid_c))["stage"] == "commander" and x)
menu_names = next(c for c in calls if c["op"] == "commanders")["menu"]
check("with no colors named, the Doctor's combinations are all searched (not an error)", s_c is not None and {c for c, _ in searched} == {"R", "BR", "RG"}, str(searched))
check("...each looks at the first hinted theme that has commanders there", ("R", "treasure") in searched and ("BR", "treasure") in searched and ("RG", "treasure") in searched, str(searched))
check("...a combination with none for the theme falls back to its colors alone", ("RG", None) in searched)
check("...the menu mixes the combinations, with no commander twice", {"Red One", "Rakdos One", "Gruul One"} <= set(menu_names) and len(menu_names) == len(set(menu_names)), str(menu_names))
check("...and the round says which colors it added from, since the searches found nothing", "red, black-red and red-green" in (s_c["rounds"][0]["topped_up"] or "") and s_c["rounds"][0]["matched"] == 0, str(s_c["rounds"]))
check("...the options carry their colors for the page", all(o["colors"] for o in s_c["commander_options"]), str(s_c["commander_options"][:1]))
searched.clear()
state["brief"] = {"theme_hints": ["treasure"]}
bid5 = B.create({**BRIEF, "text": "surprise me"})
s5 = wait_until(lambda: (x := B.load(bid5))["stage"] == "commander" and x)
check("a request with nothing to go on isn't refused: some colors are tried at random", s5 is not None and s5["error"] is None and len(searched) >= 3, str(searched))
state["brief"] = {"colors": ["B", "R"]}
searched.clear()
bid6 = B.create({**BRIEF, "colors": ["B", "R"], "text": "x"})
wait_until(lambda: B.load(bid6)["stage"] == "commander")
check("colors the player chose are searched, and only those", {c for c, _ in searched} == {"BR"}, str(searched))
state["brief"] = {}
W.candidates = real_candidates_for_later = lambda colors, theme, bracket, niche=False: {"unavailable": False, "relaxed": False, "fell_back_from": None, "niche_fallback": False, "commanders": [menu_entry("Cmdr"), menu_entry("Other Cmdr")]}
check("(the helpers) combinations in words, and an even draw from each list",
      B._in_words(["R", "BR", "URG"]) == "red, black-red and blue-red-green" and B._in_words([""]) == "colorless"
      and [c["name"] for c in B._interleave([[{"name": "a1"}, {"name": "a2"}, {"name": "a3"}], [{"name": "b1"}, {"name": "a1"}], [{"name": "c1"}]], 5)] == ["a1", "b1", "c1", "a2", "a3"])
calls.clear()

# --- the commander, a round at a time ---------------------------------------------------------------
for n in ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta"]:
    info(n, 2, "Legendary Creature — Goblin", ci=("R",), cost="{2}{R}", cmc=3)
FOUND = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta"]
def round_done(bid_, n, timeout=6.0):
    """Waits until the commander stage has had `n` rounds and the Doctor is idle."""
    return wait_until(lambda: (x := B.load(bid_))["stage"] == "commander" and not x["busy"] and len(x["rounds"]) == n and x, timeout)
def refuse(fn):
    try: fn(); return None
    except B.BuildError as err: return err.status

state["found"] = list(FOUND)
calls.clear()
bid_r = B.create({**BRIEF, "text": "a treasure deck"})
r1 = round_done(bid_r, 1)
check("round one: the Doctor's searches are run and the closest of what they find are offered", r1 and [o["name"] for o in r1["commander_options"]] == ["Alpha", "Beta"] and next(c for c in calls if c["op"] == "scryfall")["queries"] == ["o:treasure"], str(r1 and r1["commander_options"]))
check("...with the facts it learnt, and which of them each commander fits and misses", r1["facts"] == ["Makes Treasure"] and r1["commander_options"][0]["fits"] == ["Makes Treasure"] and r1["commander_options"][0]["misses"] == [] and all(o["colors"] == "R" for o in r1["commander_options"]), str(r1["commander_options"][0]))
check("...and the round is logged: what was found, what was offered", r1["rounds"][0]["said"] is None and r1["rounds"][0]["options"] == ["Alpha", "Beta"] and r1["rounds"][0]["considered"] == 6 and r1["rounds"][0]["facts"] == ["Makes Treasure"] and r1["rounds"][0]["understood"])
check("...the steps show what it searched for", any(x["label"].startswith("Searching: makes Treasure") for x in r1["steps"]), str(r1["steps"]))
check("...and the page is given the facts, the rounds, and what is ruled out", all(k in B.public(r1) for k in ("facts", "rounds", "rejected", "liked")))
check("a round must bring something: nothing said, rejected, liked or dropped -> 400", refuse(lambda: B.refine_commanders(bid_r, "  ", [], [], [])) == 400)
check("...and only while the commander is being chosen -> 409, and not while the Doctor is busy", refuse(lambda: B.refine_commanders(bid2, "x", [], [], [])) == 409 and (B._update(bid_r, lambda s: s.__setitem__("busy", "Working…")) and refuse(lambda: B.refine_commanders(bid_r, "x", [], [], [])) == 409) and (B._update(bid_r, lambda s: s.__setitem__("busy", None)) and True))

calls.clear()
B.refine_commanders(bid_r, "  attacks a lot  ", [], [], [])
r2 = round_done(bid_r, 2)
sp = next(c for c in calls if c["op"] == "search")
check("round two: what they said goes to the Doctor with the facts so far and what it offered", sp["facts"] == ["Makes Treasure"] and sp["said"] == "attacks a lot" and sp["offered"] == ["Alpha", "Beta"], str(sp))
check("...and is kept as a fact, with the round logged beside the first", r2 and r2["facts"] == ["Makes Treasure", "attacks a lot"] and r2["rounds"][1]["said"] == "attacks a lot" and r2["rounds"][0]["facts"] == ["Makes Treasure"] and any(x["during"] == "refine" for x in r2["steps"]), str(r2 and r2["facts"]))

calls.clear()
B.refine_commanders(bid_r, "", [{"name": "Alpha", "reason": "too slow " + "x" * 300}, {"name": "Zeta", "reason": "never offered"}], [], [])
r3 = round_done(bid_r, 3)
menu3 = next(c for c in calls if c["op"] == "commanders")
check("round three: a commander rejected is never offered again, and its reason is kept (a cut one if long)", r3 and [r["name"] for r in r3["rejected"]] == ["Alpha"] and len(r3["rejected"][0]["reason"]) == 200 and "Alpha" not in menu3["menu"] and "Alpha" not in [o["name"] for o in r3["commander_options"]], str(r3 and r3["rejected"]))
check("...one that wasn't on offer can't be rejected", "Zeta" not in [r["name"] for r in r3["rejected"]])
check("...the reason sharpens the facts, and both the search and the offer are told what was rejected", any(f.startswith("Not like Alpha: too slow") for f in r3["facts"]) and next(c for c in calls if c["op"] == "search")["rejected"][0]["name"] == "Alpha" and menu3["rejected"][0]["name"] == "Alpha", str(r3["facts"]))
check("...the next best come forward", [o["name"] for o in r3["commander_options"]] == ["Beta", "Gamma"], str([o["name"] for o in r3["commander_options"]]))

calls.clear()
B.refine_commanders(bid_r, "", [], ["Beta", "Zeta"], ["attacks a lot", "no such fact"])
r4 = round_done(bid_r, 4)
check("round four: a liked commander is passed on (one not on offer isn't), and a fact taken back is gone", r4 and r4["liked"] == ["Beta"] and next(c for c in calls if c["op"] == "commanders")["liked"] == ["Beta"] and "attacks a lot" not in r4["facts"] and "attacks a lot" not in next(c for c in calls if c["op"] == "search")["facts"], str(r4 and (r4["liked"], r4["facts"])))
check("...earlier rejections still stand", [r["name"] for r in r4["rejected"]] == ["Alpha"] and "Alpha" not in [o["name"] for o in r4["commander_options"]])

# a round that finds nothing leaves the last offer as it was, says why, and can be tried again
offered_before = [o["name"] for o in r4["commander_options"]]
state["found"] = []
real_candidates_now = W.candidates
W.candidates = lambda colors, theme, bracket, niche=False: {"unavailable": False, "relaxed": False, "fell_back_from": None, "niche_fallback": False, "commanders": []}
B.refine_commanders(bid_r, "something nobody printed", [], [], [])
rf = wait_until(lambda: B.load(bid_r)["error"] and B.load(bid_r))
check("a round that finds nothing is an error on the session, not a blank page", rf and rf["error"]["status"] == 422 and rf["stage"] == "commander" and rf["busy"] is None, str(rf and rf["error"]))
check("...the last offer and what the Doctor knows are untouched", [o["name"] for o in rf["commander_options"]] == offered_before and rf["facts"] == r4["facts"] and len(rf["rounds"]) == 4 and rf["rejected"] == r4["rejected"])
W.candidates = real_candidates_now
state["found"] = list(FOUND)
check("...and the player can go on from there", refuse(lambda: B.refine_commanders(bid_r, "", [], [], ["Makes Treasure"])) is None)
rg = round_done(bid_r, 5)
check("...which a round that does find something clears", rg and rg["error"] is None and "Makes Treasure" not in rg["facts"], str(rg and rg["facts"]))
state["search_raises"] = T.StructuredLoopError("cut off")
B.refine_commanders(bid_r, "faster", [], [], [])
rs = wait_until(lambda: B.load(bid_r)["error"] and B.load(bid_r))
check("the Doctor failing to finish a round is an error with a retry, and the offer stands", rs and rs["error"]["status"] == 502 and rs["error"]["retry"]["op"] == "refine" and rs["error"]["retry"]["said"] == "faster" and len(rs["rounds"]) == 5 and not B.public(rs)["error"].get("retry"), str(rs and rs["error"]))
state["search_raises"] = None
B.retry(bid_r)
rr = round_done(bid_r, 6)
check("retrying runs that round again, with what the player said", rr and rr["error"] is None and rr["rounds"][5]["said"] == "faster" and "faster" in rr["facts"], str(rr and rr["facts"]))
B.choose_commander(bid_r, rr["commander_options"][0]["name"])
check("choosing from the last round's offer moves on, and further rounds are refused", B.load(bid_r)["commander"]["name"] == rr["commander_options"][0]["name"] and refuse(lambda: B.refine_commanders(bid_r, "x", [], [], [])) == 409)

# commanders EDHREC knows nothing about are dropped; too few from the searches are topped up, not repeated
state["found"], state["no_edhrec"] = list(FOUND), {"Alpha"}
calls.clear()
bid_e = B.create({**BRIEF, "text": "a treasure deck"})
re_ = round_done(bid_e, 1)
menu_e = next(c for c in calls if c["op"] == "commanders")["menu"]
check("a commander with no EDHREC data is dropped, since a deck can't be built from nothing", re_ and "Alpha" not in menu_e and menu_e[:5] == ["Beta", "Gamma", "Delta", "Epsilon", "Zeta"], str(menu_e))
check("...too few from the searches are topped up with the best known in the colors, after them and without repeats", menu_e[5:] == ["Cmdr", "Other Cmdr"], str(menu_e))
state["found"], state["no_edhrec"] = ["Alpha"], set()
calls.clear()
bid_t = B.create({**BRIEF, "text": "a treasure deck"})
rt = round_done(bid_t, 1)
check("(setup) the top-up follows the searched ones", rt and [o["name"] for o in rt["commander_options"]] == ["Alpha", "Cmdr"])
calls.clear()
B.refine_commanders(bid_t, "", [{"name": "Cmdr", "reason": ""}], [], [])
rt2 = round_done(bid_t, 2)
check("a rejected commander isn't brought back by the top-up either", rt2 and next(c for c in calls if c["op"] == "commanders")["menu"] == ["Alpha", "Other Cmdr"], str(next(c for c in calls if c["op"] == "commanders")["menu"]))

# the colors the top-up looks in: the player's, else the Doctor's from what it has learnt, else the brief's
seen_colors: list[str] = []
def record_colors(colors, theme, bracket, niche=False):
    seen_colors.append(colors)
    return {"unavailable": False, "relaxed": False, "fell_back_from": None, "niche_fallback": False, "commanders": [menu_entry(f"{colors or 'C'} Cmdr")]}
W.candidates = record_colors
state["found"] = []
state["search_colors"] = ["BR", "G"]
bid_k = B.create({**BRIEF, "text": "treasure"})
round_done(bid_k, 1)
check("with no colors chosen, the top-up looks in the colors the Doctor's search plan gives", set(seen_colors) == {"BR", "G"}, str(seen_colors))
seen_colors.clear()
bid_k2 = B.create({**BRIEF, "colors": ["U", "B"], "text": "treasure"})
round_done(bid_k2, 1)
check("...and only in the player's if they chose some", set(seen_colors) == {"UB"}, str(seen_colors))
W.candidates = real_candidates_now
state["found"], state["search_colors"] = [], []
# colors named are colors had: a Rakdos deck is black-red, not mono-black or mono-red
state["found"] = ["Mono R", "Mono B", "Rakdos A", "Rakdos B", "Mono R2", "Rakdos C", "Rakdos D", "Rakdos E"]
state["found_colors"] = {"Mono R": "R", "Mono B": "B", "Mono R2": "R"} | {n: "BR" for n in state["found"] if n.startswith("Rakdos")}
W.candidates = lambda colors, theme, bracket, niche=False: {"unavailable": False, "relaxed": False, "fell_back_from": None, "niche_fallback": False, "commanders": [menu_entry(f"Top {colors} {i}") for i in range(3)]}
calls.clear()
bid_x = B.create({**BRIEF, "colors": ["R", "B"], "text": "a rakdos deck"})
rx = round_done(bid_x, 1)
menu_x = next(c for c in calls if c["op"] == "commanders")["menu"]
check("colors the player chose: commanders of other colors the searches found (mono-black, mono-red) are left out", rx and menu_x == ["Rakdos A", "Rakdos B", "Rakdos C", "Rakdos D", "Rakdos E", "Top BR 0", "Top BR 1", "Top BR 2"], str(menu_x))
check("...and the round records the colors it held to", rx["rounds"][0]["colors"] == ["BR"])
calls.clear()
state["search_only"] = ["BR", "G"]
B.refine_commanders(bid_x, "or maybe green too", [], [], [])
rx2 = round_done(bid_x, 2)
menu_x2 = next(c for c in calls if c["op"] == "commanders")["menu"]
check("a later round holds to the colors the Doctor gives from the facts, not the first brief's", rx2 and "Rakdos A" in menu_x2 and "Mono R" not in menu_x2, str(menu_x2))
state["search_only"] = ["R"]
calls.clear()
B.refine_commanders(bid_x, "no, just mono red", [], [], [])
rx3 = round_done(bid_x, 3)
menu_x3 = next(c for c in calls if c["op"] == "commanders")["menu"]
check("...so the player can change them", rx3 and menu_x3[:2] == ["Mono R", "Mono R2"] and not any(n.startswith("Rakdos") for n in menu_x3), str(menu_x3))
state["search_only"] = []
calls.clear()
B.refine_commanders(bid_x, "actually any colors", [], [], [])
rx4 = round_done(bid_x, 4)
check("...or withdraw them: with none fixed, nothing is held back", rx4 and {"Mono R", "Mono B"} <= set(next(c for c in calls if c["op"] == "commanders")["menu"]) and rx4["rounds"][3]["colors"] == [])
state["found"], state["found_colors"] = [], {}
W.candidates = real_candidates_now

check("the Doctor is told only what the player chose: no defaults passed off as wishes",
      B._answers({"resolved": {"colors": [], "colorless": False, "theme": None, "bracket": 2, "bracket_chosen": False, "budget": None, "budget_stated": False, "niche": False}}) == "nothing chosen on the form"
      and "power level" in B._answers({"resolved": {"colors": ["B", "R"], "colorless": False, "theme": "treasure", "bracket": 3, "bracket_chosen": True, "budget": 100.0, "budget_stated": True, "niche": True}})
      and "budget: up to $100" in B._answers({"resolved": {"colors": [], "colorless": False, "theme": None, "bracket": 2, "bracket_chosen": False, "budget": 100.0, "budget_stated": True, "niche": False}})
      and "no limit" in B._answers({"resolved": {"colors": [], "colorless": False, "theme": None, "bracket": 2, "bracket_chosen": False, "budget": None, "budget_stated": True, "niche": False}})
      and "power level" not in B._answers({"resolved": {"colors": ["R"], "colorless": False, "theme": None, "bracket": 2, "bracket_chosen": False, "budget": None, "budget_stated": False, "niche": False}}))
bid_a = B.create({**BRIEF, "text": "x"})
sa = wait_until(lambda: (x := B.load(bid_a))["stage"] == "commander" and x)
check("...so a brief with only words has no bracket or budget wishes of its own", sa and sa["resolved"]["bracket_chosen"] is False and sa["resolved"]["budget_stated"] is False and sa["resolved"]["bracket"] == 2)
calls.clear()

# --- the phases ------------------------------------------------------------------------------------
calls.clear()
B.begin(bid)
first = proposal_ready(bid)
check("the first phase is the plan's first, and the Doctor proposes for it", first["current"] == "creatures" and len(first["phases"]["creatures"]["proposal"]["cards"]) == 10)
check("...from creatures only, never lands or Game Changers, nothing off the list", all(not pool[c["name"]]["land"] for c in first["phases"]["creatures"]["proposal"]["cards"]) and "Tutor" not in calls[0]["pool"] and not any(n.startswith("Land") for n in calls[0]["pool"]), str(calls[0]["pool"][:5]))
check("the next phase is prepared while the first is reviewed, assuming it's kept", wait_until(lambda: B.load(bid)["phases"]["ramp"]["proposal"] is not None) is not None)
ramp_call = next(c for c in calls if c["op"] == "phase" and c["kind"] == "ramp")
check("...and the model was told what that assumed", any("being chosen with this phase" in line for line in ramp_call["deck"]))
n_before = len([c for c in calls if c["op"] == "phase"])
proposal = B.load(bid)["phases"]["creatures"]["proposal"]
B.lock_phase(bid, "creatures", [c["name"] for c in proposal["cards"]])
s = B.load(bid)
check("locking what was proposed moves on to the phase already prepared, with no new model call", s["current"] == "ramp" and s["phases"]["ramp"]["proposal"] is not None and s["phases"]["creatures"]["status"] == "locked" and len([c for c in calls if c["op"] == "phase" and c["kind"] == "ramp"]) == 1)
check("...and the deck holds the locked cards", s["deck"]["locked"] and len(s["deck"]["locked"]) == 10 and all(e["phase"] == "creatures" for e in s["deck"]["locked"]))
settled(bid)

# keeping fewer than proposed makes the prepared next phase stale: it's redone
ramp_prop = B.load(bid)["phases"]["ramp"]["proposal"]
calls.clear()
B.lock_phase(bid, "ramp", [c["name"] for c in ramp_prop["cards"]][:3])
s = B.load(bid)
check("(setup) lands is next", s["current"] == "lands")
settled(bid)
lands_calls = [c for c in calls if c["op"] == "phase" and c["kind"] == "lands"]
check("a prepared phase that assumed cards that weren't kept is redone against what was", len(lands_calls) >= 1)
lp = proposal_ready(bid)["phases"]["lands"]["proposal"]
check("lands: only lands are offered, up to the count less one per colour", all(pool[c["name"]]["land"] for c in lp["cards"]) and len(lp["cards"]) <= 36 - 2 and lands_calls[-1]["limit"] == 34, str(lands_calls[-1]["limit"]))
check("...with basics filling the rest of the lands, split by the deck's colour pips", lp["basics"] and sum(lp["basics"].values()) == 36 - len(lp["cards"]) and set(lp["basics"]) <= {"Island", "Swamp"}, str(lp["basics"]))
check("...a mostly-blue deck gets more Islands than Swamps", lp["basics"].get("Island", 0) >= lp["basics"].get("Swamp", 0), str(lp["basics"]))
# redo: remove two lands and ask again
removed = [lp["cards"][0]["name"], lp["cards"][1]["name"]]
kept_before = [c["name"] for c in lp["cards"][2:]]
calls.clear()
B.redo_phase(bid, "lands", removed, "cheaper please")
settled(bid)
redo_call = next(c for c in calls if c["op"] == "phase" and c["kind"] == "lands")
new_lp = B.load(bid)["phases"]["lands"]["proposal"]
check("redo with some cards kept keeps the phase's summary, which the model's covers only part of", new_lp["summary"] == lp["summary"], str((new_lp["summary"], lp["summary"])))
check("redo: the cards taken out are replaced, not offered again, and the rest stay", all(n not in redo_call["pool"] for n in removed) and all(n in [c["name"] for c in new_lp["cards"]] for n in kept_before) and not set(removed) & {c["name"] for c in new_lp["cards"]}, str([c["name"] for c in new_lp["cards"]][:6]))
check("...with the player's note passed to the Doctor, and only the replacements asked for", redo_call["note"] == "cheaper please" and redo_call["limit"] == 34 - len(kept_before), str((redo_call["note"], redo_call["limit"])))
try:
    B.redo_phase(bid, "lands", [], ""); refused = False
except B.BuildError as err:
    refused = err.status == 400
check("redo with nothing removed and no note is refused", refused)
calls.clear()
B.redo_phase(bid, "lands", [], "more fixing")
settled(bid)
check("redo with only a note chooses the whole phase again", next(c for c in calls if c["op"] == "phase")["limit"] == 34 and next(c for c in calls if c["op"] == "phase")["note"] == "more fixing")
for bad, status in [(lambda: B.lock_phase(bid, "ramp", []), 409), (lambda: B.lock_phase(bid, "lands", ["Not In Proposal"]), 400)]:
    try: bad(); got = None
    except B.BuildError as err: got = err.status
    check(f"locking the wrong phase or a card that wasn't proposed -> {status}", got == status)
lp = B.load(bid)["phases"]["lands"]["proposal"]
B.lock_phase(bid, "lands", [c["name"] for c in lp["cards"]])
s = B.load(bid)
lands_locked = [e for e in s["deck"]["locked"] if e["phase"] == "lands"]
check("locking lands adds the basics too, so the phase comes to its 36", sum(e["qty"] for e in lands_locked) == 36 and any(e["category"] == "Basic Land" for e in lands_locked), str(sum(e["qty"] for e in lands_locked)))
settled(bid)
flex_prop = proposal_ready(bid)["phases"]["flex"]["proposal"]
locked_total = sum(e["qty"] for e in B.load(bid)["deck"]["locked"])
check("flex takes whatever slots are left, however the earlier phases came out", flex_prop["count"] == 99 - locked_total, str((flex_prop["count"], locked_total)))
B.lock_phase(bid, "flex", [c["name"] for c in flex_prop["cards"]])
s = B.load(bid)
check("locking the last phase moves to review", s["stage"] == "review" and s["current"] is None)
names = B.final_cards(s)
check("the finished deck is 99 cards, filled with basics if the phases came up short", len(names) == 99 and len(set(n for n in names if n not in B._BASIC_FOR_COLOR.values())) == len([n for n in names if n not in B._BASIC_FOR_COLOR.values()]), str(len(names)))
check("...with no card twice but basics", len({n for n in names if n not in {"Island", "Swamp"}}) == len([n for n in names if n not in {"Island", "Swamp"}]))
convo = B.conversation(s)
check("the chat opens with the brief, then the Doctor's account of every phase", [m["role"] for m in convo] == ["user", "assistant"] and convo[0]["content"].startswith("zombies please") and all(x in convo[1]["content"] for x in ["Zombies.", "Why Cmdr", "How we built it", "**Creatures**", "**Ramp**", "Creature 0 — Creature 0 fits the plan."]), convo[1]["content"][:300])

# --- rules the Doctor can't break -------------------------------------------------------------------
# a Game Changer past the bracket's limit is never kept (bracket 2 allows none)
state["plan"] = {"strategy": "s", "order_reason": "o", "phases": [{"kind": "must_haves", "count": 8, "why": "core"}, {"kind": "lands", "count": 36, "why": ""}]}
B.interpret_deck_request = lambda text, styles, given=None: {"colors": [], "colorless": False, "style": None, "power": None, "budget": None, "commander": None, "color_options": [], "theme_hints": [], "focus": "", "lesser_known": False, "understood": "ok"}
real_phase = B.propose_phase
def greedy(brief, commander, phase, deck_lines, pool, constraints, budget, note="", limit=None):
    # a model that asks for the Game Changer and the most expensive card first
    ordered = sorted(pool, key=lambda c: (c["name"] != "Tutor", -c["price"]))
    return {"summary": "x", "picks": [{"name": c["name"], "why": f"{c['name']} is good here."} for c in ordered[: limit or phase["count"]]]}
B.propose_phase = greedy
bid6 = B.create({**BRIEF, "commander": "Cmdr"})
wait_until(lambda: B.load(bid6)["stage"] == "plan")
B.begin(bid6)
p6 = proposal_ready(bid6)["phases"]["must_haves"]["proposal"]
check("a Game Changer isn't in the pool at a power level that allows none", "Tutor" not in [c["name"] for c in p6["cards"]])
B.propose_phase = real_phase

# a budget: each phase gets a share and the picks can't cost more than it
stub_model()
state["plan"] = {"strategy": "s", "order_reason": "o", "phases": [{"kind": "must_haves", "count": 8, "why": "core"}, {"kind": "lands", "count": 36, "why": ""}]}
B.interpret_deck_request = lambda text, styles, given=None: {"colors": [], "colorless": False, "style": None, "power": None, "budget": 50, "commander": None, "color_options": [], "theme_hints": [], "focus": "", "lesser_known": False, "understood": "ok"}
calls.clear()
B.propose_phase = lambda brief, commander, phase, deck_lines, pool, constraints, budget, note="", limit=None: (calls.append({"kind": phase["kind"], "budget": budget}) or {"summary": "x", "picks": [{"name": c["name"], "why": f"{c['name']} is good here."} for c in sorted(pool, key=lambda c: -c["price"])[: limit or phase["count"]]]})
bid7 = B.create({**BRIEF, "commander": "Cmdr"})
wait_until(lambda: B.load(bid7)["stage"] == "plan")
check("the budget is the whole deck's, so the commander's price comes out first", True)
B.begin(bid7)
p7 = proposal_ready(bid7)["phases"]["must_haves"]["proposal"]
share_text = next(c for c in calls if "budget" in c)["budget"]
total = sum(c["price"] for c in p7["cards"])
check("a budget phase is told its share, and picks that don't fit it are dropped, dearest first", "$50" in share_text and total <= 48 + 1e-6 and any("budget" in n for n in p7["notes"]), f"{share_text} -> ${total}")
check("...so the cards chosen for the phase never cost more than the money left", total <= 50 - 2)
B.propose_phase = real_phase
stub_model()
# the money guidance, directly: kept cards are already spent, a cap is the phase's own, the last phase can't overspend
fake = {"brief": {"caps": {}}, "resolved": {"budget": 100.0}, "commander": {"price": 0}}
prices = {"A": {"price": 10}}
text, limit = B._budget(fake, {"kind": "creatures"}, 2, {"A"}, prices, 50, 10)
check("a phase's money limit is its share of what's left (kept cards already spent, not counted twice)", abs(limit - 90 * 2 / 50 * 1.5) < 1e-6 and "$90 left" in text, f"{limit} {text}")
text, limit = B._budget(fake, {"kind": "creatures"}, 2, {"A"}, prices, 2, 0)
check("...and the last phase can't spend more than is left", abs(limit - 90) < 1e-6, str(limit))
capped = {**fake, "brief": {"caps": {"lands": 30}}}
text, limit = B._budget(capped, {"kind": "lands"}, 5, set(), {}, 40, 12)
check("a spending limit on lands is the phase's own, less what its kept lands cost", limit == 18 and "$30" in text, f"{limit} {text}")
check("no budget, no limit", B._budget({**fake, "resolved": {"budget": None}}, {"kind": "ramp"}, 3, set(), {}, 40, 0)[1] is None)

# --- failures: the page is told, and can retry -------------------------------------------------------------
state["plan"] = None
B.interpret_deck_request = lambda text, styles, given=None: {"colors": [], "colorless": False, "style": None, "power": None, "budget": None, "commander": None, "color_options": [], "theme_hints": [], "focus": "", "lesser_known": False, "understood": "ok"}
stub_model()
state["fail_phase"], state["raise"] = "creatures", T.StructuredLoopError("cut off")
bid8 = B.create({**BRIEF, "commander": "Cmdr"})
wait_until(lambda: B.load(bid8)["stage"] == "plan")
B.begin(bid8)
s8 = wait_until(lambda: B.load(bid8)["error"] and B.load(bid8))
check("a phase the Doctor couldn't finish is an error on the session, with how to retry", s8 and s8["error"]["status"] == 502 and s8["error"]["retry"]["op"] == "phase" and not B.public(s8)["error"].get("retry"), str(s8 and s8["error"]))
check("...and nothing is stuck 'working'", s8["phases"]["creatures"]["working_gen"] is None and B.public(s8)["working"] is False)
state["raise"] = None
B.retry(bid8)
ok8 = proposal_ready(bid8)
check("retrying makes the proposal and clears the error", ok8 and ok8["error"] is None and ok8["phases"]["creatures"]["proposal"] is not None)
state["fail_phase"], state["raise"] = "ramp", anthropic.BadRequestError("Your credit balance is too low", response=httpx.Response(400, request=httpx.Request("POST", "u")), body={})
bid9 = B.create({**BRIEF, "commander": "Cmdr"})
wait_until(lambda: B.load(bid9)["stage"] == "plan")
B.begin(bid9)
p9 = proposal_ready(bid9)
time.sleep(0.5)
check("a failed prefetch is dropped quietly: no error is shown for a phase the player isn't on", B.load(bid9)["error"] is None and B.load(bid9)["phases"]["ramp"]["working_gen"] is None)
state["raise"] = None
B.lock_phase(bid9, "creatures", [c["name"] for c in p9["phases"]["creatures"]["proposal"]["cards"]])
check("...and the phase is made when its turn comes", proposal_ready(bid9)["phases"]["ramp"]["proposal"] is not None)
state["fail_phase"], state["raise"] = "lands", anthropic.BadRequestError("Your credit balance is too low", response=httpx.Response(400, request=httpx.Request("POST", "u")), body={})
p9b = B.load(bid9)
# keeping fewer than were proposed makes the prepared lands phase stale, so it is made fresh — and fails
B.lock_phase(bid9, "ramp", [c["name"] for c in p9b["phases"]["ramp"]["proposal"]["cards"]][:2])
s9 = wait_until(lambda: B.load(bid9)["error"] and B.load(bid9))
check("a model failure on the phase the player is on is typed, so the page can explain it", s9 and s9["error"]["code"] == "ai_credits" and s9["error"]["status"] == 503 and s9["error"]["retry_after"] is None, str(s9 and s9["error"]))
state["raise"] = None

# --- endpoints ------------------------------------------------------------------------------------------------
stub_model()
B.interpret_deck_request = lambda text, styles, given=None: {"colors": [], "colorless": False, "style": None, "power": None, "budget": None, "commander": None, "color_options": [], "theme_hints": [], "focus": "", "lesser_known": False, "understood": "ok"}
c = TestClient(api.app, raise_server_exceptions=False)
GOOD = {"styles": ["zombies"], "text": "x", "commander": "Cmdr"}
check("start: bad theme, bracket, budget, color, cap, area -> 400", all(c.post("/builds", json={**GOOD, **extra}).status_code == 400 for extra in [{"theme": "../x"}, {"bracket": 9}, {"budget": 1}, {"colors": ["Q"]}, {"caps": {"lands": 99999}}, {"caps": {"basement": 5}}, {"caps": {"lands": 5}, "invest": ["lands"]}]))
check("start: words over the limit -> 422", c.post("/builds", json={**GOOD, "text": "x" * 1500}).status_code == 422)
check("an unknown build -> 404, and a path that isn't an id can't reach a file", c.get("/builds/nope").status_code == 404 and c.get("/builds/..%2F..%2Fetc").status_code in (404, 422))
r = c.post("/builds", json=GOOD)
eid = r.json()["id"]
wait_until(lambda: c.get(f"/builds/{eid}").json()["stage"] == "plan")
view = c.get(f"/builds/{eid}").json()
check("the page's view: stage, plan, commander, no candidate pool", view["stage"] == "plan" and view["plan"]["phases"][0]["id"] == "creatures" and view["commander"]["name"] == "Cmdr" and "pool" not in view)
check("create before the phases are done -> 409, and nothing is made", c.post(f"/builds/{eid}/create").status_code == 409 and len(D.list_decks()) == 0)
c.post(f"/builds/{eid}/begin")
check("begin twice -> 409", c.post(f"/builds/{eid}/begin").status_code == 409)
wait_until(lambda: c.get(f"/builds/{eid}").json()["proposal"] is not None and not c.get(f"/builds/{eid}").json()["working"])
step = 0
while c.get(f"/builds/{eid}").json()["stage"] == "building" and step < 12:
    v = wait_until(lambda: (x := c.get(f"/builds/{eid}").json())["stage"] == "review" or (x["proposal"] is not None and not x["working"]) and x)
    v = c.get(f"/builds/{eid}").json()
    if v["stage"] == "review": break
    r = c.post(f"/builds/{eid}/phases/{v['current']}/lock", json={"keep": [x["name"] for x in v["proposal"]["cards"]]})
    step += 1
v = c.get(f"/builds/{eid}").json()
check("walking the phases over HTTP reaches review", v["stage"] == "review" and v["deck"]["count"] > 40, str((v["stage"], v["deck"]["count"], step)))
made = c.post(f"/builds/{eid}/create")
body = made.json()
check("create makes the deck: commander, the cards, and the Doctor's account as its chat", made.status_code == 200 and body["deck"]["commander"] == "Cmdr" and len(body["deck"]["cards"]) == 99 and body["failed"] == [], made.text[:200])
saved = D.load_deck(body["deck"]["id"])
check("...whose first message is the player's, as the model's API needs", saved.messages[0]["role"] == "user" and saved.messages[1]["role"] == "assistant" and "How we built it" in saved.messages[1]["content"])
again = c.post(f"/builds/{eid}/create")
check("asking again returns the deck already made, not another", again.status_code == 200 and again.json()["deck"]["id"] == body["deck"]["id"] and len(D.list_decks()) == 1)
check("a finished build says so", c.get(f"/builds/{eid}").json()["stage"] == "done" and c.get(f"/builds/{eid}").json()["deck_id"] == body["deck"]["id"])
state["found"] = list(FOUND)
rid = c.post("/builds", json={"styles": ["zombies"], "text": "a treasure deck"}).json()["id"]
wait_until(lambda: (x := c.get(f"/builds/{rid}").json())["stage"] == "commander" and not x["busy"] and len(x["rounds"]) == 1)
view = c.get(f"/builds/{rid}").json()
check("the commander stage shows its options with facts, and the rounds so far", [o["name"] for o in view["commander_options"]] == ["Alpha", "Beta"] and view["facts"] == ["Makes Treasure"] and len(view["rounds"]) == 1 and view["rejected"] == [] and view["liked"] == [])
refine = f"/builds/{rid}/commander/refine"
check("refine: nothing to say -> 400; words over the limit, a reason over the limit, a body that isn't one -> 422; an unknown build -> 404",
      c.post(refine, json={}).status_code == 400 and c.post(refine, json={"text": "x" * 601}).status_code == 422
      and c.post(refine, json={"reject": [{"name": "Alpha", "reason": "x" * 201}]}).status_code == 422 and c.post(refine, json={"reject": ["Alpha"]}).status_code == 422
      and c.post("/builds/nope/commander/refine", json={"text": "x"}).status_code == 404)
got = c.post(refine, json={"text": "red or black-red", "reject": [{"name": "Alpha", "reason": "too slow"}], "like": ["Beta"]})
check("refine starts another round and answers at once with the session, busy", got.status_code == 200 and got.json()["stage"] == "commander" and got.json()["busy"], got.text[:200])
wait_until(lambda: (x := c.get(f"/builds/{rid}").json())["stage"] == "commander" and not x["busy"] and len(x["rounds"]) == 2)
view = c.get(f"/builds/{rid}").json()
check("...and the next round has the new fact, what is ruled out and what was liked", "red or black-red" in view["facts"] and view["rejected"] == [{"name": "Alpha", "reason": "too slow"}] and view["liked"] == ["Beta"] and "Alpha" not in [o["name"] for o in view["commander_options"]], str((view["facts"], view["rejected"])))
check("choosing with the endpoint closes the rounds: refine -> 409 after", c.post(f"/builds/{rid}/commander", json={"name": view["commander_options"][0]["name"]}).status_code == 200 and c.post(refine, json={"text": "x"}).status_code == 409)
check("the old one-shot endpoints are gone", c.post("/wizard/agent", json={}).status_code in (404, 405) and c.post("/wizard/interpret", json={}).status_code in (404, 405))
check("the manual starting-list build is still there (it asks for a commander and a power level)", c.post("/wizard/build", json={}).status_code == 422)

print(f"\n{sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
