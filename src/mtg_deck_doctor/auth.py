"""Signing in: an account's email and password (see users.py), and a signed cookie after that.

Every route needs the cookie except the ones marked `@public` (the login routes and the routes a
public deck page reads). A route added later is closed until someone marks it.

The login is on as soon as an account exists, and then `MTG_DECK_DOCTOR_AUTH=off` does nothing, so a
server can't be left open by a stray setting. With no account, the app is closed (`unconfigured`)
unless `MTG_DECK_DOCTOR_AUTH=off` says to run open, which `dev-backend.sh` does for local work.

The cookie holds the user's id, the user's session version, an expiry, and an HMAC of those. The HMAC
key is a random secret kept in `data/session_secret`. Raising a user's session version (a new password,
or `mtg-deck-doctor revoke-sessions`) ends every cookie that user has.
"""

import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from contextvars import ContextVar
from pathlib import Path

from mtg_deck_doctor import users
from mtg_deck_doctor.users import User

AUTH_ENV = "MTG_DECK_DOCTOR_AUTH"
COOKIE = "mtgdd_session"
SESSION_SECONDS = 30 * 24 * 3600
SECRET_PATH = Path("data/session_secret")

# Failed logins allowed per client address in a window, before it is turned away until the window moves on.
MAX_FAILURES = 8
FAILURE_WINDOW_SECONDS = 600

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
    if not (version.isdigit() and expires.isdigit() and signature):
        return None
    if int(expires) <= (time.time() if now is None else now):
        return None
    if not hmac.compare_digest(signature, _sign(f"{user_id}.{version}.{expires}")):
        return None
    user = users.get_user(user_id)
    if user is None or user.session_version != int(version):
        return None
    return user


# ---- the throttle ------------------------------------------------------------------------------------


class LoginThrottle:
    """Counts failed logins per client address, so a password can't be guessed at speed."""

    def __init__(self) -> None:
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _recent(self, client: str, now: float) -> deque[float]:
        failures = self._failures[client]
        while failures and now - failures[0] > FAILURE_WINDOW_SECONDS:
            failures.popleft()
        return failures

    def retry_after(self, client: str, now: float | None = None) -> int:
        """Seconds until this client may try again, or 0 if it may now."""
        now = time.monotonic() if now is None else now
        with self._lock:
            failures = self._recent(client, now)
            if len(failures) < MAX_FAILURES:
                return 0
            return int(FAILURE_WINDOW_SECONDS - (now - failures[0])) + 1

    def record_failure(self, client: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            self._recent(client, now).append(now)

    def reset(self, client: str) -> None:
        with self._lock:
            self._failures.pop(client, None)


throttle = LoginThrottle()
