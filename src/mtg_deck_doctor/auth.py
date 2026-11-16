"""Signing in: an account's email and password (see users.py), and a signed cookie after that.

Every route needs the cookie except the ones marked `@public` (the login routes and the routes a
public deck page reads). A route added later is closed until someone marks it.

The login is on as soon as an account exists, and then `MTG_DECK_DOCTOR_AUTH=off` does nothing, so a
server can't be left open by a stray setting. With no account, the app is closed (`unconfigured`)
unless `MTG_DECK_DOCTOR_AUTH=off` says to run open, which `dev-backend.sh` does for local work.

The cookie holds the user's id, the user's session version, an expiry, and an HMAC of those. The HMAC
key is a random secret kept in `data/session_secret`. Raising a user's session version (a new password,
`mtg-deck-doctor revoke-sessions`, or signing out) ends every cookie that user has.
"""

import hashlib
import hmac
import ipaddress
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from contextvars import ContextVar
from pathlib import Path

from starlette.requests import Request
from starlette.types import Scope

from mtg_deck_doctor import users
from mtg_deck_doctor.users import User

AUTH_ENV = "MTG_DECK_DOCTOR_AUTH"
COOKIE = "mtgdd_session"
SESSION_SECONDS = 30 * 24 * 3600
SECRET_PATH = Path("data/session_secret")

# Sign-in attempts allowed per client address in a window, before it is turned away until the window moves
# on. The overall limit counts every address together, so an attacker who can make up addresses still gets
# only this many guesses in the window. It also means a flood of wrong guesses can lock the owner out of the
# sign-in page for up to one window; a browser that is already signed in is not affected.
MAX_FAILURES = 8
MAX_FAILURES_OVERALL = 30
FAILURE_WINDOW_SECONDS = 600

# Set to `fly` when the app runs behind Fly.io's proxy (fly.toml does). The proxy is then the only way in, so
# its headers say who the visitor is and which scheme they used. Without it, those headers are ignored,
# because anyone can send them.
PROXY_ENV = "MTG_DECK_DOCTOR_PROXY"

# Who is signed in on the request being handled, or None when the app runs open. Set before a route runs
# (see require_owner in api.py), and read by whatever decides which decks that person may see.
current_user: ContextVar[User | None] = ContextVar("current_user", default=None)


def mode() -> str:
    """`on` (an account exists), `off` (no account, and run open was asked for), or `unconfigured`."""
    if users.any_users():
        return "on"
    return "off" if os.environ.get(AUTH_ENV, "").strip().lower() == "off" else "unconfigured"


def public(fn):
    """Marks a route as open to anyone. Put it under the route decorator."""
    fn.public = True
    return fn


# ---- the cookie --------------------------------------------------------------------------------------

_secret_lock = threading.Lock()


