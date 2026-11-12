"""Tests for making a deck from the New deck modal: POST /decks with an optional name and
commander. The card lookup is stubbed, so no network. Run with

    uv run python tests/test_new_deck.py
"""

import os
import tempfile
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from fastapi.testclient import TestClient

import mtg_deck_doctor.deck as D
import mtg_deck_doctor.tool_loop as T
from mtg_deck_doctor import api

D.DECKS_DIR = Path(tempfile.mkdtemp()) / "decks"
results: list[bool] = []


def check(name: str, ok: object, detail: str = "") -> None:
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


CARDS = {
    "Atarka, World Render": {"legal_in_commander": True, "type_line": "Legendary Creature — Dragon Avatar", "color_identity": ["R", "G"], "oracle_text": "Flying, trample"},
    "Grist, the Hunger Tide": {"legal_in_commander": True, "type_line": "Legendary Planeswalker — Grist", "color_identity": ["B", "G"], "oracle_text": "Grist, the Hunger Tide can be your commander."},
    "Sol Ring": {"legal_in_commander": True, "type_line": "Artifact", "color_identity": [], "oracle_text": "{T}: Add {C}{C}."},
    "Banned Dragon": {"legal_in_commander": False, "type_line": "Legendary Creature — Dragon", "color_identity": ["R"], "oracle_text": ""},
}
looked_up: list[str] = []


def lookup(name: str) -> dict:
    looked_up.append(name)
    return CARDS[name] if name in CARDS else {"error": f"No card named {name!r} found."}


T.lookup_card = lookup
# These tests aren't about the login (see test_auth.py), so they run open, whatever password .env sets.
os.environ.pop("MTG_DECK_DOCTOR_PASSWORD", None)
os.environ["MTG_DECK_DOCTOR_AUTH"] = "off"
c = TestClient(api.app, raise_server_exceptions=False)
count = lambda: len(D.list_decks())

r = c.post("/decks")
check("with no body, a deck is made as before: empty, no name, no commander", r.status_code == 200 and r.json()["name"] is None and r.json()["commander"] is None and r.json()["cards"] == [] and count() == 1)

r = c.post("/decks", json={})
check("an empty body is the same", r.status_code == 200 and r.json()["commander"] is None and count() == 2)

r = c.post("/decks", json={"name": "  Dragons, but make it fast  "})
check("a name alone names the deck, trimmed", r.status_code == 200 and r.json()["name"] == "Dragons, but make it fast" and r.json()["commander"] is None and count() == 3 and looked_up == [], r.text[:150])

r = c.post("/decks", json={"commander": "Atarka, World Render"})
check("a commander alone sets it and its color identity, and leaves the deck unnamed", r.status_code == 200 and r.json()["commander"] == "Atarka, World Render" and r.json()["commander_color_identity"] == ["R", "G"] and r.json()["name"] is None and count() == 4, r.text[:200])

r = c.post("/decks", json={"name": "Hungry", "commander": "Grist, the Hunger Tide"})
saved = D.load_deck(r.json()["id"])
check("both together are set and saved, a commander that isn't a creature included when its text says it can lead", r.status_code == 200 and saved.name == "Hungry" and saved.commander == "Grist, the Hunger Tide" and saved.commander_color_identity == ["B", "G"] and count() == 5)

r = c.post("/decks", json={"name": "   ", "commander": "   "})
check("blank spaces count as nothing", r.status_code == 200 and r.json()["name"] is None and r.json()["commander"] is None and count() == 6)

before = count()
for label, body, words in [
    ("a card that can't lead", {"name": "Nope", "commander": "Sol Ring"}, "can't be a commander"),
    ("a banned one", {"commander": "Banned Dragon"}, "banned"),
    ("a card that doesn't exist", {"name": "Ghost", "commander": "Zzz Not A Card"}, "No card named"),
]:
    r = c.post("/decks", json=body)
    check(f"{label} is a 400 that says why, and no deck is left behind", r.status_code == 400 and words in r.json()["detail"] and count() == before, r.text[:160])

T.lookup_card = lambda name: (_ for _ in ()).throw(RuntimeError("lookup broke"))
r = c.post("/decks", json={"commander": "Atarka, World Render"})
check("even when the lookup itself fails, no deck is left behind", r.status_code == 500 and count() == before)
T.lookup_card = lookup

check("a name over 100 characters, or a commander over 200, is refused", c.post("/decks", json={"name": "x" * 101}).status_code == 422 and c.post("/decks", json={"commander": "x" * 201}).status_code == 422 and count() == before)
check("...and exactly 100 is fine", c.post("/decks", json={"name": "x" * 100}).status_code == 200 and count() == before + 1)

print(f"\n{sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
