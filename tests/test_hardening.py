"""Tests for the guards around the app: the security headers, the request size limit, the limits on what
a route accepts, the limits on guessing (passwords and deck addresses), sign-out that ends a copied
cookie, forged cookies, and the file-name and id checks. No network and no model. Run with

    uv run python tests/test_hardening.py
"""

import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from starlette.requests import Request

import mtg_deck_doctor.deck as D
import mtg_deck_doctor.users as users
from mtg_deck_doctor import api, auth, cli, hardening, server
from mtg_deck_doctor.card_details import is_scryfall_id

results: list[bool] = []


def check(name: str, ok: object, detail: str = "") -> None:
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


tmp = Path(tempfile.mkdtemp())
dist = tmp / "dist"
(dist / "assets").mkdir(parents=True)
(dist / "index.html").write_text("<!doctype html><title>shell</title>")
(dist / "assets" / "app-abc123.js").write_text("console.log(1)")
server.DIST = dist
D.DECKS_DIR = tmp / "decks"
auth.SECRET_PATH = tmp / "session_secret"
users.SCRYPT_N = 2**12
users.USERS_DIR = tmp / "users"
os.environ.pop(auth.PROXY_ENV, None)


def reset_limits() -> None:
    auth.throttle = auth.AttemptLimiter(auth.MAX_FAILURES, auth.FAILURE_WINDOW_SECONDS, overall=auth.MAX_FAILURES_OVERALL)
    auth.deck_misses = auth.AttemptLimiter(auth.MAX_DECK_MISSES, auth.FAILURE_WINDOW_SECONDS)


def fresh(*accounts: tuple[str, str], open_mode: bool = False, through_server: bool = False) -> TestClient:
    users.USERS_DIR = Path(tempfile.mkdtemp()) / "users"
    os.environ.pop(auth.AUTH_ENV, None)
    if open_mode:
        os.environ[auth.AUTH_ENV] = "off"
    for email, password in accounts:
        users.create_user(email, password)
    reset_limits()
    return TestClient(server.app if through_server else api.app, raise_server_exceptions=False)


def request_with(headers: dict[str, str], client: tuple[str, int] | None = ("203.0.113.5", 4000), scheme: str = "http") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "scheme": scheme,
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": client,
    }
    return Request(scope)


OWNER = ("owner@example.com", "correct horse battery")

# --- the limiter ------------------------------------------------------------------------------------

t = auth.AttemptLimiter(per_client=3, window_seconds=100, overall=5)
check("an attempt under the limits is allowed and counted", t.begin("a", now=0) == 0 and t.begin("a", now=1) == 0 and t.begin("a", now=2) == 0)
wait = t.begin("a", now=3)
check("past the per-client limit it is refused, with a wait", wait > 0 and wait <= 100, str(wait))
check("another client isn't held by it", t.begin("b", now=4) == 0)
check("the overall limit stops every client once all together reach it", t.begin("c", now=5) == 0 and t.begin("d", now=6) > 0)
check("...until the window moves on", t.begin("d", now=200) == 0)
t = auth.AttemptLimiter(per_client=3, window_seconds=100)
for i in range(3):
    t.begin("a", now=i)
t.begin("a", now=3)  # Refused.
check("a refused attempt isn't counted, so the wait ends when the first counted one does", t.retry_after("a", now=99) > 0 and t.retry_after("a", now=101) == 0)
t = auth.AttemptLimiter(per_client=3, window_seconds=100)
for _ in range(3):
    t.begin("a", now=0)
t.forgive("a")
check("forgiving gives the attempts back", t.begin("a", now=1) == 0 and t.retry_after("a", now=1) == 0)
t = auth.AttemptLimiter(per_client=3, window_seconds=100, overall=2)
t.begin("a", now=0)
t.begin("b", now=0)
t.forgive("a")
check("...and gives back that client's share of the overall limit", t.begin("c", now=1) == 0)

t = auth.AttemptLimiter(per_client=3, window_seconds=100, max_tracked=50)
for i in range(500):
    t.begin(f"made-up-{i}", now=float(i) / 100)
check("made-up addresses can't grow its memory without limit", len(t._clients) <= 50, str(len(t._clients)))
t = auth.AttemptLimiter(per_client=3, window_seconds=10)
for i in range(20):
    t.begin(f"x{i}", now=0)
t.retry_after("x0", now=50)
check("addresses that have gone quiet are forgotten", len(t._clients) == 0 and len(t._all) == 0)

# --- who is asking ----------------------------------------------------------------------------------