def _key() -> bytes:
    with _secret_lock:
        if not SECRET_PATH.exists():
            SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
            # Created readable by the owner only, and never replaced once it exists.
            fd = os.open(SECRET_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(secrets.token_hex(32))
        return hashlib.sha256(SECRET_PATH.read_text().strip().encode()).digest()


def _sign(payload: str) -> str:
    return hmac.new(_key(), payload.encode(), hashlib.sha256).hexdigest()


def make_session(user: User, now: float | None = None) -> str:
    expires = int((time.time() if now is None else now) + SESSION_SECONDS)
    payload = f"{user.id}.{user.session_version}.{expires}"
    return f"{payload}.{_sign(payload)}"


def session_user(value: str | None, now: float | None = None) -> User | None:
    """The user a cookie belongs to, or None if it is missing, forged, expired, or from before the
    user's sessions were last ended."""
    if not value:
        return None
    parts = value.split(".")
    if len(parts) != 4:
        return None
    user_id, version, expires, signature = parts
    # `str.isdigit()` is true for characters like "²" that `int()` refuses, so ask for plain ASCII digits.
    if not (_ascii_digits(version) and _ascii_digits(expires) and signature):
        return None
    if int(expires) <= (time.time() if now is None else now):
        return None
    try:
        signed = hmac.compare_digest(signature.encode(), _sign(f"{user_id}.{version}.{expires}").encode())
    except UnicodeEncodeError:
        return None
    if not signed:
        return None
    user = users.get_user(user_id)
    if user is None or user.session_version != int(version):
        return None
    return user


def _ascii_digits(value: str) -> bool:
    return value.isascii() and value.isdigit()


# ---- who is asking, and the limits -------------------------------------------------------------------


def behind_fly() -> bool:
    return os.environ.get(PROXY_ENV, "").strip().lower() == "fly"


def client_key(request: Request) -> str:
    """Who to count this request against. Behind Fly.io it is the address Fly's proxy saw. Otherwise it is
    the address of the connection. An IPv6 visitor is counted by the /64 their address is in, because one
    household or one attacker holds the whole block."""
    candidates = []
    if behind_fly():
        candidates.append(request.headers.get("fly-client-ip", ""))
    if request.client:
        candidates.append(request.client.host)
    for raw in candidates:
        try:
            address = ipaddress.ip_address(raw.strip())
        except ValueError:
            continue
        if address.version == 6:
            return str(ipaddress.ip_network(f"{address}/64", strict=False))
        return str(address)
    return "unknown"


def is_https(scope: Scope) -> bool:
    """Whether a request came in over HTTPS: the connection says so, or, behind Fly.io, the proxy says
    the visitor used it."""
    if scope.get("scheme") in ("https", "wss"):
        return True
    if behind_fly():
        for name, value in scope["headers"]:
            if name == b"x-forwarded-proto":
                return value.decode("latin-1").split(",")[0].strip() == "https"
    return False


class AttemptLimiter:
    """Counts attempts per client address, and across all addresses, in a sliding window, so a password
    or an address can't be guessed at speed.

    `begin` counts an attempt before the work it guards starts, in the same step as the check. Counting
    a failure afterwards instead would let a burst of simultaneous requests all pass the check before
    the first of them failed."""

    def __init__(self, per_client: int, window_seconds: float, overall: int | None = None, max_tracked: int = 10_000) -> None:
        self.per_client = per_client
        self.window = window_seconds
        self.overall = overall
        self.max_tracked = max_tracked
        self._clients: dict[str, deque[float]] = {}
        self._all: deque[tuple[float, str]] = deque()
        self._lock = threading.Lock()

    def _expire(self, now: float) -> None:
        while self._all and now - self._all[0][0] > self.window:
            self._all.popleft()
        for client in [c for c, times in self._clients.items() if not times or now - times[-1] > self.window]:
            del self._clients[client]
        for times in self._clients.values():
            while times and now - times[0] > self.window:
                times.popleft()

    def _count(self, client: str, now: float) -> None:
        self._clients.setdefault(client, deque()).append(now)
        self._all.append((now, client))
        # Made-up addresses can't grow this without limit: past the cap, the oldest go first.
        while len(self._clients) > self.max_tracked:
            del self._clients[next(iter(self._clients))]

    def _wait(self, client: str, now: float) -> int:
        times = self._clients.get(client)
        waits = []
        if times is not None and len(times) >= self.per_client:
            waits.append(self.window - (now - times[0]))
        if self.overall is not None and len(self._all) >= self.overall:
            waits.append(self.window - (now - self._all[0][0]))
        return int(max(waits)) + 1 if waits else 0

    def retry_after(self, client: str, now: float | None = None) -> int:
        """Seconds until this client may try again, or 0 if it may now. Counts nothing."""
        now = time.monotonic() if now is None else now
        with self._lock:
            self._expire(now)
            return self._wait(client, now)

    def record(self, client: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            self._count(client, now)

    def begin(self, client: str, now: float | None = None) -> int:
        """Counts an attempt and returns 0, or, if the client is over a limit, counts nothing and returns
        how many seconds it must wait."""
        now = time.monotonic() if now is None else now
        with self._lock:
            self._expire(now)
            wait = self._wait(client, now)
            if wait == 0:
                self._count(client, now)
            return wait

    def forgive(self, client: str) -> None:
        """Drops what this client has used up, after it signed in."""
        with self._lock:
            self._clients.pop(client, None)
            self._all = deque(entry for entry in self._all if entry[1] != client)


throttle = AttemptLimiter(MAX_FAILURES, FAILURE_WINDOW_SECONDS, overall=MAX_FAILURES_OVERALL)

# Guesses at deck addresses that found no deck. A real visitor opens a link that works, so a handful of
# misses in ten minutes is already unusual.
MAX_DECK_MISSES = 20
deck_misses = AttemptLimiter(MAX_DECK_MISSES, FAILURE_WINDOW_SECONDS, overall=None)

# Requests for the browse page's list, which anyone can make. Real browsing is a few a minute.
MAX_BROWSE_PER_MINUTE = 120
browse_limiter = AttemptLimiter(MAX_BROWSE_PER_MINUTE, 60, overall=None)
