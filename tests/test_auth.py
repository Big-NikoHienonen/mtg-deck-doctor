"""Tests for signing in: with an account, every route but the login routes and the public deck routes
refuses a browser that hasn't signed in; the cookie can't be forged, and ends with the password or at
the user's request; wrong passwords are throttled; every deck belongs to one user and no one else can
see or change it; and a stranger can read a deck's list and nothing else. No network and no model. Run with

    uv run python tests/test_auth.py
"""

import json
import os
import stat
import tempfile
from pathlib import Path

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import mtg_deck_doctor.deck as D
import mtg_deck_doctor.users as users
from mtg_deck_doctor import api, auth

tmp = Path(tempfile.mkdtemp())
D.DECKS_DIR = tmp / "decks"
auth.SECRET_PATH = tmp / "session_secret"
users.SCRYPT_N = 2**12  # Cheaper than the real cost, so the tests are quick. test_users.py checks the real one.
results: list[bool] = []


def check(name: str, ok: object, detail: str = "") -> None:
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def fresh(*accounts: tuple[str, str], open_mode: bool = False) -> TestClient:
    """A new browser against the app, with exactly these accounts and settings."""
    users.USERS_DIR = Path(tempfile.mkdtemp()) / "users"
    os.environ.pop(auth.AUTH_ENV, None)
    if open_mode:
        os.environ[auth.AUTH_ENV] = "off"
    for email, password in accounts:
        users.create_user(email, password)
    auth.throttle = auth.LoginThrottle()
    return TestClient(api.app, raise_server_exceptions=False)


def sign_in(email: str, password: str) -> TestClient:
    browser = TestClient(api.app, raise_server_exceptions=False)
    res = browser.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return browser


OWNER = ("owner@example.com", "correct horse battery")
OTHER = ("other@example.com", "another long password")

# --- no account: closed -----------------------------------------------------------------------------

c = fresh()
res = c.get("/decks")
check("with no account and no opt-out the app is closed, and says how to open it", res.status_code == 503 and "create-user" in res.json()["detail"], res.text)
status = c.get("/auth/status").json()
check("...and says so", status == {"required": True, "configured": False, "signed_in": False, "email": None}, str(status))
check("...login can't succeed", c.post("/auth/login", json={"email": OWNER[0], "password": OWNER[1]}).status_code == 503)
check("...a public deck page still answers (404: there is no such deck)", c.get("/public/decks/deadbeef").status_code == 404)

# --- asked to run open ------------------------------------------------------------------------------

c = fresh(open_mode=True)
check("MTG_DECK_DOCTOR_AUTH=off with no account runs open", c.get("/decks").status_code == 200)
check("...and tells the page there's nothing to sign in to", c.get("/auth/status").json() == {"required": False, "configured": True, "signed_in": True, "email": None})
check("...login does nothing", c.post("/auth/login", json={"email": "x@example.com", "password": "whatever"}).json() == {"ok": True, "email": None})
c = fresh(OWNER, open_mode=True)
check("an account wins over running open, so a stray setting can't leave a server open", c.get("/decks").status_code == 401)

# --- an account -------------------------------------------------------------------------------------

c = fresh(OWNER)
check("without the cookie a route is refused", c.get("/decks").status_code == 401)
check("...status says to sign in", c.get("/auth/status").json() == {"required": True, "configured": True, "signed_in": False, "email": None})

public_names = sorted(r.endpoint.__name__ for r in api.app.routes if isinstance(r, APIRoute) and getattr(r.endpoint, "public", False))
check(
    "only the login and public deck routes are open",
    public_names
    == sorted(["auth_status_endpoint", "login_endpoint", "logout_endpoint", "get_public_deck_endpoint", "get_public_card_info_endpoint", "get_public_rulings_endpoint"]),
    str(public_names),
)

