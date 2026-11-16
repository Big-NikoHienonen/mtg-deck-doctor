"""Tests for accounts: the password hash, what an email and a password must look like, the files, and
the command-line tool that makes accounts. No network and no model. Run with

    uv run python tests/test_users.py
"""

import getpass
import io
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

import mtg_deck_doctor.deck as D
from mtg_deck_doctor import cli, users

tmp = Path(tempfile.mkdtemp())
users.USERS_DIR = tmp / "users"
D.DECKS_DIR = tmp / "decks"
results: list[bool] = []


def check(name: str, ok: object, detail: str = "") -> None:
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def exits_with(*argv: str, password: str | None = None, stdin: str | None = None) -> str | None:
    """Runs the command; the message it stopped with, or None if it finished."""
    real = (getpass.getpass, sys.stdin)
    if password is not None:
        getpass.getpass = lambda prompt="": password
    if stdin is not None:
        sys.stdin = io.StringIO(stdin)
    try:
        cli.main(list(argv))
        return None
    except SystemExit as stop:
        return str(stop.code)
    finally:
        getpass.getpass, sys.stdin = real


start = os.getcwd()
getpass.getpass = lambda prompt="": (_ for _ in ()).throw(AssertionError("a test asked for a password it wasn't given"))

# --- the hash ---------------------------------------------------------------------------------------

stored = users.hash_password("a long enough password")
check("a hash says how it was made", stored.startswith(f"scrypt${users.SCRYPT_N}${users.SCRYPT_R}${users.SCRYPT_P}$"), stored[:40])
check("...and doesn't contain the password", "a long enough password" not in stored)
check("the right password checks out", users.verify_password("a long enough password", stored))
check("a wrong one doesn't", not users.verify_password("a long enough passworD", stored) and not users.verify_password("", stored))
check("the same password hashes differently each time (a fresh salt)", users.hash_password("a long enough password") != stored)
check("junk in place of a hash never checks out", not any(users.verify_password("x", junk) for junk in ["", "x", "scrypt$1$2", "scrypt$a$b$c$d$e", "bcrypt$1$2$3$4$5", "scrypt$99999999999$8$3$AAAA$AAAA"]))
check("a hash made with the current settings is current", not users.needs_rehash(stored))
old = users.SCRYPT_N
users.SCRYPT_N = 2**12
weak = users.hash_password("a long enough password")
users.SCRYPT_N = old
check("...and one made with other settings is not, but still works", users.needs_rehash(weak) and users.verify_password("a long enough password", weak))
check("the dummy hash is a real hash nobody has the password to", users.verify_password("anything", users.dummy_hash()) is False and users.dummy_hash() == users.dummy_hash())

# --- what is allowed --------------------------------------------------------------------------------------

check("emails are lowercased and trimmed", users.normalize_email("  Niko@Example.COM ") == "niko@example.com")
check("a plain email passes", users.check_email("niko@example.com") is None)
check("things that aren't emails don't", all(users.check_email(e) for e in ["", "niko", "niko@", "@example.com", "a b@example.com", "niko@example", "a@b.c" + "x" * 300]))
check("a password of ten characters passes", users.check_password("0123456789", "niko@example.com") is None)
check("a short one doesn't", users.check_password("123456789", "niko@example.com") is not None)
check("one that is too long doesn't", users.check_password("x" * 201, "niko@example.com") is not None)
check("the email isn't a password", users.check_password("niko@example.com", "niko@example.com") is not None)

# --- the files ---------------------------------------------------------------------------------------------

check("with no folder there are no users", not users.any_users() and users.list_users() == [] and users.find_user("niko@example.com") is None)
niko = users.create_user("  Niko@Example.com ", "a long enough password")
check("making an account stores it under the email, normalized", niko.email == "niko@example.com" and users.any_users() and users.find_user("NIKO@example.com").id == niko.id)
check("...with a hash and not the password", "a long enough password" not in (users.USERS_DIR / f"{niko.id}.json").read_text() and users.verify_password("a long enough password", niko.password_hash))
mode = stat.S_IMODE((users.USERS_DIR / f"{niko.id}.json").stat().st_mode)
check("...in a file only its owner can read", mode == 0o600, oct(mode))
check("an id is sixteen hex characters", len(niko.id) == 16 and all(c in "0123456789abcdef" for c in niko.id))
for args, why in [(("niko@example.com", "another long password"), "the same email"), (("NIKO@EXAMPLE.COM", "another long password"), "the same email in capitals"), (("nope", "a long enough password"), "a bad email"), (("a@example.com", "short"), "a short password")]:
    try:
        users.create_user(*args)
        check(f"{why} is refused", False)
    except ValueError as err:
        check(f"{why} is refused", True, str(err))
check("...and nothing was left behind by them", len(users.list_users()) == 1)
check("an id that isn't one finds nothing", all(users.get_user(i) is None for i in ["", "../x", niko.id.upper(), niko.id + "0", "x" * 16]))
(users.USERS_DIR / "garbage.json").write_text("{ not json")
(users.USERS_DIR / "wrongshape.json").write_text(json.dumps(["a list"]))
check("a file that can't be read is skipped", [u.id for u in users.list_users()] == [niko.id])
(users.USERS_DIR / "garbage.json").unlink()
(users.USERS_DIR / "wrongshape.json").unlink()

