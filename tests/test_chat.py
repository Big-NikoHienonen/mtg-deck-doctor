"""Tests for the Doctor's chat: it proposes deck changes and never makes one, every proposal is
checked against the rules, and a turn cut off in the middle of a tool call is never saved. No
network and no model: both are stubbed. Run with

    uv run python tests/test_chat.py
"""

import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS

from fastapi.testclient import TestClient

import mtg_deck_doctor.deck as D
import mtg_deck_doctor.tool_loop as T
from mtg_deck_doctor import api

D.DECKS_DIR = Path(tempfile.mkdtemp()) / "decks"
results: list[bool] = []


def check(name: str, ok: object, detail: str = "") -> None:
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


# --- the fixture: a few cards, keyed by lowercase name -------------------------------------------

CARDS = {
    "prosper, tome-bound": ("Prosper, Tome-Bound", ["B", "R"], "Legendary Creature — Tiefling Warlock", True),
    "omnath, locus of rage": ("Omnath, Locus of Rage", ["G", "R"], "Legendary Creature — Elemental", True),
    "sol ring": ("Sol Ring", [], "Artifact", True),
    "lightning bolt": ("Lightning Bolt", ["R"], "Instant", True),
    "blood artist": ("Blood Artist", ["B"], "Creature — Vampire", True),
    "llanowar elves": ("Llanowar Elves", ["G"], "Creature — Elf Druid", True),
    "mana crypt": ("Mana Crypt", [], "Artifact", False),
    "mountain": ("Mountain", [], "Basic Land — Mountain", True),
    "cultivate": ("Cultivate", ["G"], "Sorcery", True),
}


def fake_lookup(name):
    card = CARDS.get(name.lower())
    if not card:
        return {"error": f"no card named {name!r} found, or Scryfall couldn't be reached right now"}
    return {"name": card[0], "color_identity": card[1], "oracle_text": f"Text of {card[0]}", "type_line": card[2], "legal_in_commander": card[3], "price_usd": "1.00"}


T.lookup_card = fake_lookup
T.refresh_if_stale = lambda deck: None


def make_deck(deck_id, cards=("Sol Ring", "Mountain"), commander="Prosper, Tome-Bound", identity=("B", "R")):
    deck = D.Deck(id=deck_id, commander=commander, commander_color_identity=list(identity), cards=list(cards))
    D.save_deck(deck)
    return deck


def change(action, name, why="It fits."):
    return {"action": action, "name": name, "why": why}


def outcome(deck, *changes):
    result = T.suggest_changes(deck, list(changes))
    return [a["name"] for a in result["accepted"]], {r["name"]: r["error"] for r in result["rejected"]}, result


# --- the chat can look and propose, never change ---------------------------------------------------

names = {t["name"] for t in T.TOOLS}
check("the chat's tools are lookups and suggest_changes, with nothing that changes the deck", names == {"lookup_card", "find_synergies", "search_cards", "get_edhrec_categories", "suggest_changes"}, str(sorted(names)))
check("every tool it is offered has an implementation", set(T.make_tool_implementations(D.Deck(id="x"))) == names)

# --- proposals are checked --------------------------------------------------------------------------

deck = make_deck("d1")
ok, bad, result = outcome(deck, change("add", "lightning bolt"), change("add", "Blood Artist"))
check("legal additions are accepted, under the card's own spelling", ok == ["Lightning Bolt", "Blood Artist"] and not bad, str(result))
check("an accepted proposal carries the reason and the card's text, for the model to describe it", result["accepted"][0]["why"] == "It fits." and result["accepted"][0]["oracle_text"] == "Text of Lightning Bolt")
ok, bad, _ = outcome(deck, change("add", "Sol Ring"), change("add", "Mana Crypt"), change("add", "Llanowar Elves"), change("add", "Nonesuch Card"))
check("a card already in the deck, a banned one, one outside the colors and an unknown one are each rejected, with why",
      not ok and "already in the deck" in bad["Sol Ring"] and "banned" in bad["Mana Crypt"] and "color identity" in bad["Llanowar Elves"] and "Nonesuch Card" in bad, str(bad))
