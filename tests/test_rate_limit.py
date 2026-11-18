"""Tests for the volume limits: how many requests one address may make in an hour, and how many model
calls one account may start in an hour. The counter itself, the middleware that applies it to every
request (files included), and the per-account count on the routes that call the model. No network and no
model: the model calls are stubbed. Run with

    uv run python tests/test_rate_limit.py
"""

import os
import tempfile
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

import mtg_deck_doctor.deck as D
import mtg_deck_doctor.users as users
from mtg_deck_doctor import api, auth, server

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

Limiter = auth.RequestLimiter

# --- the counter -----------------------------------------------------------------------------------------

limiter = Limiter(5, 100)
check("a key may make its limit's worth of requests", [limiter.begin("a", now=0) for _ in range(5)] == [0] * 5)
wait = limiter.begin("a", now=0)
check("the next one is refused, with a wait of about a window", 0 < wait <= 101, str(wait))
check("another key isn't held by it", limiter.begin("b", now=0) == 0)
check("a refused request isn't counted: asking again changes nothing", [limiter.begin("a", now=1) > 0 for _ in range(50)] == [True] * 50 and limiter.begin("a", now=wait) == 0)


def burst(limit: int, window: float, at: float) -> Limiter:
    made = Limiter(limit, window)
    for _ in range(limit):
        assert made.begin("k", now=at) == 0
    return made


for at in (0.0, 37.5, 99.0, 100.0, 140.0):
    made = burst(10, 100, at)
    wait = made.begin("k", now=at)
    ok_after = Limiter(10, 100)
    ok_after._keys = {k: list(v) for k, v in made._keys.items()}
    check(f"a burst at t={at} is refused, and the wait it is given is enough", wait > 0 and ok_after.begin("k", now=at + wait) == 0, str(wait))
    if wait > 3:
        short = Limiter(10, 100)
        short._keys = {k: list(v) for k, v in made._keys.items()}
        check(f"...and not longer than needed (t={at})", short.begin("k", now=at + wait - 3) > 0)

made = burst(100, 100, 0)
allowed = sum(made.begin("k", now=150) == 0 for _ in range(200))
check("half a window after a full one, about half the limit is allowed (a sliding window, not a reset)", 48 <= allowed <= 52, str(allowed))
made = burst(100, 100, 0)
check("two windows later, the whole limit is back", sum(made.begin("k", now=250) == 0 for _ in range(150)) == 100)
made = Limiter(100, 100)
for _ in range(100):
    made.begin("k", now=0)
check("a key doesn't get the window's worth twice by waiting for the clock to tick over", sum(made.begin("k", now=101) == 0 for _ in range(200)) <= 3)

check("a limit of 0 never refuses", all(Limiter(0, 100).begin("a", now=0) == 0 for _ in range(1000)))
check("a negative limit never refuses", all(Limiter(-5, 100).begin("a", now=0) == 0 for _ in range(1000)))

many = Limiter(5, 100, max_tracked=100)
for i in range(10_000):
    many.begin(f"made-up-{i}", now=0)
check("made-up keys can't grow its memory without limit", len(many._keys) == 100, str(len(many._keys)))
check("...the least recently seen go first", "made-up-0" not in many._keys and "made-up-9999" in many._keys)
many = Limiter(5, 100, max_tracked=3)
for key in ("a", "b", "c"):
    many.begin(key, now=0)
many.begin("a", now=0)
many.begin("d", now=0)
check("a key seen again is kept over one that has been quiet", list(many._keys) == ["c", "a", "d"], str(list(many._keys)))

busy = Limiter(10**9, 3600)
started = time.perf_counter()
for i in range(100_000):
    busy.begin(f"key-{i % 20_000}", now=float(i))
spent = time.perf_counter() - started
check("a request costs the same however many keys are held (100,000 requests across 20,000 keys)", spent < 5, f"{spent:.2f}s")

shared = Limiter(1000, 3600)
allowed_count = []


def hammer() -> None:
    allowed_count.append(sum(shared.begin("k", now=0) == 0 for _ in range(500)))


threads = [threading.Thread(target=hammer) for _ in range(8)]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
check("at the same moment from many threads, exactly the limit gets through", sum(allowed_count) == 1000, str(sum(allowed_count)))