before = niko.session_version
changed = users.set_password(niko, "a different long password")
check("a new password works, the old one doesn't", users.verify_password("a different long password", users.find_user("niko@example.com").password_hash) and not users.verify_password("a long enough password", users.find_user("niko@example.com").password_hash))
check("...and ends every session", changed.session_version == before + 1 == users.find_user("niko@example.com").session_version)
check("revoking ends every session without a new password", users.revoke_sessions(changed).session_version == before + 2 and users.verify_password("a different long password", users.find_user("niko@example.com").password_hash))
try:
    users.set_password(niko, "short")
    check("a bad new password is refused", False)
except ValueError:
    check("a bad new password is refused", True)

users.SCRYPT_N = 2**12
weak_user = users.create_user("weak@example.com", "a long enough password")
users.SCRYPT_N = old
users.record_login(weak_user, "a long enough password")
saved = users.find_user("weak@example.com")
check("signing in notes the time", saved.last_login_at is not None)
check("...and upgrades a hash made with older settings", not users.needs_rehash(saved.password_hash) and users.verify_password("a long enough password", saved.password_hash))

# --- the command-line tool ---------------------------------------------------------------------------------

import shutil

shutil.rmtree(users.USERS_DIR)
D.DECKS_DIR.mkdir(parents=True)
(D.DECKS_DIR / "aaaa1111.json").write_text(json.dumps({"id": "aaaa1111", "name": "Mine", "cards": [], "version": 3, "updated_at": "2026-01-01T00:00:00+00:00"}))
(D.DECKS_DIR / "bbbb2222.json").write_text(json.dumps({"id": "bbbb2222", "name": "Taken", "cards": [], "owner_id": "someoneelse00000", "version": 1, "updated_at": "2026-01-02T00:00:00+00:00"}))

answers = iter(["a long enough password", "a different one entirely"])
getpass.getpass = lambda prompt="": next(answers)
try:
    cli.main(["create-user", "a@example.com"])
    mismatch = None
except SystemExit as stop:
    mismatch = str(stop.code)
getpass.getpass = lambda prompt="": ""
check("...and no account is made", mismatch == "The two passwords don't match." and not users.any_users(), str(mismatch))

check("the first account is made", exits_with("create-user", "Niko@Example.com", password="a long enough password") is None and users.find_user("niko@example.com") is not None)
first = users.find_user("niko@example.com")
claimed = json.loads((D.DECKS_DIR / "aaaa1111.json").read_text())
check("...and takes the decks nobody owned", claimed["owner_id"] == first.id)
check("...without changing when they were updated, and moving the version on", claimed["updated_at"] == "2026-01-01T00:00:00+00:00" and claimed["version"] == 4, str(claimed))
check("...and leaves a deck someone owns alone", json.loads((D.DECKS_DIR / "bbbb2222.json").read_text())["owner_id"] == "someoneelse00000")

(D.DECKS_DIR / "cccc3333.json").write_text(json.dumps({"id": "cccc3333", "cards": [], "version": 0}))
check("a second account is made", exits_with("create-user", "two@example.com", password="another long password") is None and len(users.list_users()) == 2)
check("...and doesn't take decks", "owner_id" not in json.loads((D.DECKS_DIR / "cccc3333.json").read_text()) or not json.loads((D.DECKS_DIR / "cccc3333.json").read_text()).get("owner_id"))

check("claim-decks gives the decks nobody owns to the account named", exits_with("claim-decks", "two@example.com") is None and json.loads((D.DECKS_DIR / "cccc3333.json").read_text())["owner_id"] == users.find_user("two@example.com").id)
check("...and says so for nobody", "no account" in (exits_with("claim-decks", "nobody@example.com") or "").lower())

check("a duplicate email is refused with a reason", "already an account" in (exits_with("create-user", "NIKO@example.com", password="another long password") or ""))
check("a short password is refused with a reason", "at least" in (exits_with("create-user", "three@example.com", password="short") or ""))
check("a bad email is refused with a reason", "email" in (exits_with("create-user", "nonsense", password="a long enough password") or ""))
check("the password can come from standard input", exits_with("create-user", "stdin@example.com", "--password-stdin", stdin="a long enough password\n") is None and users.verify_password("a long enough password", users.find_user("stdin@example.com").password_hash))

version = users.find_user("niko@example.com").session_version
check("set-password changes it, and signs out", exits_with("set-password", "niko@example.com", password="a brand new password") is None and users.verify_password("a brand new password", users.find_user("niko@example.com").password_hash) and users.find_user("niko@example.com").session_version == version + 1)
check("set-password for nobody says so", "no account" in (exits_with("set-password", "nobody@example.com", password="a brand new password") or "").lower())
check("revoke-sessions signs out and keeps the password", exits_with("revoke-sessions", "niko@example.com") is None and users.find_user("niko@example.com").session_version == version + 2 and users.verify_password("a brand new password", users.find_user("niko@example.com").password_hash))

out = io.StringIO()
real_stdout, sys.stdout = sys.stdout, out
os.chdir(tempfile.gettempdir())
exits_with("list-users")
sys.stdout = real_stdout
check("list-users shows each account, and never a hash", "niko@example.com" in out.getvalue() and "two@example.com" in out.getvalue() and "scrypt" not in out.getvalue(), out.getvalue())
check("the tool works from any folder, since it moves to the project's own", Path(os.getcwd()).resolve() == Path(start).resolve() and (Path(os.getcwd()) / "pyproject.toml").exists())
os.chdir(start)

print(f"\n{sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