refused: list[str] = []
for route in api.app.routes:
    if not isinstance(route, APIRoute) or getattr(route.endpoint, "public", False):
        continue
    path = route.path.replace("{deck_id}", "aaaa1111")
    for method in route.methods:
        res = c.request(method, path)
        if res.status_code != 401:
            refused.append(f"{method} {route.path} -> {res.status_code}")
check("every other route refuses a browser that hasn't signed in", not refused, "; ".join(refused))

wrong = c.post("/auth/login", json={"email": OWNER[0], "password": "nope nope nope"})
unknown = c.post("/auth/login", json={"email": "nobody@example.com", "password": OWNER[1]})
check("a wrong password is refused and sets no cookie", wrong.status_code == 401 and auth.COOKIE not in wrong.cookies)
check("an email with no account gets the same answer, so nothing says which was wrong", unknown.status_code == 401 and unknown.json() == wrong.json() and wrong.json()["detail"] == "Incorrect email or password.")

hashes: list[str] = []
real_verify = users.verify_password
users.verify_password = lambda password, stored: hashes.append(stored) or real_verify(password, stored)
c.post("/auth/login", json={"email": "nobody@example.com", "password": "whatever it is"})
users.verify_password = real_verify
check("...and it takes as long: the password is checked against a dummy hash", hashes == [users.dummy_hash()])

check("an email or password that is too long is rejected", c.post("/auth/login", json={"email": "a" * 300, "password": "x"}).status_code == 422 and c.post("/auth/login", json={"email": OWNER[0], "password": "x" * 201}).status_code == 422)
check("both fields are needed", c.post("/auth/login", json={"password": OWNER[1]}).status_code == 422 and c.post("/auth/login", json={"email": OWNER[0]}).status_code == 422)

ok = c.post("/auth/login", json={"email": "  OWNER@Example.com ", "password": OWNER[1]})
cookie = ok.headers.get("set-cookie", "")
check("the right email and password sign in, whatever the capitals", ok.status_code == 200 and ok.json() == {"ok": True, "email": OWNER[0]} and auth.COOKIE in ok.cookies)
check("...with a cookie JavaScript can't read, and that other sites don't send", "httponly" in cookie.lower() and "samesite=lax" in cookie.lower(), cookie)
check("...not marked secure over plain http", "secure" not in cookie.lower())
check("...but secure over https", "secure" in TestClient(api.app, base_url="https://testserver").post("/auth/login", json={"email": OWNER[0], "password": OWNER[1]}).headers.get("set-cookie", "").lower())
check("once signed in the routes work, and status says who", c.get("/decks").status_code == 200 and c.get("/auth/status").json() == {"required": True, "configured": True, "signed_in": True, "email": OWNER[0]})
check("the sign-in is noted on the account", users.find_user(OWNER[0]).last_login_at is not None)
mode_file = stat.S_IMODE(auth.SECRET_PATH.stat().st_mode)
check("the session secret is readable by its owner only", mode_file == 0o600, oct(mode_file))
secret_before = auth.SECRET_PATH.read_text()

# --- cookies that must not work ---------------------------------------------------------------------

owner = users.find_user(OWNER[0])
value = c.cookies.get(auth.COOKIE)
user_id, version, expires, signature = value.split(".")


def refused_with(cookie_value: str) -> bool:
    other = TestClient(api.app, raise_server_exceptions=False)
    return other.get("/decks", headers={"Cookie": f"{auth.COOKIE}={cookie_value}"}).status_code == 401


