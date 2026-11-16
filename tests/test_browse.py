"""Tests for public and private decks, the browse page's list, usernames, and the profanity check on deck
names. A deck is public unless its owner says otherwise; a private deck is the owner's alone and every
public route answers 404 for it; the browse list names a deck's builder by username and never shows an
email. No network and no model. Run with

    uv run python tests/test_browse.py
"""

import json
import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

import mtg_deck_doctor.deck as D
import mtg_deck_doctor.users as users
from mtg_deck_doctor import api, auth

tmp = Path(tempfile.mkdtemp())
D.DECKS_DIR = tmp / "decks"
auth.SECRET_PATH = tmp / "session_secret"
users.SCRYPT_N = 2**12
results: list[bool] = []

# No cache file, no network: every card is known by an id, and costs $1.50.
api.peek_card_info_many = lambda names: {n: {"id": f"id-{n}", "priceUsd": "1.50"} for n in names}


def check(name: str, ok: object, detail: str = "") -> None:
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def fresh(*accounts: tuple[str, str, str | None], open_mode: bool = False) -> TestClient:
    users.USERS_DIR = Path(tempfile.mkdtemp()) / "users"
    D.DECKS_DIR = Path(tempfile.mkdtemp()) / "decks"
    os.environ.pop(auth.AUTH_ENV, None)
    if open_mode:
        os.environ[auth.AUTH_ENV] = "off"
    for email, password, username in accounts:
        users.create_user(email, password, username)
    auth.throttle = auth.AttemptLimiter(auth.MAX_FAILURES, auth.FAILURE_WINDOW_SECONDS, overall=auth.MAX_FAILURES_OVERALL)
    auth.deck_misses = auth.AttemptLimiter(auth.MAX_DECK_MISSES, auth.FAILURE_WINDOW_SECONDS)
    auth.browse_limiter = auth.AttemptLimiter(auth.MAX_BROWSE_PER_MINUTE, 60)
    api._index = None
    return TestClient(api.app, raise_server_exceptions=False)


def sign_in(email: str, password: str) -> TestClient:
    browser = TestClient(api.app, raise_server_exceptions=False)
    res = browser.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return browser


def build(owner: users.User | None, deck_id: str, commander: str | None = "Atarka, World Render", **fields) -> D.Deck:
    deck = D.Deck(id=deck_id, commander=commander, commander_color_identity=["R", "G"], cards=["Sol Ring", "Forest"], owner_id=owner.id if owner else None, **fields)
    D.save_deck(deck)
    return deck


NIKO = ("niko@example.com", "correct horse battery", "Niko_D")
SAM = ("sam@example.com", "another long password", None)

# --- public by default ------------------------------------------------------------------------------

fresh(NIKO)
niko = sign_in(NIKO[0], NIKO[1])
made = niko.post("/decks", json={"name": "Mine"}).json()
check("a new deck is public unless its owner says otherwise", made["public"] is True)
check("...and can be made private when it is made", niko.post("/decks", json={"name": "Secret", "public": False}).json()["public"] is False)
check("...and a deck made with no body is public", niko.post("/decks").json()["public"] is True)
D.DECKS_DIR.mkdir(parents=True, exist_ok=True)
(D.DECKS_DIR / "aaaa0000.json").write_text(json.dumps({"id": "aaaa0000", "cards": [], "commander": "Atarka, World Render"}))
check("a deck file from before there was a choice reads as public", D.load_deck("aaaa0000").public is True)
check("a duplicate keeps its original's visibility", D.duplicate_deck(niko.post("/decks", json={"public": False}).json()["id"]).public is False)

# --- changing it ------------------------------------------------------------------------------------

deck_id = made["id"]
res = niko.post(f"/decks/{deck_id}/visibility", json={"public": False})
check("the owner can make a deck private", res.status_code == 200 and res.json()["public"] is False and D.load_deck(deck_id).public is False)
check("...and public again", niko.post(f"/decks/{deck_id}/visibility", json={"public": True}).json()["public"] is True)
check("only true or false will do", niko.post(f"/decks/{deck_id}/visibility", json={"public": "no"}).status_code == 422 and niko.post(f"/decks/{deck_id}/visibility", json={}).status_code == 422)
check("the deck keeps everything else", niko.get(f"/decks/{deck_id}").json()["name"] == "Mine")
check("without signing in it is refused", TestClient(api.app).post(f"/decks/{deck_id}/visibility", json={"public": False}).status_code == 401)