os.environ["TEST_LIMIT"] = "75"
a = auth._env_limit("TEST_LIMIT", 5)
os.environ["TEST_LIMIT"] = "  "
b = auth._env_limit("TEST_LIMIT", 5)
os.environ["TEST_LIMIT"] = "lots"
c_ = auth._env_limit("TEST_LIMIT", 5)
os.environ["TEST_LIMIT"] = "0"
d = auth._env_limit("TEST_LIMIT", 5)
os.environ.pop("TEST_LIMIT")
e = auth._env_limit("TEST_LIMIT", 5)
check("a limit is read from the environment, and the default is used when it is blank, junk or unset", (a, b, c_, d, e) == (75, 5, 5, 0, 5), str((a, b, c_, d, e)))
check("the defaults are 2,000 requests and 30 model calls an hour", (auth.DEFAULT_REQUESTS_PER_HOUR, auth.DEFAULT_AI_REQUESTS_PER_HOUR) == (2000, 30))
check("Fly's health check (every 30 seconds) uses a small part of an address's hour", 3600 / 30 <= auth.DEFAULT_REQUESTS_PER_HOUR / 10)

# --- every request is counted against its address --------------------------------------------------------

os.environ["MTG_DECK_DOCTOR_AUTH"] = "off"  # No account: the page and the API answer without a sign-in.
client = TestClient(server.app, raise_server_exceptions=False)
os.environ[auth.PROXY_ENV] = "fly"


def from_address(address: str) -> dict[str, str]:
    return {"Fly-Client-IP": address}


auth.request_limiter = Limiter(5, 3600)
codes = [client.get("/", headers=from_address("198.51.100.1")).status_code for _ in range(7)]
check("an address is turned away once it has used its hour", codes == [200] * 5 + [429] * 2, str(codes))
refusal = client.get("/", headers=from_address("198.51.100.1"))
check("...with a Retry-After, and a sentence that says when", refusal.headers["retry-after"].isdigit() and 0 < int(refusal.headers["retry-after"]) <= 3601 and "Too many requests" in refusal.json()["detail"] and "Try again in" in refusal.json()["detail"], refusal.text)
check("...and the security headers are on the refusal too", refusal.headers.get("x-frame-options") == "DENY" and "content-security-policy" in refusal.headers)
check("another address isn't held by it", client.get("/", headers=from_address("198.51.100.2")).status_code == 200)

auth.request_limiter = Limiter(3, 3600)
first = [client.get(path, headers=from_address("198.51.100.3")).status_code for path in ("/", "/assets/app-abc123.js", "/api/auth/status")]
check("files and API calls count as much as the page", first == [200, 200, 200] and client.get("/api/auth/status", headers=from_address("198.51.100.3")).status_code == 429, str(first))
auth.request_limiter = Limiter(2, 3600)
client.head("/", headers=from_address("198.51.100.4"))
client.post("/api/auth/logout", headers=from_address("198.51.100.4"))
check("HEAD and POST count too", client.get("/", headers=from_address("198.51.100.4")).status_code == 429)
check("a missing file counts, so guessing addresses is limited too", [client.get(f"/nope-{i}.png", headers=from_address("198.51.100.5")).status_code for i in range(3)] == [404, 404, 429])

auth.request_limiter = Limiter(3, 3600)
shared_block = [client.get("/", headers=from_address(f"2001:db8:1:2::{i}")).status_code for i in range(1, 5)]
check("an IPv6 visitor is counted by its /64, so changing the last digits doesn't help", shared_block == [200, 200, 200, 429], str(shared_block))
check("...but another /64 is another visitor", client.get("/", headers=from_address("2001:db8:1:3::1")).status_code == 200)

os.environ.pop(auth.PROXY_ENV)
auth.request_limiter = Limiter(3, 3600)
spoofed = [client.get("/", headers=from_address(f"198.51.100.{i}")).status_code for i in range(10, 15)]
check("with the proxy setting off, a made-up Fly-Client-IP doesn't buy a new count", spoofed == [200, 200, 200, 429, 429], str(spoofed))

os.environ[auth.PROXY_ENV] = "fly"
auth.request_limiter = Limiter(0, 3600)
check("a limit of 0 turns the limit off", all(client.get("/", headers=from_address("198.51.100.6")).status_code == 200 for _ in range(50)))
auth.request_limiter = Limiter(2, 3600)
client.get("/", headers=from_address("198.51.100.7"))
client.get("/", headers=from_address("198.51.100.7"))
check("the page works again for an address that waits out the answer", client.get("/", headers=from_address("198.51.100.7")).status_code == 429)
os.environ.pop(auth.PROXY_ENV)

# --- model calls are counted against the account ---------------------------------------------------------

os.environ.pop("MTG_DECK_DOCTOR_AUTH")
users.USERS_DIR = Path(tempfile.mkdtemp()) / "users"
alice = users.create_user("alice@example.com", "a long enough password")
bob = users.create_user("bob@example.com", "another long password")
a_client = TestClient(api.app, raise_server_exceptions=False)
b_client = TestClient(api.app, raise_server_exceptions=False)
a_client.post("/auth/login", json={"email": "alice@example.com", "password": "a long enough password"})
b_client.post("/auth/login", json={"email": "bob@example.com", "password": "another long password"})