check("a cookie with the wrong signature is refused", refused_with(f"{user_id}.{version}.{expires}.{'0' * 64}"))
check("...so is one with its expiry pushed out", refused_with(f"{user_id}.{version}.{int(expires) + 10_000_000}.{signature}"))
check("...so is one with its session version raised", refused_with(f"{user_id}.{int(version) + 1}.{expires}.{signature}"))
check("...so is one aimed at another user's id", refused_with(f"{'0' * 16}.{version}.{expires}.{signature}"))
check("...so is junk", all(refused_with(v) for v in ["", "x", ".", "a.b.c.d", f"{user_id}.{version}.{expires}.", f"{user_id}.x.{expires}.{signature}", f"{user_id}.{version}.-1.{signature}", f"{value}.extra"]))
check("an expired cookie is refused", auth.session_user(auth.make_session(owner, now=0)) is None)
check("...and one still in date is accepted", auth.session_user(auth.make_session(owner)) is not None)

users.set_password(owner, "a brand new password")
check("a new password signs the old cookie out", c.get("/decks").status_code == 401)
check("...and the old password no longer signs in", TestClient(api.app).post("/auth/login", json={"email": OWNER[0], "password": OWNER[1]}).status_code == 401)
c = sign_in(OWNER[0], "a brand new password")
check("...while the new one does", c.get("/decks").status_code == 200)
users.revoke_sessions(users.find_user(OWNER[0]))
check("revoking sessions signs a cookie out without a new password", c.get("/decks").status_code == 401 and sign_in(OWNER[0], "a brand new password").get("/decks").status_code == 200)
fresh(OWNER, OTHER)
c = sign_in(*OWNER)
(users.USERS_DIR / f"{users.find_user(OWNER[0]).id}.json").unlink()
check("a cookie for an account that was removed is refused", c.get("/decks").status_code == 401)
fresh(OWNER)
c = sign_in(*OWNER)
(users.USERS_DIR / f"{users.find_user(OWNER[0]).id}.json").unlink()
check("...and with no account left the app is closed, not open", c.get("/decks").status_code == 503)
check("the session secret was kept, not replaced", auth.SECRET_PATH.read_text() == secret_before)

c = fresh(OWNER)
c = sign_in(*OWNER)
c.post("/auth/logout")
check("signing out ends the session in that browser", c.get("/decks").status_code == 401)

# --- throttle ---------------------------------------------------------------------------------------

c = fresh(OWNER)
codes = [c.post("/auth/login", json={"email": OWNER[0], "password": f"guess number {i}"}).status_code for i in range(auth.MAX_FAILURES)]
check("wrong passwords answer 401 until the limit", codes == [401] * auth.MAX_FAILURES, str(codes))
locked = c.post("/auth/login", json={"email": OWNER[0], "password": "guess"})
check("then the client is turned away with a wait time", locked.status_code == 429 and int(locked.headers["retry-after"]) > 0)
check("...even with the right password", c.post("/auth/login", json={"email": OWNER[0], "password": OWNER[1]}).status_code == 429)
check("...and routes stay closed", c.get("/decks").status_code == 401)

t = auth.LoginThrottle()
for _ in range(auth.MAX_FAILURES):
    t.record_failure("a", now=100.0)
check("a lockout is for that client only", t.retry_after("a", now=101.0) > 0 and t.retry_after("b", now=101.0) == 0)
check("...and ends when the window has passed", t.retry_after("a", now=100.0 + auth.FAILURE_WINDOW_SECONDS + 1) == 0)
c = fresh(OWNER)
for i in range(auth.MAX_FAILURES - 1):
    c.post("/auth/login", json={"email": OWNER[0], "password": "nope nope nope"})
check("a right password under the limit still signs in", c.post("/auth/login", json={"email": OWNER[0], "password": OWNER[1]}).status_code == 200)
for i in range(auth.MAX_FAILURES - 1):
    c.post("/auth/login", json={"email": OWNER[0], "password": "nope nope nope"})
check("...and clears the count", c.post("/auth/login", json={"email": OWNER[0], "password": "nope nope nope"}).status_code == 401)

# --- whose deck it is -------------------------------------------------------------------------------

fresh(OWNER, OTHER)
a = sign_in(*OWNER)
b = sign_in(*OTHER)
visitor = TestClient(api.app, raise_server_exceptions=False)
a_id, b_id = users.find_user(OWNER[0]).id, users.find_user(OTHER[0]).id