ok, bad, _ = outcome(deck, change("add", "Mountain"))
check("a basic land can be proposed even when the deck has one", ok == ["Mountain"] and not bad)
ok, bad, _ = outcome(deck, change("add", "Blood Artist"), change("add", "blood artist"))
check("the same card proposed twice is accepted once", ok == ["Blood Artist"] and "already in the deck" in bad["blood artist"], str((ok, bad)))
ok, bad, _ = outcome(deck, change("remove", "Sol Ring"), change("remove", "Cultivate"))
check("a removal is accepted for a card in the deck and rejected for one that isn't", ok == ["Sol Ring"] and "not in the deck" in bad["Cultivate"])
result = T.suggest_changes(deck, [{"action": "swap", "name": "Sol Ring", "why": "x"}, {"action": "add", "name": "", "why": "x"}, "nonsense"])
check("a change with no known action or no name is rejected, whatever it looks like", not result["accepted"] and len(result["rejected"]) == 3, str(result))
check("changes that aren't a list are an error, not a crash", "error" in T.suggest_changes(deck, "add Sol Ring") and "error" in T.suggest_changes(deck, None))

# --- a full deck ------------------------------------------------------------------------------------------

full = make_deck("d2", cards=[f"Filler {i}" for i in range(99)])
ok, bad, _ = outcome(full, change("add", "Blood Artist"))
check("an addition to a full deck is rejected", not ok and "99 cards" in bad["Blood Artist"], str(bad))
ok, bad, _ = outcome(full, change("add", "Blood Artist"), change("remove", "Filler 3"))
check("...but a swap goes through, whichever is listed first", ok == ["Blood Artist", "Filler 3"] and not bad, str((ok, bad)))
almost = make_deck("d3", cards=[f"Filler {i}" for i in range(98)])
ok, bad, _ = outcome(almost, change("add", "Blood Artist"), change("add", "Lightning Bolt"))
check("two additions can't both take the last slot", ok == ["Blood Artist"] and "99 cards" in bad["Lightning Bolt"], str((ok, bad)))

# --- the commander ----------------------------------------------------------------------------------------------

ok, bad, _ = outcome(deck, change("commander", "Omnath, Locus of Rage"))
check("a legal commander is accepted", ok == ["Omnath, Locus of Rage"] and not bad)
ok, bad, _ = outcome(deck, change("commander", "Sol Ring"), change("commander", "Prosper, Tome-Bound"), change("commander", "Mana Crypt"))
check("a card that can't lead, the commander already in place and a banned card are each rejected",
      not ok and "can't be a commander" in bad["Sol Ring"] and "already the commander" in bad["Prosper, Tome-Bound"] and "banned" in bad["Mana Crypt"], str(bad))
ok, bad, _ = outcome(deck, change("add", "Cultivate"), change("commander", "Omnath, Locus of Rage"))
check("additions are checked against the commander proposed in the same call", ok == ["Cultivate", "Omnath, Locus of Rage"] and not bad, str((ok, bad)))

# --- limits and side effects --------------------------------------------------------------------------------------

many = [change("add", "Blood Artist")] * (T.MAX_SUGGESTIONS + 5)
result = T.suggest_changes(deck, many)
check("a longer list is cut at the limit, and the result says so", len(result["accepted"]) + len(result["rejected"]) == T.MAX_SUGGESTIONS and "5" in result["note"], str(result.get("note")))
before = json.dumps(D.load_deck("d1").__dict__, sort_keys=True, default=str)
T.suggest_changes(deck, [change("add", "Blood Artist"), change("remove", "Sol Ring"), change("commander", "Omnath, Locus of Rage")])
check("proposing changes nothing, in memory or on disk", deck.cards == ["Sol Ring", "Mountain"] and deck.commander == "Prosper, Tome-Bound" and json.dumps(D.load_deck("d1").__dict__, sort_keys=True, default=str) == before)

# --- a whole turn, through the loop and the endpoint ---------------------------------------------------------------

script: list = []


def respond(**kw):
    kw_messages = kw["messages"]
    sent.append(kw_messages)
    return script.pop(0)