fresh(NIKO, SAM)
niko, sam = sign_in(NIKO[0], NIKO[1]), sign_in(SAM[0], SAM[1])
mine = niko.post("/decks", json={"name": "Mine"}).json()["id"]
check("someone else's deck can't be changed, and looks like no deck", sam.post(f"/decks/{mine}/visibility", json={"public": False}).status_code == 404 and D.load_deck(mine).public is True)

# --- what a private deck shows a stranger -----------------------------------------------------------

fresh(NIKO)
niko = sign_in(NIKO[0], NIKO[1])
owner = users.find_user(NIKO[0])
build(owner, "aaaa1111", name="Dragons")
build(owner, "bbbb2222", name="Hidden", public=False)
stranger = TestClient(api.app, raise_server_exceptions=False)
check("a stranger can open a public deck", stranger.get("/public/decks/aaaa1111").status_code == 200)
check("...but a private one looks like no deck at all", stranger.get("/public/decks/bbbb2222").status_code == 404 and stranger.get("/public/decks/bbbb2222").json() == stranger.get("/public/decks/cccc3333").json())
check("...also for its cards and rulings", stranger.post("/public/decks/bbbb2222/cards", json={"names": ["Sol Ring"]}).status_code == 404 and stranger.get("/public/decks/bbbb2222/rulings", params={"id": "x"}).status_code == 404)
users.create_user("sam@example.com", "another long password")
check("...even for someone signed in as someone else", sign_in("sam@example.com", "another long password").get("/public/decks/bbbb2222").status_code == 404)
check("the owner still sees a private deck in their own routes", niko.get("/decks/bbbb2222").status_code == 200 and "bbbb2222" in [d["id"] for d in niko.get("/decks").json()])
check("...and the hub says which decks are private", {d["id"]: d["public"] for d in niko.get("/hub").json()["decks"]} == {"aaaa1111": True, "bbbb2222": False})

# --- the browse list --------------------------------------------------------------------------------

listing = stranger.get("/public/decks")
body = listing.json()
check("anyone can browse, with no sign-in", listing.status_code == 200 and [d["id"] for d in body["decks"]] == ["aaaa1111"] and body["total"] == 1)
tile = body["decks"][0]
check("a tile has what the page shows", set(tile) == {"id", "title", "commander", "commander_id", "color_identity", "card_count", "price_usd", "owner_name", "updated_at"}, str(sorted(tile)))
check("...the commander's art id, the price of the list, and the count", tile["commander_id"] == "id-Atarka, World Render" and tile["price_usd"] == 4.5 and tile["card_count"] == 3)
check("...and the builder by username", tile["owner_name"] == "Niko_D")
text = listing.text
check("nothing in it gives away an email, an account id, or who owns what", "niko@example.com" not in text and owner.id not in text and "owner_id" not in text)

build(owner, "dddd4444", commander=None, name="No commander yet")
check("a deck with no commander isn't a build yet, so it isn't listed", [d["id"] for d in stranger.get("/public/decks").json()["decks"]] == ["aaaa1111"])

D.save_deck(D.Deck(id="eeee5555", commander="Grist, the Hunger Tide", name="Mantis", owner_id=owner.id, updated_at="2020-01-01T00:00:00+00:00"))
api._index = None
ids = lambda **q: [d["id"] for d in stranger.get("/public/decks", params=q).json()["decks"]]
check("newest first", ids() == ["aaaa1111", "eeee5555"] or ids() == ["eeee5555", "aaaa1111"])
D.save_deck(D.load_deck("eeee5555"))  # saving stamps it with the time now, which makes it the newest
check("...the deck most recently saved leads", ids()[0] == "eeee5555")
check("by name, when asked", ids(sort="name") == ["aaaa1111", "eeee5555"])
check("search looks at the title", ids(q="mantis") == ["eeee5555"] and ids(q="DRAGON") == ["aaaa1111"])
check("...at the commander", ids(q="grist") == ["eeee5555"] and ids(q="atarka") == ["aaaa1111"])
check("...and at the builder", set(ids(q="niko_d")) == {"aaaa1111", "eeee5555"})
check("...and finds nothing for nothing", ids(q="zzzzzz") == [] and stranger.get("/public/decks", params={"q": "zzzzzz"}).json()["total"] == 0)
check("a page is cut out of the matches, and the total is of all of them", stranger.get("/public/decks", params={"limit": 1}).json()["total"] == 2 and len(ids(limit=1)) == 1 and ids(limit=1, offset=1) != ids(limit=1, offset=0) and ids(offset=5) == [])
check("a page can't be too large, or start before the first", stranger.get("/public/decks", params={"limit": 61}).status_code == 422 and stranger.get("/public/decks", params={"limit": 0}).status_code == 422 and stranger.get("/public/decks", params={"offset": -1}).status_code == 422 and stranger.get("/public/decks", params={"sort": "price"}).status_code == 422)
check("a search can't be huge", stranger.get("/public/decks", params={"q": "x" * 101}).status_code == 422)

