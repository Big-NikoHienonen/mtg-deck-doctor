"""The owner's login: one password, and a signed cookie once you have entered it.

Every route needs the cookie except the ones marked `@public` (the login routes and the routes a
public deck page reads). A route added later is closed until someone marks it.

The password comes from `MTG_DECK_DOCTOR_PASSWORD`. Without one, the app is closed (`unconfigured`)
unless `MTG_DECK_DOCTOR_AUTH=off` says to run open, which `dev-backend.sh` does for local work. A set
password always wins, so you can try the login locally.

The cookie holds an expiry and an HMAC of it. The HMAC key comes from the password and a random secret
kept in `data/session_secret`, so changing the password signs everyone out, and the cookie alone can't be
used to guess the password.
"""

import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

PASSWORD_ENV = "MTG_DECK_DOCTOR_PASSWORD"
AUTH_ENV = "MTG_DECK_DOCTOR_AUTH"
COOKIE = "mtgdd_session"
SESSION_SECONDS = 30 * 24 * 3600
SECRET_PATH = Path("data/session_secret")

# Failed logins allowed per client address in a window, before it is turned away until the window moves on.
MAX_FAILURES = 8
FAILURE_WINDOW_SECONDS = 600


def _password() -> str:
    return os.environ.get(PASSWORD_ENV, "").strip()


def mode() -> str:
    """`on` (a password is set), `off` (run open, asked for explicitly), or `unconfigured` (closed)."""
    if _password():
        return "on"
    return "off" if os.environ.get(AUTH_ENV, "").strip().lower() == "off" else "unconfigured"


def public(fn):
    """Marks a route as open to anyone. Put it under the route decorator."""
    fn.public = True
    return fn


def password_ok(candidate: str) -> bool:
    password = _password()
    return bool(password) and hmac.compare_digest(candidate.encode(), password.encode())


_secret_lock = threading.Lock()


def _key() -> bytes:
    with _secret_lock:
        if not SECRET_PATH.exists():
            SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
            # Created readable by the owner only, and never replaced once it exists.
            fd = os.open(SECRET_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(secrets.token_hex(32))
        secret = SECRET_PATH.read_text().strip()
    return hashlib.sha256(f"{secret}:{_password()}".encode()).digest()


def _sign(expires: int) -> str:
    return hmac.new(_key(), str(expires).encode(), hashlib.sha256).hexdigest()


def make_session(now: float | None = None) -> str:
    expires = int((time.time() if now is None else now) + SESSION_SECONDS)
    return f"{expires}.{_sign(expires)}"


def valid_session(value: str | None, now: float | None = None) -> bool:
    if not value or _password() == "":
        return False
    expires_text, _, signature = value.partition(".")
    if not expires_text.isdigit() or not signature:
        return False
    if int(expires_text) <= (time.time() if now is None else now):
        return False
    return hmac.compare_digest(signature, _sign(int(expires_text)))


class LoginThrottle:
    """Counts failed logins per client address, so the password can't be guessed at speed."""

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