model_calls: list[str] = []
api.run_conversation = lambda deck, messages, message: (model_calls.append("chat") or "ok", [])
api.review_cuts = lambda deck, candidates, health: (model_calls.append("cuts"), [])[1]

D.save_deck(D.Deck(id="alice-deck", commander="Sol Ring", owner_id=alice.id))
D.save_deck(D.Deck(id="bob-deck", commander="Sol Ring", owner_id=bob.id))
CHAT = {"message": "hi"}
REVIEW = {"candidates": [], "health": []}

auth.ai_limiter = Limiter(3, 3600)
codes = [a_client.post("/decks/alice-deck/chat", json=CHAT).status_code for _ in range(5)]
check("an account may start its limit's worth of chat messages, and no more", codes == [200, 200, 200, 429, 429], str(codes))
check("a refused message never reaches the model", model_calls.count("chat") == 3, str(model_calls))
refusal = a_client.post("/decks/alice-deck/chat", json=CHAT)
body = refusal.json()
check("the refusal is a typed AI error the page already knows how to show", refusal.status_code == 429 and body["code"] == "ai_account_limit" and body["code"].startswith("ai_"), str(body))
check("...with how long to wait, as seconds in the body and the header", isinstance(body["retry_after"], int) and 0 < body["retry_after"] <= 3601 and refusal.headers["retry-after"] == str(body["retry_after"]), str(body))
check("...and a sentence that says how many (the page adds the countdown)", body["detail"] == "You've used this hour's 3 requests to the Doctor.", body["detail"])
check("another account isn't held by it", b_client.post("/decks/bob-deck/chat", json=CHAT).status_code == 200)
check("the account that is over can still do everything that doesn't call the model", a_client.get("/decks").status_code == 200 and a_client.get("/decks/alice-deck").status_code == 200 and a_client.get("/decks/alice-deck/cuts").status_code == 200)

auth.ai_limiter = Limiter(3, 3600)
model_calls.clear()
codes = [a_client.post("/decks/alice-deck/cuts/review", json=REVIEW).status_code for _ in range(5)]
check("a review of cuts counts as a model call (400 here, since the stub reviews nothing)", codes == [400, 400, 400, 429, 429], str(codes))
auth.ai_limiter = Limiter(3, 3600)
a_client.post("/decks/alice-deck/chat", json=CHAT)
a_client.post("/decks/alice-deck/chat", json=CHAT)
check("chat, reviews and the rest share one count per account", a_client.post("/decks/alice-deck/cuts/review", json=REVIEW).status_code == 400 and a_client.post("/decks/alice-deck/chat", json=CHAT).status_code == 429)

auth.ai_limiter = Limiter(2, 3600)
for _ in range(10):
    a_client.get("/decks/alice-deck/cuts")
    a_client.get("/decks/alice-deck/suggestions")
    a_client.get("/decks/alice-deck/discoveries")
check("reading a stored result costs nothing", [a_client.post("/decks/alice-deck/chat", json=CHAT).status_code for _ in range(3)] == [200, 200, 429])

auth.ai_limiter = Limiter(2, 3600)
nothing = [a_client.post("/decks/not-a-deck/chat", json=CHAT).status_code for _ in range(6)]
too_long = a_client.post("/decks/alice-deck/chat", json={"message": "x" * (api.CHAT_MESSAGE_MAX + 1)}).status_code
someone_elses = a_client.post("/decks/bob-deck/chat", json=CHAT).status_code
check("a request that never gets to the model doesn't count: no such deck, a message too long, someone else's deck", set(nothing) == {404} and too_long == 422 and someone_elses == 404, str((nothing, too_long, someone_elses)))
check("...so the account still has all of its calls", [a_client.post("/decks/alice-deck/chat", json=CHAT).status_code for _ in range(3)] == [200, 200, 429])

auth.ai_limiter = Limiter(0, 3600)
check("a limit of 0 turns the limit off", all(a_client.post("/decks/alice-deck/chat", json=CHAT).status_code == 200 for _ in range(40)))

# With no account, the app runs open (a local run): every call counts against one shared key.
users.USERS_DIR = Path(tempfile.mkdtemp()) / "users"
os.environ["MTG_DECK_DOCTOR_AUTH"] = "off"
open_client = TestClient(api.app, raise_server_exceptions=False)
D.save_deck(D.Deck(id="open-deck", commander="Sol Ring"))
auth.ai_limiter = Limiter(2, 3600)
check("run open, the calls are counted too", [open_client.post("/decks/open-deck/chat", json=CHAT).status_code for _ in range(3)] == [200, 200, 429])

print(f"\n{sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