niko.post("/decks/aaaa1111/visibility", json={"public": False})
check("a deck made private leaves the list at once", ids() == ["eeee5555"])
niko.post("/decks/aaaa1111/visibility", json={"public": True})
check("...and comes back when made public", "aaaa1111" in ids())
niko.delete("/decks/eeee5555")
check("a deck that is deleted leaves it too", ids() == ["aaaa1111"])

auth.browse_limiter = auth.AttemptLimiter(5, 60)
codes = [stranger.get("/public/decks").status_code for _ in range(7)]
check("someone who asks for the list over and over is slowed", codes == [200] * 5 + [429] * 2, str(codes))
check("...with a wait time, and the rest of the site is unaffected", int(stranger.get("/public/decks").headers["retry-after"]) > 0 and stranger.get("/public/decks/aaaa1111").status_code == 200)

# --- who built it -----------------------------------------------------------------------------------

fresh(NIKO, SAM)
build(users.find_user(NIKO[0]), "aaaa1111", name="By Niko")
build(users.find_user(SAM[0]), "bbbb2222", name="By Sam")
build(None, "cccc3333", name="By nobody")
owners = {d["id"]: d["owner_name"] for d in TestClient(api.app).get("/public/decks").json()["decks"]}
check("a builder with a username is named, one without isn't, and a deck with no owner has none", owners == {"aaaa1111": "Niko_D", "bbbb2222": None, "cccc3333": None}, str(owners))
page = TestClient(api.app).get("/public/decks/aaaa1111").json()
check("a deck's page names its builder by username too, and carries no email or id", page["owner_name"] == "Niko_D" and "niko@example.com" not in json.dumps(page) and "owner_id" not in page)
sam = sign_in(SAM[0], SAM[1])
check("a signed-in user's own username is on their account", sam.get("/account").json() == {"email": SAM[0], "username": None})

# --- usernames --------------------------------------------------------------------------------------

check("a username is 3 to 24 letters, digits, hyphens and underscores", all(users.check_username(n) is None for n in ["abc", "Niko_D", "a-b_c", "x" * 24, "007", "Dragon99"]))
check("...nothing shorter, longer, or with anything else in it", all(users.check_username(n) is not None for n in ["ab", "x" * 25, "has space", "dot.dot", "name@host", "-lead", "_lead", "emoji😀", "ünicode", ""]))
check("a reserved name can't be taken", all(users.check_username(n) for n in ["admin", "Admin", "ROOT", "Moderator", "anonymous", "MtgDeckDoctor"]))
check("a profane one can't, in any disguise", all(users.check_username(n) for n in ["fuck", "xxfuckxx", "sh1thead", "n1gg3r", "f_u_c_k", "Cunt99"]))
check("...and a harmless one that looks near it can", all(users.check_username(n) is None for n in ["Cat_Waters", "Cockatrice", "Assassin", "Titan", "Scunthorpe"]))

