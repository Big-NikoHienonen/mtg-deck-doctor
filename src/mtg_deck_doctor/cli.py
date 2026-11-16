"""Account commands, run on the machine that holds the data (see users.py for why there is no sign-up).

    mtg-deck-doctor create-user EMAIL       make an account; the first one takes the decks that have no owner
    mtg-deck-doctor set-password EMAIL      a new password, which signs the user out everywhere
    mtg-deck-doctor revoke-sessions EMAIL   sign the user out everywhere, keeping the password
    mtg-deck-doctor claim-decks EMAIL       give every deck that has no owner to this account
    mtg-deck-doctor list-users

The password is asked for with a prompt that doesn't show it, and never taken from the command line,
where it would stay in the shell's history. `--password-stdin` reads it from standard input instead, for a
script.
"""

import argparse
import getpass
import os
import sys
from pathlib import Path

from mtg_deck_doctor import users
from mtg_deck_doctor.deck import claim_unowned_decks


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\n")
    first = getpass.getpass("Password: ")
    if getpass.getpass("Password again: ") != first:
        raise SystemExit("The two passwords don't match.")
    return first


def _user_or_exit(email: str) -> users.User:
    user = users.find_user(email)
    if user is None:
        raise SystemExit(f"There is no account for {users.normalize_email(email)}.")
    return user


def _create_user(args: argparse.Namespace) -> None:
    first = not users.any_users()
    try:
        user = users.create_user(args.email, _read_password(args.password_stdin))
    except ValueError as err:
        raise SystemExit(str(err))
    print(f"Made the account for {user.email}.")
    if first:
        count = claim_unowned_decks(user.id)
        print("1 existing deck now belongs to it." if count == 1 else f"{count} existing decks now belong to it.")


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
    count = claim_unowned_decks(user.id)
    print(f"{count} deck{'' if count == 1 else 's'} with no owner now belong{'s' if count == 1 else ''} to {user.email}.")


def _list_users(_: argparse.Namespace) -> None:
    accounts = users.list_users()
    if not accounts:
        print("No accounts.")
    for user in accounts:
        print(f"{user.email}  made {user.created_at[:10]}  last signed in {user.last_login_at[:10] if user.last_login_at else 'never'}")


def main(argv: list[str] | None = None) -> None:
    # The data folder is relative to the project, so run from there whatever folder the command was typed in.
    os.chdir(Path(__file__).resolve().parents[2])

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
        command.set_defaults(handler=handler)
    commands.add_parser("list-users", help="list the accounts").set_defaults(handler=_list_users)

    args = parser.parse_args(argv)
    args.handler(args)
