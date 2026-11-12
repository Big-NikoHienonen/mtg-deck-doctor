"""Tests for a deck's public page: anyone can read a deck's list at its address, and only the list, with
no way to change the deck or use the Doctor on it. The card routes answer only for that deck's cards.
No network and no model. Run with

    uv run python tests/test_public_decks.py
"""

import json
import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

import mtg_deck_doctor.deck as D
from mtg_deck_doctor import api

D.DECKS_DIR = Path(tempfile.mkdtemp()) / "decks"
results: list[bool] = []


def check(name: str, ok: object, detail: str = "") -> None:
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


# These tests aren't about the login (see test_auth.py), so they run open, whatever password .env sets.
os.environ.pop("MTG_DECK_DOCTOR_PASSWORD", None)
os.environ["MTG_DECK_DOCTOR_AUTH"] = "off"
c = TestClient(api.app, raise_server_exceptions=False)

SECRET_CHAT = "the-owner's-private-question"
deck = D.Deck(
    id="aaaa1111",
    name="Prosper treasure",
    commander="Prosper, Tome-Bound",
    commander_color_identity=["B", "R"],
    cards=["Sol Ring", "Mountain"],
    keep=["Sol Ring"],
    messages=[{"role": "user", "content": SECRET_CHAT}],
)
D.save_deck(deck)

# --- what the page shows ------------------------------------------------------------------------------

view = c.get("/public/decks/aaaa1111")
body = view.json()
check("a deck's address opens the list: name, commander, colors, cards", view.status_code == 200 and body["name"] == "Prosper treasure" and body["commander"] == "Prosper, Tome-Bound" and body["commander_color_identity"] == ["B", "R"] and body["cards"] == ["Sol Ring", "Mountain"], str(body))
check("...and only those, with a date", set(body) == {"name", "commander", "commander_color_identity", "cards", "updated_at"}, str(sorted(body)))
check("...so not its conversation, its keep list, or its version", SECRET_CHAT not in view.text and "keep" not in body and "version" not in body and "messages" not in body)
version = D.load_deck("aaaa1111").version
updated = D.load_deck("aaaa1111").updated_at
c.get("/public/decks/aaaa1111")
check("looking at a deck changes nothing", D.load_deck("aaaa1111").version == version and D.load_deck("aaaa1111").updated_at == updated)
live = D.load_deck("aaaa1111")
live.cards.append("Blood Artist")
D.save_deck(live)
check("the page follows the deck: a card added later shows", "Blood Artist" in c.get("/public/decks/aaaa1111").json()["cards"])

bare = D.create_deck()
res = c.get(f"/public/decks/{bare.id}")
check("a deck with no name or commander opens too", res.status_code == 200 and res.json()["name"] is None and res.json()["commander"] is None and res.json()["cards"] == [])

# --- what a stranger can't do -----------------------------------------------------------------------------------

check("an unknown address is a 404", c.get("/public/decks/deadbeef").status_code == 404)
bad = ["x", "abc", "AAAA1111", "a" * 33, "aaaa 1111", "..", "aaaa1111.json", "%2e%2e%2f", "ünïcödé!"]
check("anything that can't be a deck's id is a 404 too", all(c.get(f"/public/decks/{b}").status_code == 404 for b in bad), str([b for b in bad if c.get(f"/public/decks/{b}").status_code != 404]))
check("the page takes no edits: only GET", all(c.request(m, "/public/decks/aaaa1111").status_code == 405 for m in ["POST", "PUT", "PATCH", "DELETE"]))
check("the deck is as it was after all of that", D.load_deck("aaaa1111").cards == ["Sol Ring", "Mountain", "Blood Artist"] and D.load_deck("aaaa1111").messages[0]["content"] == SECRET_CHAT)
c.delete("/decks/" + bare.id)

# --- an old file ----------------------------------------------------------------------------------------------------

old = json.loads((D.DECKS_DIR / "aaaa1111.json").read_text()) | {"id": "bbbb2222", "share_token": "left-over-from-share-links"}
(D.DECKS_DIR / "bbbb2222.json").write_text(json.dumps(old))
loaded = D.load_deck("bbbb2222")
check("a deck saved with the retired share_token still opens", loaded is not None and loaded.cards == ["Sol Ring", "Mountain", "Blood Artist"])
check("...and is in the list", any(d.id == "bbbb2222" for d in D.list_decks()) and c.get("/decks").status_code == 200)
D.rename_deck(loaded, "Renamed")
check("...and its next save drops the key", "share_token" not in json.loads((D.DECKS_DIR / "bbbb2222.json").read_text()))
check("a copy of a deck is as public as any other", c.get(f"/public/decks/{c.post('/decks/aaaa1111/duplicate').json()['id']}").status_code == 200)

# --- card details, for the cards in the deck only ---------------------------------------------------------------------

asked: list[list[str]] = []
real = (api.get_card_info_batch, api.peek_card_info, api.get_rulings)
api.get_card_info_batch = lambda names, refresh=False: asked.append(list(names)) or {"info": {n: {"id": f"id-{n}"} for n in names}, "not_found": [], "failed": []}
api.peek_card_info = lambda name: {"id": f"id-{name}"} if name in ("Sol Ring", "Mountain", "Blood Artist", "Prosper, Tome-Bound", "Counterspell") else None
api.get_rulings = lambda card_id: [{"comment": f"ruling for {card_id}"}]

res = c.post("/public/decks/aaaa1111/cards", json={"names": ["Sol Ring", "Counterspell", "Prosper, Tome-Bound"], "refresh": True})
check("a stranger gets card details for the cards in the deck, the commander included", res.status_code == 200 and sorted(res.json()["info"]) == ["Prosper, Tome-Bound", "Sol Ring"], str(res.json()))
check("...and nothing is looked up for a card that isn't in it, or forced to refresh", asked == [["Sol Ring", "Prosper, Tome-Bound"]], str(asked))
check("card details for a deck that doesn't exist are a 404", c.post("/public/decks/deadbeef/cards", json={"names": ["Sol Ring"]}).status_code == 404)

res = c.get("/public/decks/aaaa1111/rulings", params={"id": "id-Sol Ring"})
check("a stranger gets rulings for a card in the deck", res.status_code == 200 and res.json() == {"rulings": [{"comment": "ruling for id-Sol Ring"}]}, str(res.json()))
check("...but not for one that isn't", c.get("/public/decks/aaaa1111/rulings", params={"id": "id-Counterspell"}).status_code == 404)
check("...nor for a deck that doesn't exist", c.get("/public/decks/deadbeef/rulings", params={"id": "id-Sol Ring"}).status_code == 404)
api.get_card_info_batch, api.peek_card_info, api.get_rulings = real

# --- deleting ----------------------------------------------------------------------------------------------------------

c.delete("/decks/aaaa1111")
check("deleting a deck takes its page with it", c.get("/public/decks/aaaa1111").status_code == 404)

print(f"\n{sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