fresh(NIKO, SAM)
niko, sam = sign_in(NIKO[0], NIKO[1]), sign_in(SAM[0], SAM[1])
check("a username can be set from the account page", sam.post("/account/username", json={"username": "SamTheMan"}).json() == {"username": "SamTheMan"} and users.find_user(SAM[0]).username == "SamTheMan")
check("...and shows in the sign-in status", sam.get("/auth/status").json()["username"] == "SamTheMan" and sam.get("/account").json()["username"] == "SamTheMan")
check("...and on the user's decks", (build(users.find_user(SAM[0]), "aaaa1111"), TestClient(api.app).get("/public/decks/aaaa1111").json()["owner_name"])[1] == "SamTheMan")
res = sam.post("/account/username", json={"username": "niko_d"})
check("someone else's username is taken, whatever the capitals", res.status_code == 400 and "taken" in res.json()["detail"] and users.find_user(SAM[0]).username == "SamTheMan")
check("a user may change the capitals of their own", sam.post("/account/username", json={"username": "samtheman"}).status_code == 200 and users.find_user(SAM[0]).username == "samtheman")
res = sam.post("/account/username", json={"username": "fuckface"})
check("a profane one is refused, without saying which word", res.status_code == 400 and res.json()["detail"] == "That username isn't allowed." and users.find_user(SAM[0]).username == "samtheman")
check("a bad shape is refused, and a huge one is too", sam.post("/account/username", json={"username": "no spaces"}).status_code == 400 and sam.post("/account/username", json={"username": "x" * 51}).status_code == 422)
check("signing in is needed to set one", TestClient(api.app).post("/account/username", json={"username": "someone"}).status_code == 401)
check("...and the login answer carries it", TestClient(api.app).post("/auth/login", json={"email": SAM[0], "password": SAM[1]}).json() == {"ok": True, "email": SAM[0], "username": "samtheman"})
check("an account can be made with a username", users.create_user("third@example.com", "a third long password", "Third_One").username == "Third_One")
try:
    users.create_user("fourth@example.com", "a fourth long password", "third_one")
    twice = False
except ValueError as err:
    twice = "taken" in str(err)
check("...and the same username can't be given twice, whatever the capitals", twice)
try:
    users.create_user("fifth@example.com", "a fifth long password", "shit_head")
    refused = False
except ValueError as err:
    refused = "allowed" in str(err)
check("...and a profane username is refused at creation", refused and users.find_user("fifth@example.com") is None)

c = fresh(open_mode=True)
check("with no sign-in there is no account to name", c.post("/account/username", json={"username": "someone"}).status_code == 400 and c.get("/account").json() == {"email": None, "username": None})

# --- deck names -------------------------------------------------------------------------------------

fresh(NIKO)
niko = sign_in(NIKO[0], NIKO[1])
before = len(D.list_decks())
res = niko.post("/decks", json={"name": "Fuck Everything"})
check("a deck can't be made with a profane name, and nothing is left behind", res.status_code == 400 and res.json()["detail"] == api.NAME_REFUSED and len(D.list_decks()) == before)
check("...in any disguise", all(niko.post("/decks", json={"name": n}).status_code == 400 for n in ["sh1t deck", "f u c k", "Nazi Tribal", "b!tch"]))
check("...but a card name or a pun is fine", all(niko.post("/decks", json={"name": n}).status_code == 200 for n in ["Cockatrice Tribal", "Assassin's Trophy", "Hell's Caretaker", "Damnation Nation"]))
deck = niko.post("/decks", json={"name": "Clean Name"}).json()
res = niko.post(f"/decks/{deck['id']}/name", json={"name": "Total Bullshit"})
check("a deck can't be renamed to a profane name, and keeps the one it had", res.status_code == 400 and D.load_deck(deck["id"]).name == "Clean Name")
check("...but can be renamed to a clean one", niko.post(f"/decks/{deck['id']}/name", json={"name": "Better Name"}).json()["name"] == "Better Name")
check("clearing the name is fine", niko.post(f"/decks/{deck['id']}/name", json={"name": ""}).status_code == 200)

D.save_deck(D.Deck(id="ffff6666", commander="Atarka, World Render", name="Piss Poor Dragons Tribal Fuck", owner_id=users.find_user(NIKO[0]).id))
api._index = None
anon = TestClient(api.app)
shown = {d["id"]: d["title"] for d in anon.get("/public/decks").json()["decks"]}
check("a name saved before the check, which would fail it now, isn't shown to strangers: the commander is", shown["ffff6666"] == "Atarka, World Render", str(shown))
check("...on the deck's own page either", anon.get("/public/decks/ffff6666").json()["name"] is None)
check("...though its owner still sees what they wrote", niko.get("/decks/ffff6666").json()["name"] == "Piss Poor Dragons Tribal Fuck")

D.save_deck(D.Deck(id="1111aaaa", commander="Atarka, World Render", owner_id=users.find_user(NIKO[0]).id))
users.set_username(users.find_user(NIKO[0]), "Niko_D")
u = users.find_user(NIKO[0])
u.username = "xxfuckxx"  # set by hand: a username saved before the check
users._write(u)
api._index = None
check("a username that would fail the check now isn't shown either", anon.get("/public/decks/1111aaaa").json()["owner_name"] is None and all(d["owner_name"] is None for d in anon.get("/public/decks").json()["decks"]))

print(f"\n{sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
