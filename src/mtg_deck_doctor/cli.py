"""Account commands, run on the machine that holds the data (see users.py for why there is no sign-up).

    mtg-deck-doctor create-user EMAIL       make an account (--username NAME); the first one takes the decks that have no owner here
    mtg-deck-doctor set-username EMAIL NAME give an account a username, or a new one
    mtg-deck-doctor set-password EMAIL      a new password, which signs the user out everywhere
    mtg-deck-doctor revoke-sessions EMAIL   sign the user out everywhere, keeping the password
    mtg-deck-doctor claim-decks EMAIL       give every deck that has no owner here to this account
    mtg-deck-doctor list-users

A deck "has no owner here" when it has none, or when its owner is an account that doesn't exist on this
machine, as with decks copied from your own computer to a server.

The password is asked for with a prompt that doesn't show it, and never taken from the command line,
where it would stay in the shell's history. `--password-stdin` reads it from standard input instead, for a
script.

The server runs as an unprivileged user, so the files it reads must belong to that user. Run as root, this
command gives up root first and acts as the owner of the `data` folder, so what it writes is readable by
the server (`fly ssh console` opens a root session unless you pass `-u app`).
"""

import argparse
import getpass
import os
import sys
from pathlib import Path

from mtg_deck_doctor import users
from mtg_deck_doctor.deck import claim_unowned_decks


def privilege_target(euid: int, data_owner: tuple[int, int] | None) -> tuple[int, int] | None:
    """The (user id, group id) to act as, or None to stay as the current user. Root acts as the owner of the
    data folder, unless root owns it, or it isn't there yet."""
    if euid != 0 or data_owner is None or data_owner[0] == 0:
        return None
    return data_owner


def _drop_root() -> None:
    try:
        info = os.stat("data")
    except FileNotFoundError:
        return
    target = privilege_target(os.geteuid(), (info.st_uid, info.st_gid))
    if target is not None:
        uid, gid = target
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\n")
    first = getpass.getpass("Password: ")
    if getpass.getpass("Password again: ") != first:
        raise SystemExit("The two passwords don't match.")
    return first


def _account_ids() -> set[str]:
    return {user.id for user in users.list_users()}


def _user_or_exit(email: str) -> users.User:
    user = users.find_user(email)
    if user is None:
        raise SystemExit(f"There is no account for {users.normalize_email(email)}.")
    return user


def _create_user(args: argparse.Namespace) -> None:
    first = not users.any_users()
    try:
        user = users.create_user(args.email, _read_password(args.password_stdin), args.username)
    except ValueError as err:
        raise SystemExit(str(err))
    print(f"Made the account for {user.email}.")
    if first:
        count = claim_unowned_decks(user.id, _account_ids())
        print("1 existing deck now belongs to it." if count == 1 else f"{count} existing decks now belong to it.")


def _set_username(args: argparse.Namespace) -> None:
    user = _user_or_exit(args.email)
    try:
        user = users.set_username(user, args.username)
    except ValueError as err:
        raise SystemExit(str(err))
    print(f"{user.email} is now {user.username}.")


def _set_password(args: argparse.Namespace) -> None:
    user = _user_or_exit(args.email)
    try:
        users.set_password(user, _read_password(args.password_stdin))
    except ValueError as err:
        raise SystemExit(str(err))
    print(f"Changed the password for {user.email}. It is signed out of every browser.")


def _revoke_sessions(args: argparse.Namespace) -> None:
    user = _user_or_exit(args.email)
    users.revoke_sessions(user)
    print(f"{user.email} is signed out of every browser.")


def _claim_decks(args: argparse.Namespace) -> None:
    user = _user_or_exit(args.email)
    count = claim_unowned_decks(user.id, _account_ids())
    print(f"{count} deck{'' if count == 1 else 's'} with no owner here now belong{'s' if count == 1 else ''} to {user.email}.")


def _list_users(_: argparse.Namespace) -> None:
    accounts = users.list_users()
    if not accounts:
        print("No accounts.")
    for user in accounts:
        print(f"{user.email}  {user.username or '(no username)'}  made {user.created_at[:10]}  last signed in {user.last_login_at[:10] if user.last_login_at else 'never'}")


def main(argv: list[str] | None = None) -> None:
    # The data folder is relative to the project, so run from there whatever folder the command was typed in.
    os.chdir(Path(__file__).resolve().parents[2])
    _drop_root()

    parser = argparse.ArgumentParser(prog="mtg-deck-doctor", description="Manage the accounts of an MTG Deck Doctor server.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, handler, help_text in [
        ("create-user", _create_user, "make an account"),
        ("set-password", _set_password, "set a new password"),
        ("revoke-sessions", _revoke_sessions, "sign a user out of every browser"),
        ("claim-decks", _claim_decks, "give the decks that have no owner to an account"),
    ]:
        command = commands.add_parser(name, help=help_text)
        command.add_argument("email")
        if name in ("create-user", "set-password"):
            command.add_argument("--password-stdin", action="store_true", help="read the password from standard input")
        if name == "create-user":
            command.add_argument("--username", help="what other people see of this user, on the decks they make public")
        command.set_defaults(handler=handler)
    set_username = commands.add_parser("set-username", help="give an account a username, or a new one")
    set_username.add_argument("email")
    set_username.add_argument("username")
    set_username.set_defaults(handler=_set_username)
    commands.add_parser("list-users", help="list the accounts").set_defaults(handler=_list_users)

    args = parser.parse_args(argv)
    args.handler(args)
