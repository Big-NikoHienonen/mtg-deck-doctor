"""The accounts: one JSON file per user under data/users, with a salted scrypt hash of the password and a
username. The username is what other people see of a user, on the decks they have made public. The
email is never shown to anyone but its owner.

There is no sign-up. An account is made on the server's command line (see cli.py). The password is
never stored. What is stored is a scrypt hash with its own salt and its cost settings, so the cost can be
raised later and an account's hash is upgraded the next time its owner signs in.

`session_version` is part of every login cookie (see auth.py). Raising it signs the user out of every
browser at once, which setting a new password does.
"""

import base64
import functools
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path

from mtg_deck_doctor import moderation

USERS_DIR = Path("data/users")

# scrypt cost. N=2**15, r=8, p=3 is one of the equal-strength settings OWASP lists for scrypt. It needs
# 32 MiB for about a tenth of a second per check, which a 512 MB Machine can spare.
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 3
SCRYPT_DKLEN = 32
# OpenSSL refuses to run scrypt above 32 MiB unless it is told how much it may use.
_SCRYPT_MAXMEM = 128 * 1024 * 1024

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 200
MAX_EMAIL_LENGTH = 254
EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
USER_ID_PATTERN = re.compile(r"[0-9a-f]{16}")

# A username: 3 to 24 letters, digits, hyphens and underscores, starting with a letter or digit. It shows
# beside a deck on a public page, so it has to pass the profanity check, and it can't pass for the site.
USERNAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{2,23}")
RESERVED_USERNAMES = frozenset(
    "admin administrator root system support help staff mod moderator official owner anonymous unknown null "
    "undefined everyone nobody mtgdeckdoctor deckdoctor doctor".split()
)

_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class User:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    email: str = ""
    password_hash: str = ""
    # Part of every login cookie. Raising it ends all of the user's sessions.
    session_version: int = 0
    created_at: str = field(default_factory=_now)
    last_login_at: str | None = None
    # What other people see of this user. None until the user picks one, and until then the decks they
    # have made public are shown without a name.
    username: str | None = None


# ---- passwords ---------------------------------------------------------------------------------------


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def hash_password(password: str) -> str:
    """`scrypt$N$r$p$salt$hash`, with a fresh random salt."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_DKLEN, maxmem=_SCRYPT_MAXMEM)
    return "$".join(["scrypt", str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P), _b64(salt), _b64(digest)])


def _parse_hash(stored: str) -> tuple[int, int, int, bytes, bytes] | None:
    parts = stored.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return None
    try:
        n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
        return n, r, p, base64.b64decode(parts[4]), base64.b64decode(parts[5])
    except ValueError:
        return None


def verify_password(password: str, stored: str) -> bool:
    parsed = _parse_hash(stored)
    if parsed is None:
        return False
    n, r, p, salt, expected = parsed
    try:
        digest = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=len(expected), maxmem=_SCRYPT_MAXMEM)
    except ValueError:
        return False
    return hmac.compare_digest(digest, expected)


def needs_rehash(stored: str) -> bool:
    """Whether the hash was made with settings other than the current ones."""
    parsed = _parse_hash(stored)
    return parsed is None or parsed[:3] != (SCRYPT_N, SCRYPT_R, SCRYPT_P) or len(parsed[4]) != SCRYPT_DKLEN


@functools.cache
def dummy_hash() -> str:
    """A hash nobody has the password to. Checking a password against it takes as long as checking one
    against a real account, so sign-in takes the same time for an email that has no account."""
    return hash_password(secrets.token_urlsafe(16))


# ---- what is allowed ---------------------------------------------------------------------------------


def normalize_email(email: str) -> str:
    return email.strip().lower()


def check_email(email: str) -> str | None:
    """Why this can't be an account's email, or None. Expects it already normalized."""
    if len(email) > MAX_EMAIL_LENGTH or not EMAIL_PATTERN.fullmatch(email):
        return "That isn't an email address."
    return None


def check_password(password: str, email: str) -> str | None:
    """Why this can't be the password, or None."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"The password has to be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"The password can't be longer than {MAX_PASSWORD_LENGTH} characters."
    if password.strip().lower() == email:
        return "The password can't be the email address."
    return None