os.environ.pop(auth.PROXY_ENV, None)
check("without the proxy setting, the connection's address is used", auth.client_key(request_with({"fly-client-ip": "198.51.100.9", "x-forwarded-for": "198.51.100.8"})) == "203.0.113.5")
check("...and an IPv6 visitor is counted by the /64 they are in", auth.client_key(request_with({}, client=("2001:db8:1:2:aaaa:bbbb:cccc:dddd", 1))) == auth.client_key(request_with({}, client=("2001:db8:1:2::1", 1))) == "2001:db8:1:2::/64")
check("...and a connection with no usable address is one client", auth.client_key(request_with({}, client=None)) == "unknown" and auth.client_key(request_with({}, client=("testclient", 1))) == "unknown")
os.environ[auth.PROXY_ENV] = "fly"
check("behind Fly, the address Fly saw is used", auth.client_key(request_with({"fly-client-ip": "198.51.100.9", "x-forwarded-for": "198.51.100.8"})) == "198.51.100.9")
check("...and a made-up value falls back to the connection", auth.client_key(request_with({"fly-client-ip": "not an address"})) == "203.0.113.5")
check("behind Fly, the proxy's word on the scheme counts", auth.is_https({"scheme": "http", "headers": [(b"x-forwarded-proto", b"https")]}) is True and auth.is_https({"scheme": "http", "headers": []}) is False)
os.environ.pop(auth.PROXY_ENV)
check("otherwise only the connection's own scheme counts", auth.is_https({"scheme": "http", "headers": [(b"x-forwarded-proto", b"https")]}) is False and auth.is_https({"scheme": "https", "headers": []}) is True)

# --- guessing passwords with made-up addresses ------------------------------------------------------

os.environ[auth.PROXY_ENV] = "fly"
c = fresh(OWNER)
codes = [c.post("/auth/login", json={"email": OWNER[0], "password": "nope nope nope"}, headers={"Fly-Client-IP": f"198.51.100.{i}"}).status_code for i in range(auth.MAX_FAILURES_OVERALL + 3)]
check("a new address for each guess is stopped by the overall limit", codes[: auth.MAX_FAILURES_OVERALL] == [401] * auth.MAX_FAILURES_OVERALL and codes[auth.MAX_FAILURES_OVERALL :] == [429] * 3, str(codes))
check("...even with the right password", c.post("/auth/login", json={"email": OWNER[0], "password": OWNER[1]}, headers={"Fly-Client-IP": "198.51.100.200"}).status_code == 429)
os.environ.pop(auth.PROXY_ENV)
c = fresh(OWNER)
codes = [c.post("/auth/login", json={"email": OWNER[0], "password": "nope nope nope"}, headers={"X-Forwarded-For": f"198.51.100.{i}", "Fly-Client-IP": f"198.51.100.{i}"}).status_code for i in range(auth.MAX_FAILURES + 2)]
check("made-up forwarding headers don't help when the proxy setting is off", codes[auth.MAX_FAILURES :] == [429, 429], str(codes))

# --- sign out ends a copied cookie ------------------------------------------------------------------

c = fresh(OWNER)
c.post("/auth/login", json={"email": OWNER[0], "password": OWNER[1]})
copied = c.cookies.get(auth.COOKIE)
other = TestClient(api.app, raise_server_exceptions=False)
check("a copied cookie works before sign out", other.get("/decks", headers={"cookie": f"{auth.COOKIE}={copied}"}).status_code == 200)
c.post("/auth/logout")
check("signing out ends a copy of the cookie too", other.get("/decks", headers={"cookie": f"{auth.COOKIE}={copied}"}).status_code == 401)
check("...and the password still signs in", c.post("/auth/login", json={"email": OWNER[0], "password": OWNER[1]}).status_code == 200)
anon = TestClient(api.app, raise_server_exceptions=False)
check("signing out with no cookie ends nothing and doesn't fail", anon.post("/auth/logout").status_code == 200 and c.get("/decks").status_code == 200)
check("signing out with a forged cookie ends nothing", anon.post("/auth/logout", headers={"cookie": f"{auth.COOKIE}=1.1.99999999999.abc"}).status_code == 200 and c.get("/decks").status_code == 200)

# --- forged cookies ---------------------------------------------------------------------------------

forged = ["1.2.²3.sig", "x.².99999999999.sig", "a.b.c.d", "..", "1.2.3.éé", "².².².²", ".." * 100]
check("a cookie with odd digits or odd characters is refused, not an error", all(auth.session_user(v) is None for v in forged))
c = fresh(OWNER)
statuses = []
for v in forged:
    r = c.get("/decks", headers=[(b"cookie", f"{auth.COOKIE}={v}".encode("latin-1", "replace"))])
    r2 = c.get("/auth/status", headers=[(b"cookie", f"{auth.COOKIE}={v}".encode("latin-1", "replace"))])
    statuses.append((r.status_code, r2.status_code))
check("...over HTTP as well: 401 on a closed route, 200 on the status route", all(s == (401, 200) for s in statuses), str(statuses))

