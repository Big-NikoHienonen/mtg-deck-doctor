"""Tests for sharing a deck by link: the link opens a read-only view of the list and nothing else, it
can be turned off for good, and holding it gives no way to edit the deck or use the Doctor on it. No
network and no model. Run with

    uv run python tests/test_sharing.py
"""

import json
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

# --- turning it on ---------------------------------------------------------------------------------

check("a deck isn't shared until it is asked to be", c.get("/decks/aaaa1111").json()["share_token"] is None)
shared = c.post("/decks/aaaa1111/share")
token = shared.json()["share_token"]
check("sharing gives the deck a link token, long enough that it can't be guessed", shared.status_code == 200 and isinstance(token, str) and len(token) >= 16, str(token))
check("asking again keeps the same link", c.post("/decks/aaaa1111/share").json()["share_token"] == token)
check("the token is kept with the deck", D.load_deck("aaaa1111").share_token == token)
check("sharing a deck that doesn't exist is a 404", c.post("/decks/nope/share").status_code == 404 and c.delete("/decks/nope/share").status_code == 404)

# --- what the link opens ------------------------------------------------------------------------------

view = c.get(f"/shared/{token}")
body = view.json()
check("the link opens the list: name, commander, colors, cards", view.status_code == 200 and body["name"] == "Prosper treasure" and body["commander"] == "Prosper, Tome-Bound" and body["commander_color_identity"] == ["B", "R"] and body["cards"] == ["Sol Ring", "Mountain"], str(body))
check("...and only those, with a date", set(body) == {"name", "commander", "commander_color_identity", "cards", "updated_at"}, str(sorted(body)))
check("...so not the deck's id, its conversation, its keep list, or the link itself", "aaaa1111" not in view.text and SECRET_CHAT not in view.text and token not in view.text and "keep" not in body and "version" not in body)
version = D.load_deck("aaaa1111").version
c.get(f"/shared/{token}")
check("opening the link changes nothing", D.load_deck("aaaa1111").version == version)
live = D.load_deck("aaaa1111")
live.cards.append("Blood Artist")
D.save_deck(live)
check("the view follows the deck: a card added later shows", "Blood Artist" in c.get(f"/shared/{token}").json()["cards"])

# --- what the link can't do ---------------------------------------------------------------------------------

check("an unknown link is a 404", c.get("/shared/" + "x" * 22).status_code == 404)
check("anything that can't be a token is a 404 too", all(c.get(f"/shared/{t}").status_code == 404 for t in ["x", "a" * 70, "token with spaces!!", "..%2F..%2Fetc", "ünïcode-ünïcode-ünïcode"]))
check("the token isn't a deck id: it opens none of the deck's own endpoints", c.get(f"/decks/{token}").status_code == 404 and c.post(f"/decks/{token}/chat", json={"message": "hi"}).status_code == 404 and c.post(f"/decks/{token}/cards", json={"name": "Sol Ring"}).status_code == 404 and c.delete(f"/decks/{token}").status_code == 404)
check("the shared view takes no edits: only GET", all(c.request(m, f"/shared/{token}").status_code == 405 for m in ["POST", "PUT", "PATCH", "DELETE"]))
check("the deck is as it was after all of that", D.load_deck("aaaa1111").cards == ["Sol Ring", "Mountain", "Blood Artist"] and D.load_deck("aaaa1111").messages[0]["content"] == SECRET_CHAT)

# --- a copy, an old file, a broken file -------------------------------------------------------------------------------

copy = c.post("/decks/aaaa1111/duplicate").json()
check("a copy of a shared deck isn't shared", copy["share_token"] is None)
old = {k: v for k, v in json.loads((D.DECKS_DIR / "aaaa1111.json").read_text()).items() if k != "share_token"} | {"id": "bbbb2222"}
(D.DECKS_DIR / "bbbb2222.json").write_text(json.dumps(old))
check("a deck saved before sharing existed opens, and isn't shared", D.load_deck("bbbb2222").share_token is None)
(D.DECKS_DIR / "cccc3333.json").write_text("{ not json")
check("a file that can't be read doesn't break finding the others", c.get(f"/shared/{token}").status_code == 200)
(D.DECKS_DIR / "cccc3333.json").unlink()

# --- turning it off ---------------------------------------------------------------------------------------------------

off = c.delete("/decks/aaaa1111/share")
check("turning it off clears the token", off.status_code == 200 and off.json()["share_token"] is None and D.load_deck("aaaa1111").share_token is None)
check("...and the old link opens nothing", c.get(f"/shared/{token}").status_code == 404)
check("turning it off when it is off is fine", c.delete("/decks/aaaa1111/share").status_code == 200)
again = c.post("/decks/aaaa1111/share").json()["share_token"]
check("sharing again makes a new link, and the old one stays dead", again != token and c.get(f"/shared/{token}").status_code == 404 and c.get(f"/shared/{again}").status_code == 200)
c.delete("/decks/aaaa1111")
check("deleting the deck ends its link", c.get(f"/shared/{again}").status_code == 404)

print(f"\n{sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