mine = a.post("/decks", json={"name": "Mine"}).json()
theirs = b.post("/decks", json={"name": "Theirs"}).json()
check("a new deck belongs to whoever made it", mine["owner_id"] == a_id and theirs["owner_id"] == b_id)
check("each user's list is their own decks only", [d["id"] for d in a.get("/decks").json()] == [mine["id"]] and [d["id"] for d in b.get("/decks").json()] == [theirs["id"]])

routes = [
    ("GET", "", None),
    ("DELETE", "", None),
    ("POST", "/duplicate", None),
    ("POST", "/name", {"name": "Taken"}),
    ("POST", "/cards", {"name": "Sol Ring"}),
    ("DELETE", "/cards?name=Sol%20Ring", None),
    ("POST", "/keep", {"name": "Sol Ring"}),
    ("POST", "/printings", {"printings": {}}),
    ("POST", "/chat", {"message": "hi"}),
    ("POST", "/swap", {"remove": "Sol Ring", "add": "Mountain"}),
    ("GET", "/suggestions", None),
]
got = {f"{m} {p}": b.request(m, f"/decks/{mine['id']}{p}", json=body).status_code for m, p, body in routes}
check("another user's deck is a 404 on every route that takes a deck's id", set(got.values()) == {404}, str({k: v for k, v in got.items() if v != 404}))
foreign, missing = b.get(f"/decks/{mine['id']}"), b.get("/decks/deadbeef")
check("...the same as a deck that doesn't exist, so an id says nothing", foreign.status_code == missing.status_code == 404 and foreign.json()["detail"].replace(mine["id"], "X") == missing.json()["detail"].replace("deadbeef", "X"))
check("...and none of it changed the deck", D.load_deck(mine["id"]).name == "Mine" and D.load_deck(mine["id"]).cards == [] and D.load_deck(mine["id"]).owner_id == a_id)
check("the owner still has the whole deck", a.get(f"/decks/{mine['id']}").status_code == 200 and a.post(f"/decks/{mine['id']}/name", json={"name": "Renamed"}).status_code == 200)

copy = a.post(f"/decks/{mine['id']}/duplicate").json()
check("a copy belongs to whoever copied it", copy["owner_id"] == a_id and copy["id"] in [d["id"] for d in a.get("/decks").json()] and copy["id"] not in [d["id"] for d in b.get("/decks").json()])
check("deleting your own deck works, and only yours", b.delete(f"/decks/{copy['id']}").status_code == 404 and a.delete(f"/decks/{copy['id']}").status_code == 200)

check("a visitor reads either deck's list at its address", visitor.get(f"/public/decks/{mine['id']}").status_code == 200 and b.get(f"/public/decks/{mine['id']}").status_code == 200)
check("...and still can't reach the owner's view of it", visitor.get(f"/decks/{mine['id']}").status_code == 401)

D.save_deck(D.Deck(id="eeee5555", name="From before accounts"))
check("a deck nobody owns is nobody's while accounts exist", "eeee5555" not in [d["id"] for d in a.get("/decks").json()] and a.get("/decks/eeee5555").status_code == 404)
check("...until an account takes it", D.claim_unowned_decks(a_id) == 1 and a.get("/decks/eeee5555").status_code == 200 and b.get("/decks/eeee5555").status_code == 404)

c = fresh(open_mode=True)
D.save_deck(D.Deck(id="ffff6666", name="Owned", owner_id=a_id))
D.save_deck(D.Deck(id="aaaa7777", name="Not owned"))
made = c.post("/decks", json={"name": "Made open"}).json()
check("running open, every deck is visible and a new one gets no owner", made["owner_id"] is None and {"ffff6666", "aaaa7777", made["id"]} <= {d["id"] for d in c.get("/decks").json()})

print(f"\n{sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
