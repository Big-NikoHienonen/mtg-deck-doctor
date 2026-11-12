"""Tests for the owner's login: with a password set, every route but the login routes and the public
deck routes refuses a browser that hasn't signed in; the cookie can't be forged, outlives neither its
expiry nor a password change; wrong passwords are throttled; and a stranger can read a deck's list and
nothing else. No network and no model. Run with

    uv run python tests/test_auth.py
"""

import os
import stat
import tempfile
from pathlib import Path

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import mtg_deck_doctor.deck as D
from mtg_deck_doctor import api, auth

tmp = Path(tempfile.mkdtemp())
D.DECKS_DIR = tmp / "decks"
auth.SECRET_PATH = tmp / "session_secret"
results: list[bool] = []


def check(name: str, ok: object, detail: str = "") -> None:
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def setup(password: str | None, open_mode: bool = False) -> TestClient:
    """A fresh browser against the app with the given settings."""
    os.environ.pop(auth.PASSWORD_ENV, None)
    os.environ.pop(auth.AUTH_ENV, None)
    if password is not None:
        os.environ[auth.PASSWORD_ENV] = password
    if open_mode:
        os.environ[auth.AUTH_ENV] = "off"
    auth.throttle = auth.LoginThrottle()
    return TestClient(api.app, raise_server_exceptions=False)


PASSWORD = "correct horse"

# --- not set up: closed -----------------------------------------------------------------------------

c = setup(None)
check("with no password and no opt-out the app is closed", c.get("/decks").status_code == 503 and "MTG_DECK_DOCTOR_PASSWORD" in c.get("/decks").json()["detail"])
status = c.get("/auth/status").json()
check("...and says so", status == {"required": True, "configured": False, "signed_in": False}, str(status))
check("...login can't succeed", c.post("/auth/login", json={"password": ""}).status_code == 503)
check("...a public deck page still answers (404: there is no such deck)", c.get("/public/decks/deadbeef").status_code == 404)

# --- asked to run open ------------------------------------------------------------------------------

c = setup(None, open_mode=True)
check("MTG_DECK_DOCTOR_AUTH=off runs open", c.get("/decks").status_code == 200)
check("...and tells the page there's nothing to sign in to", c.get("/auth/status").json() == {"required": False, "configured": True, "signed_in": True})
c = setup(PASSWORD, open_mode=True)
check("a password set wins over running open", c.get("/decks").status_code == 401)

# --- password set -----------------------------------------------------------------------------------

c = setup(PASSWORD)
check("without the cookie a route is refused", c.get("/decks").status_code == 401)
check("...status says to sign in", c.get("/auth/status").json() == {"required": True, "configured": True, "signed_in": False})