sent: list = []
T.client = NS(messages=NS(create=respond))
proposal = {"changes": [change("add", "Blood Artist", "Drains whenever something dies."), change("add", "Mana Crypt")]}
script[:] = [
    NS(stop_reason="tool_use", content=[NS(type="text", text="Let me check."), NS(type="tool_use", id="t1", name="suggest_changes", input=proposal)]),
    NS(stop_reason="end_turn", content=[NS(type="text", text="I suggest Blood Artist. Mana Crypt is banned.")]),
]
chat = make_deck("d4")
text, messages = T.run_conversation(chat, [], "What should I add?")
tool_use = next(b for m in messages if m["role"] == "assistant" for b in m["content"] if b["type"] == "tool_use")
tool_result = next(b for m in messages if m["role"] == "user" and isinstance(m["content"], list) for b in m["content"] if b["type"] == "tool_result")
answer = json.loads(tool_result["content"])
check("a turn that proposes changes runs to a reply", text == "I suggest Blood Artist. Mana Crypt is banned." and tool_use["name"] == "suggest_changes")
check("the stored tool result says what was accepted and what was not, for the page to show", tool_result["tool_use_id"] == tool_use["id"] and [a["name"] for a in answer["accepted"]] == ["Blood Artist"] and [r["name"] for r in answer["rejected"]] == ["Mana Crypt"], str(answer))
check("...and the deck itself is untouched", chat.cards == ["Sol Ring", "Mountain"] and D.load_deck("d4").cards == ["Sol Ring", "Mountain"])
older = [
    {"role": "user", "content": "q1"},
    {"role": "assistant", "content": [{"type": "text", "text": "Try this."}, {"type": "tool_use", "id": "s1", "name": "suggest_changes", "input": proposal}]},
    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "s1", "content": json.dumps(answer)}]},
    {"role": "assistant", "content": [{"type": "text", "text": "Done."}]},
    {"role": "user", "content": "q2"},
]
shown = T.compact_history(older)
check("earlier turns show the model what it said, not the proposal calls, and the history stays valid", all(b.get("type") == "text" for m in shown if isinstance(m["content"], list) for b in m["content"]) and shown[-1] == older[-1], str(shown))

# These tests aren't about the login (see test_auth.py), so they run open, whatever password .env sets.
os.environ.pop("MTG_DECK_DOCTOR_PASSWORD", None)
os.environ["MTG_DECK_DOCTOR_AUTH"] = "off"
c = TestClient(api.app, raise_server_exceptions=False)
make_deck("d5")
script[:] = [
    NS(stop_reason="tool_use", content=[NS(type="tool_use", id="t9", name="suggest_changes", input={"changes": [change("remove", "Sol Ring", "Too pricey.")]})]),
    NS(stop_reason="end_turn", content=[NS(type="text", text="Consider cutting Sol Ring.")]),
]
r = c.post("/decks/d5/chat", json={"message": "cuts?"})
check("the chat endpoint returns the reply and leaves the deck as it was", r.status_code == 200 and r.json()["reply"] == "Consider cutting Sol Ring." and r.json()["deck"]["cards"] == ["Sol Ring", "Mountain"], r.text[:200])
check("...with the proposal in the saved conversation", any(b.get("name") == "suggest_changes" for m in r.json()["deck"]["messages"] if isinstance(m["content"], list) for b in m["content"]))

# --- a turn cut off in the middle of a tool call is never saved ---------------------------

cut_off = [{"role": "user", "content": "q"}, {"role": "assistant", "content": [{"type": "text", "text": "Looking."}, {"type": "tool_use", "id": "t1", "name": "lookup_card", "input": {}}]}]
finished = [{"role": "user", "content": "q"}, {"role": "assistant", "content": [{"type": "text", "text": "Done."}]}]
check("a last turn whose tool calls never got results is dropped from a saved history; a finished one stays", T._without_dangling_tool_use(cut_off) == cut_off[:1] and T._without_dangling_tool_use(finished) == finished and T._without_dangling_tool_use([]) == [])
sent = []
answer = {"stop": "max_tokens", "content": [NS(type="tool_use", id="t2", name="lookup_card", input={})]}
T.client = NS(messages=NS(create=lambda **kw: (sent.append(kw["messages"]), NS(stop_reason=answer["stop"], content=answer["content"]))[1]))
try:
    T.run_conversation(D.Deck(id="chat1"), finished, "next")
    raised = False
except T.ConversationCutOff:
    raised = True
check("a reply cut off at the token limit in the middle of a tool call raises instead of being returned", raised)
answer.update(stop="end_turn", content=[NS(type="text", text="Here you go.")])
text, saved = T.run_conversation(D.Deck(id="chat2"), cut_off, "next")
check("a history left with a dangling tool call is repaired before it is sent, and the chat goes on", text == "Here you go." and all(m["role"] != "assistant" or not any(b.get("type") == "tool_use" for b in m["content"]) for m in sent[-1]), str([m["role"] for m in sent[-1]]))
check("...and the chat endpoint answers a cut-off turn with a 502 and a reason, saving nothing", (lambda r: r.status_code == 502 and "ran out of room" in r.json()["detail"])((answer.update(stop="max_tokens", content=[NS(type="tool_use", id="t3", name="lookup_card", input={})]), D.save_deck(D.Deck(id="chat3")), c.post("/decks/chat3/chat", json={"message": "hi"}))[2]))

print(f"\n{sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