# --- headers and the front end ----------------------------------------------------------------------

c = fresh(open_mode=True, through_server=True)
page = c.get("/")
want = ["content-security-policy", "x-content-type-options", "x-frame-options", "referrer-policy", "permissions-policy", "cross-origin-opener-policy"]
check("the page carries the security headers", all(h in page.headers for h in want), str([h for h in want if h not in page.headers]))
check("so does the API", all(h in c.get("/api/auth/status").headers for h in want))
csp = page.headers["content-security-policy"]
check("the policy allows scripts from this server only, and no framing", "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and "object-src 'none'" in csp and "unsafe-eval" not in csp and "script-src 'self' 'unsafe" not in csp)
check("...and lets the page reach what it uses: Scryfall's API and images, Google Fonts", all(h in csp for h in ["https://api.scryfall.com", "https://cards.scryfall.io", "https://svgs.scryfall.io", "https://fonts.googleapis.com", "https://fonts.gstatic.com"]))
check("plain HTTP gets no HSTS", "strict-transport-security" not in page.headers)
check("an HTTPS connection gets HSTS", "strict-transport-security" in TestClient(server.app, base_url="https://testserver").get("/").headers)
os.environ[auth.PROXY_ENV] = "fly"
check("...and so does a request Fly says came in over HTTPS", "strict-transport-security" in c.get("/", headers={"X-Forwarded-Proto": "https"}).headers and "strict-transport-security" not in c.get("/").headers)
os.environ.pop(auth.PROXY_ENV)
check("the interactive docs and the schema are off", all(c.get(p).status_code == 404 for p in ["/api/docs", "/api/redoc", "/api/openapi.json", "/openapi.json"]))
check("a path with a NUL byte is a 404, not an error", c.get("/%00").status_code == 404 and c.get("/assets/%00.js").status_code == 404)

# --- request size -----------------------------------------------------------------------------------

check("the limits: a stranger's routes are small, the rest larger", hardening.body_limit_for("/auth/login") == hardening.STRANGER_BODY_LIMIT_BYTES == hardening.body_limit_for("/public/decks/abc/cards") and hardening.body_limit_for("/decks/abc/cards/import") == hardening.BODY_LIMIT_BYTES)
big = "x" * (hardening.STRANGER_BODY_LIMIT_BYTES + 10)
r = c.post("/api/auth/login", content=f'{{"email":"a@b.co","password":"{big}"}}', headers={"Content-Type": "application/json"})
check("an oversized login request is refused with a 413", r.status_code == 413, str(r.status_code))
r = c.post("/api/auth/login", content=iter([b'{"email":"a@b.co","password":"', big.encode(), b'"}']), headers={"Content-Type": "application/json"})
check("...also when it is streamed with no length", r.status_code == 413, str(r.status_code))
big_signed_in = "x" * (hardening.BODY_LIMIT_BYTES + 10)
r = c.post("/api/collection/bulk", content=f'{{"names":["{big_signed_in}"]}}', headers={"Content-Type": "application/json"})
check("an oversized request on a signed-in route is refused too", r.status_code == 413, str(r.status_code))
check("a normal request goes through", c.post("/api/decks", json={"name": "Fine"}).status_code == 200)
r = c.post("/api/auth/login", content="{}", headers={"Content-Type": "application/json", "Content-Length": "abc"})
check("a Content-Length that isn't a number is a 400", r.status_code in (400, 422), str(r.status_code))

# --- what a route accepts ---------------------------------------------------------------------------

c = fresh(open_mode=True)
deck = c.post("/decks", json={"name": "Limits"}).json()
base = f"/decks/{deck['id']}"
check("importing a billion copies is refused before anything is built", c.post(f"{base}/cards/import", json={"entries": [{"name": "Sol Ring", "quantity": 10**9}]}).status_code == 422)
check("...as is none or a negative number", c.post(f"{base}/cards/import", json={"entries": [{"name": "Sol Ring", "quantity": 0}]}).status_code == 422 and c.post(f"{base}/cards/import", json={"entries": [{"name": "Sol Ring", "quantity": -5}]}).status_code == 422)
check("adding a billion at once is refused", c.post(f"{base}/cards/bulk", json={"name": "Forest", "count": 10**9}).status_code == 422)
check("...and fewer than one is still a 400", c.post(f"{base}/cards/bulk", json={"name": "Forest", "count": 0}).status_code == 400)
check("an import with too many entries is refused", c.post(f"{base}/cards/import", json={"entries": [{"name": "Forest", "quantity": 1}] * (api.MAX_LIST + 1)}).status_code == 422)
check("a chat message that is too long is refused", c.post(f"{base}/chat", json={"message": "x" * (api.CHAT_MESSAGE_MAX + 1)}).status_code == 422)
check("a deck name or a card name that is too long is refused", c.post(f"{base}/name", json={"name": "x" * 101}).status_code == 422 and c.post(f"{base}/cards", json={"name": "x" * (api.NAME_MAX + 1)}).status_code == 422)
check("a batch with too many names is refused", c.post("/cards/batch", json={"names": ["Sol Ring"] * (api.MAX_LIST + 1)}).status_code == 422)
check("so is a collection import beyond the limit", c.post("/collection/bulk", json={"names": ["Sol Ring"] * (api.MAX_COLLECTION_IMPORT + 1)}).status_code == 422)
check("a rename within the limit works", c.post(f"{base}/name", json={"name": "x" * 100}).status_code == 200)
check("a rulings id must be a Scryfall id", c.get("/cards/rulings", params={"id": "../../cards/search?q=x"}).status_code == 422 and c.get("/cards/rulings", params={"id": "abc"}).status_code == 422)
check("is_scryfall_id accepts a real one only", is_scryfall_id("0c0a2a3c-6f4d-4a65-8f0e-6a2d7d6b5c11") and not is_scryfall_id("0c0a2a3c-6f4d-4a65-8f0e-6a2d7d6b5c11/../x") and not is_scryfall_id("") and not is_scryfall_id("../x"))

# --- deck ids and guessing deck addresses -----------------------------------------------------------

made = D.Deck()
check("a new deck's id is 16 hex digits", len(made.id) == 16 and D.DECK_ID_PATTERN.fullmatch(made.id) is not None and len({D.Deck().id for _ in range(200)}) == 200)
check("an id made before that, with 8 digits, still counts as one", D.DECK_ID_PATTERN.fullmatch("0a1b2c3d") is not None)
D.save_deck(D.Deck(id="0a1b2c3d", name="Old id"))
check("...and its deck still loads", D.load_deck("0a1b2c3d") is not None)
check("an id that is a path or has a NUL in it loads nothing and is no error", all(D.load_deck(v) is None for v in ["../secret", "a/b", "..", "", "a\x00b", "x" * 200]) and D.delete_deck("../x") is False and D.delete_deck("a\x00b") is False)

c = fresh(open_mode=True)
real = c.post("/decks", json={"name": "Real"}).json()
check("a real deck's page is never held up by other visitors' misses", all(c.get(f"/public/decks/{real['id']}").status_code == 200 for _ in range(auth.MAX_DECK_MISSES + 5)))
codes = [c.get(f"/public/decks/{os.urandom(8).hex()}").status_code for _ in range(auth.MAX_DECK_MISSES + 3)]
check("a client that keeps asking for decks that aren't there is turned away", codes[: auth.MAX_DECK_MISSES] == [404] * auth.MAX_DECK_MISSES and codes[auth.MAX_DECK_MISSES :] == [429] * 3, str(codes))
locked = c.get(f"/public/decks/{real['id']}")
check("...with a wait time, on every public deck route", locked.status_code == 429 and int(locked.headers["retry-after"]) > 0 and c.post(f"/public/decks/{real['id']}/cards", json={"names": []}).status_code == 429 and c.get(f"/public/decks/{real['id']}/rulings", params={"id": "x"}).status_code == 429)
check("...and the signed-in routes are not held up by it", c.get("/decks").status_code == 200)
c = fresh(open_mode=True)
check("a bad id (wrong shape) counts as a miss as well", [c.get("/public/decks/not-an-id").status_code for _ in range(auth.MAX_DECK_MISSES + 1)][-1] == 429)

# --- the deck list leaves out the chat -------------------------------------------------------------

c = fresh(open_mode=True)
chatty = c.post("/decks", json={"name": "Chatty"}).json()
D.save_messages(D.load_deck(chatty["id"]), [{"role": "user", "content": "hello " * 2000}, {"role": "assistant", "content": "hi " * 2000}])
listed = c.get("/decks")
one = next(d for d in listed.json() if d["id"] == chatty["id"])
opened = c.get(f"/decks/{chatty['id']}").json()
check("the deck list has every deck but not its chat history", one["messages"] == [] and one["name"] == "Chatty" and len(listed.content) < 2000, f"{len(listed.content)} bytes")
check("...while the deck itself still has the conversation", len(opened["messages"]) == 2 and D.load_deck(chatty["id"]).messages != [])
check("...and listing changes nothing on disk", len(D.load_deck(chatty["id"]).messages) == 2)

# --- the command line drops root --------------------------------------------------------------------

check("as root, the command line acts as the data folder's owner", cli.privilege_target(0, (10001, 10001)) == (10001, 10001))
check("...not when root owns it, or it isn't there, or the user isn't root", cli.privilege_target(0, (0, 0)) is None and cli.privilege_target(0, None) is None and cli.privilege_target(501, (10001, 10001)) is None)

print(f"\n{sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