public_names = sorted(r.endpoint.__name__ for r in api.app.routes if isinstance(r, APIRoute) and getattr(r.endpoint, "public", False))
check(
    "only the login and public deck routes are open",
    public_names
    == sorted(
        [
            "auth_status_endpoint",
            "login_endpoint",
            "logout_endpoint",
            "get_public_deck_endpoint",
            "get_public_card_info_endpoint",
            "get_public_rulings_endpoint",
        ]
    ),
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

wrong = c.post("/auth/login", json={"password": "nope"})
check("a wrong password is refused and sets no cookie", wrong.status_code == 401 and auth.COOKIE not in wrong.cookies)
check("a password past 200 characters is rejected", c.post("/auth/login", json={"password": "x" * 201}).status_code == 422)

ok = c.post("/auth/login", json={"password": PASSWORD})
cookie = ok.headers.get("set-cookie", "")
check("the right password signs in", ok.status_code == 200 and auth.COOKIE in ok.cookies)
check("...with a cookie JavaScript can't read, and that other sites don't send", "httponly" in cookie.lower() and "samesite=lax" in cookie.lower(), cookie)
check("...not marked secure over plain http", "secure" not in cookie.lower())
check("...but secure over https", "secure" in TestClient(api.app, base_url="https://testserver").post("/auth/login", json={"password": PASSWORD}).headers.get("set-cookie", "").lower())
check("once signed in the routes work", c.get("/decks").status_code == 200 and c.get("/auth/status").json()["signed_in"] is True)

value = c.cookies.get(auth.COOKIE)
mode_file = stat.S_IMODE(auth.SECRET_PATH.stat().st_mode)
check("the session secret is readable by its owner only", mode_file == 0o600, oct(mode_file))
secret_before = auth.SECRET_PATH.read_text()

# --- cookies that must not work ---------------------------------------------------------------------

expires, _, signature = value.partition(".")


def refused_with(cookie_value: str) -> bool:
    other = TestClient(api.app, raise_server_exceptions=False)
    return other.get("/decks", headers={"Cookie": f"{auth.COOKIE}={cookie_value}"}).status_code == 401


check("a cookie with the wrong signature is refused", refused_with(f"{expires}.{'0' * 64}"))
check("...so is one with its expiry pushed out", refused_with(f"{int(expires) + 10_000_000}.{signature}"))
check("...so is junk", all(refused_with(v) for v in ["", "x", ".", "abc.def", f"{expires}.", f".{signature}", "-1." + signature]))
check("an expired cookie is refused", not auth.valid_session(auth.make_session(now=0)))
check("...and one still in date is accepted", auth.valid_session(auth.make_session()))

os.environ[auth.PASSWORD_ENV] = "another password"
check("changing the password signs everyone out", c.get("/decks").status_code == 401)
os.environ[auth.PASSWORD_ENV] = PASSWORD
check("...and going back to the old one doesn't need a new login", c.get("/decks").status_code == 200)
check("the session secret was kept, not replaced", auth.SECRET_PATH.read_text() == secret_before)

c.post("/auth/logout")
check("signing out ends the session", c.get("/decks").status_code == 401)

# --- throttle ---------------------------------------------------------------------------------------

c = setup(PASSWORD)
codes = [c.post("/auth/login", json={"password": f"guess {i}"}).status_code for i in range(auth.MAX_FAILURES)]
check("wrong passwords answer 401 until the limit", codes == [401] * auth.MAX_FAILURES, str(codes))
locked = c.post("/auth/login", json={"password": "guess"})
check("then the client is turned away with a wait time", locked.status_code == 429 and int(locked.headers["retry-after"]) > 0)
check("...even with the right password", c.post("/auth/login", json={"password": PASSWORD}).status_code == 429)
check("...and routes stay closed", c.get("/decks").status_code == 401)

t = auth.LoginThrottle()
for _ in range(auth.MAX_FAILURES):
    t.record_failure("a", now=100.0)
check("a lockout is for that client only", t.retry_after("a", now=101.0) > 0 and t.retry_after("b", now=101.0) == 0)
check("...and ends when the window has passed", t.retry_after("a", now=100.0 + auth.FAILURE_WINDOW_SECONDS + 1) == 0)
c = setup(PASSWORD)
for i in range(auth.MAX_FAILURES - 1):
    c.post("/auth/login", json={"password": "nope"})
check("a right password under the limit still signs in", c.post("/auth/login", json={"password": PASSWORD}).status_code == 200)
for i in range(auth.MAX_FAILURES - 1):
    c.post("/auth/login", json={"password": "nope"})
check("...and clears the count", c.post("/auth/login", json={"password": "nope"}).status_code == 401)

# --- public decks, signed out -----------------------------------------------------------------------

owner = setup(PASSWORD)
owner.post("/auth/login", json={"password": PASSWORD})
D.save_deck(D.Deck(id="aaaa1111", name="Prosper", commander="Prosper, Tome-Bound", commander_color_identity=["B", "R"], cards=["Sol Ring", "Mountain"], messages=[{"role": "user", "content": "private question"}]))
visitor = TestClient(api.app, raise_server_exceptions=False)

asked: list[list[str]] = []
real = (api.get_card_info_batch, api.peek_card_info, api.get_rulings)
api.get_card_info_batch = lambda names, refresh=False: asked.append(list(names)) or {"info": {n: {"id": f"id-{n}"} for n in names}, "not_found": [], "failed": []}
api.peek_card_info = lambda name: {"id": f"id-{name}"} if name in ("Sol Ring", "Mountain", "Prosper, Tome-Bound", "Counterspell") else None
api.get_rulings = lambda card_id: [{"comment": f"ruling for {card_id}"}]

res = visitor.get("/public/decks/aaaa1111")
check("a visitor with no cookie sees a deck's list", res.status_code == 200 and res.json()["cards"] == ["Sol Ring", "Mountain"])
check("...but not its conversation", "private question" not in res.text)
check("...and not the owner's view of the same deck", visitor.get("/decks/aaaa1111").status_code == 401)
check("...or anything they could change it with", visitor.post("/decks/aaaa1111/chat", json={"message": "hi"}).status_code == 401 and visitor.post("/decks/aaaa1111/cards", json={"name": "Sol Ring"}).status_code == 401 and visitor.delete("/decks/aaaa1111").status_code == 401)
check("...or the list of decks", visitor.get("/decks").status_code == 401)

res = visitor.post("/public/decks/aaaa1111/cards", json={"names": ["Sol Ring", "Counterspell", "Prosper, Tome-Bound"], "refresh": True})
check("a visitor gets card details for the cards in the deck, the commander included", res.status_code == 200 and sorted(res.json()["info"]) == ["Prosper, Tome-Bound", "Sol Ring"], str(res.json()))
check("...and nothing is looked up for a card that isn't in it", asked == [["Sol Ring", "Prosper, Tome-Bound"]], str(asked))
check("...with the owner's card route closed", visitor.post("/cards/batch", json={"names": ["Sol Ring"]}).status_code == 401)

res = visitor.get("/public/decks/aaaa1111/rulings", params={"id": "id-Sol Ring"})
check("a visitor gets rulings for a card in the deck", res.status_code == 200 and res.json() == {"rulings": [{"comment": "ruling for id-Sol Ring"}]}, str(res.json()))
check("...but not for one that isn't", visitor.get("/public/decks/aaaa1111/rulings", params={"id": "id-Counterspell"}).status_code == 404)
check("...and the owner's rulings route is closed", visitor.get("/cards/rulings", params={"id": "id-Sol Ring"}).status_code == 401)
check("the owner, signed in, gets both views", owner.get("/decks/aaaa1111").status_code == 200 and owner.get("/public/decks/aaaa1111").status_code == 200)
api.get_card_info_batch, api.peek_card_info, api.get_rulings = real

print(f"\n{sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