def check_username(username: str) -> str | None:
    """Why this can't be a username, or None. Says nothing about whether someone has it already."""
    if not USERNAME_PATTERN.fullmatch(username):
        return "A username is 3 to 24 characters: letters, numbers, hyphens and underscores."
    if username.lower() in RESERVED_USERNAMES or moderation.is_blocked(username):
        return "That username isn't allowed."
    return None


# ---- the files ---------------------------------------------------------------------------------------


def _path(user_id: str) -> Path:
    return USERS_DIR / f"{user_id}.json"


def _read(path: Path) -> User | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    known = {f.name for f in fields(User)}
    try:
        return User(**{key: value for key, value in data.items() if key in known})
    except TypeError:
        return None


def _write(user: User) -> None:
    USERS_DIR.mkdir(parents=True, exist_ok=True)
    # Write-then-rename, so a reader never sees half a file. Readable by the owner only.
    tmp = _path(user.id).with_suffix(".json.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(asdict(user), indent=2))
    os.replace(tmp, _path(user.id))


def any_users() -> bool:
    return USERS_DIR.exists() and any(USERS_DIR.glob("*.json"))


def list_users() -> list[User]:
    if not USERS_DIR.exists():
        return []
    return [user for user in (_read(p) for p in sorted(USERS_DIR.glob("*.json"))) if user is not None]


def get_user(user_id: str) -> User | None:
    if not USER_ID_PATTERN.fullmatch(user_id):
        return None
    return _read(_path(user_id))


def find_user(email: str) -> User | None:
    email = normalize_email(email)
    return next((user for user in list_users() if user.email == email), None)


def find_by_username(username: str) -> User | None:
    wanted = username.strip().lower()
    return next((user for user in list_users() if user.username and user.username.lower() == wanted), None)


def usernames() -> dict[str, str]:
    """Every user's id and username, for the pages that show who built a deck. Users without a username
    are left out."""
    return {user.id: user.username for user in list_users() if user.username}


def create_user(email: str, password: str, username: str | None = None) -> User:
    """Makes an account. Raises ValueError, with something to show a person, if the email, the password
    or the username won't do, or the email or the username is taken."""
    email = normalize_email(email)
    username = username.strip() if username else None
    problem = check_email(email) or check_password(password, email) or (check_username(username) if username else None)
    if problem:
        raise ValueError(problem)
    with _lock:
        if find_user(email) is not None:
            raise ValueError("There is already an account with that email.")
        if username and find_by_username(username) is not None:
            raise ValueError("That username is taken.")
        user = User(email=email, password_hash=hash_password(password), username=username)
        _write(user)
        return user


def set_username(user: User, username: str) -> User:
    """Gives the user a username, or a new one. Raises ValueError, with something to show a person, if it
    won't do or someone else has it. The same user may change the case of their own."""
    username = username.strip()
    problem = check_username(username)
    if problem:
        raise ValueError(problem)
    with _lock:
        holder = find_by_username(username)
        if holder is not None and holder.id != user.id:
            raise ValueError("That username is taken.")
        current = get_user(user.id) or user
        current.username = username
        _write(current)
        return current


def set_password(user: User, password: str) -> User:
    """A new password, which also signs the user out of every browser."""
    problem = check_password(password, user.email)
    if problem:
        raise ValueError(problem)
    with _lock:
        current = get_user(user.id) or user
        current.password_hash = hash_password(password)
        current.session_version += 1
        _write(current)
        return current


def revoke_sessions(user: User) -> User:
    """Signs the user out of every browser, without changing the password."""
    with _lock:
        current = get_user(user.id) or user
        current.session_version += 1
        _write(current)
        return current


def record_login(user: User, password: str) -> None:
    """Notes the sign-in, and moves the stored hash to the current settings if it was made with older
    ones. `password` is what was just checked."""
    with _lock:
        current = get_user(user.id)
        if current is None:
            return
        current.last_login_at = _now()
        if needs_rehash(current.password_hash):
            current.password_hash = hash_password(password)
        _write(current)
