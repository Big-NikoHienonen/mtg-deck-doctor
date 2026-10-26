"""Persistent Commander deck state.

This is the object the model edits through tools instead of regenerating
as prose each turn. One JSON file per deck stands in for a real database
for now — the conversation history lives on the deck too, so reopening a
deck resumes the actual discussion, not just the card list.
"""

import hashlib
import json
import os
import random
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any

DECKS_DIR = Path("data/decks")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Deck:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str | None = None
    commander: str | None = None
    commander_color_identity: list[str] = field(default_factory=list)
    cards: list[str] = field(default_factory=list)
    # Cards the owner has marked as keepers — never offered as cut
    # candidates. Names, not counts: it's about the card, not copies.
    keep: list[str] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)
    updated_at: str = field(default_factory=_now)
    # Counts saves. save_deck only writes over the version it was loaded at,
    # so a copy that's gone stale can't silently overwrite newer changes.
    # Files saved before this field existed read as version 0.
    version: int = 0


def _path(deck_id: str) -> Path:
    return DECKS_DIR / f"{deck_id}.json"


def create_deck() -> Deck:
    deck = Deck()
    save_deck(deck)
    return deck


def load_deck(deck_id: str) -> Deck | None:
    path = _path(deck_id)
    if not path.exists():
        return None
    return Deck(**json.loads(path.read_text()))


def list_decks() -> list[Deck]:
    if not DECKS_DIR.exists():
        return []
    return [Deck(**json.loads(p.read_text())) for p in sorted(DECKS_DIR.glob("*.json"))]


class DeckConflictError(Exception):
    """A save was refused because the deck on disk is not the version the
    caller loaded — someone else saved it in between, or deleted it."""


# Held only for the compare-and-write inside save_deck, never across a slow
# call. Covers threads in this process (FastAPI runs sync endpoints on a
# thread pool), which is all there is: one uvicorn worker.
_save_lock = threading.Lock()


def _stored_version(deck_id: str) -> int | None:
    """The version on disk, or None if there's no such deck."""
    path = _path(deck_id)
    if not path.exists():
        return None
    return json.loads(path.read_text()).get("version", 0)


def save_deck(deck: Deck) -> None:
    """Writes `deck`, but only if the file on disk is still the version the
    deck was loaded at; otherwise raises DeckConflictError and writes
    nothing. Without that, a copy held across a slow call — a chat turn
    spends many seconds on the model — would overwrite whatever was saved
    meanwhile. Most callers don't handle the error themselves: they're
    wrapped in `retry_on_conflict`."""
    with _save_lock:
        stored = _stored_version(deck.id)
        if stored is None and deck.version > 0:
            raise DeckConflictError("This deck was deleted.")
        if stored is not None and stored != deck.version:
            raise DeckConflictError(f"Deck {deck.id} changed since it was loaded (version {deck.version}, now {stored}).")
        data = asdict(deck)
        data["version"] = deck.version + 1
        data["updated_at"] = _now()
        DECKS_DIR.mkdir(parents=True, exist_ok=True)
        # Write-then-rename, so a reader never sees half a file.
        tmp = _path(deck.id).with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, _path(deck.id))
        deck.version = data["version"]
        deck.updated_at = data["updated_at"]


def refresh_deck(deck: Deck) -> None:
    """Reloads `deck` from disk in place, so everything holding a reference
    to it sees the current state."""
    fresh = load_deck(deck.id)
    if fresh is None:
        raise DeckConflictError("This deck was deleted.")
    for f in fields(Deck):
        setattr(deck, f.name, getattr(fresh, f.name))


def refresh_if_stale(deck: Deck) -> None:
    stored = _stored_version(deck.id)
    if stored is None:
        # A deck that was never saved has version 0; one that was and is
        # now gone was deleted.
        if deck.version > 0:
            raise DeckConflictError("This deck was deleted.")
    elif stored != deck.version:
        refresh_deck(deck)


MAX_SAVE_ATTEMPTS = 8


def retry_on_conflict(edit: Callable[..., Any]) -> Callable[..., Any]:
    """For a function `edit(deck, ...)` that validates, changes `deck`, and
    saves it. Brings the deck up to date before each attempt, so the
    validation runs against what's on disk, and if a save is still beaten by
    someone else's, refreshes and runs the whole edit again — the two
    changes are both kept, and nothing is rejected. Gives up with
    DeckConflictError only if the deck keeps changing, or was deleted.

    Wrap each single edit, not a loop of them: every attempt starts from the
    top, so a wrapped function that saves more than once would redo the
    saves that had already gone through."""

    @wraps(edit)
    def wrapper(deck: Deck, *args: Any, **kwargs: Any) -> Any:
        for attempt in range(MAX_SAVE_ATTEMPTS):
            refresh_if_stale(deck)
            try:
                return edit(deck, *args, **kwargs)
            except DeckConflictError:
                # A short random pause, growing with each loss, so edits
                # that keep colliding stop doing it in lockstep.
                time.sleep(random.uniform(0, 0.02 * (attempt + 1)))
        raise DeckConflictError("The deck kept changing while this edit was being made. Try again.")

    return wrapper


def duplicate_deck(deck_id: str) -> Deck | None:
    original = load_deck(deck_id)
    if original is None:
        return None
    # Fresh id (the dataclass default) and no messages — a duplicate is a
    # new deck to iterate on, not a shared conversation with the original.
    # The name always gets a "(copy)" suffix so the hub's deck list can
    # tell the two apart at a glance, even when the original had no custom
    # name and would otherwise just be its commander's name again.
    copy = Deck(
        name=f"{original.name or original.commander or 'Untitled deck'} (copy)",
        commander=original.commander,
        commander_color_identity=list(original.commander_color_identity),
        cards=list(original.cards),
        keep=list(original.keep),
    )
    save_deck(copy)
    return copy


def delete_deck(deck_id: str) -> bool:
    path = _path(deck_id)
    if not path.exists():
        return False
    path.unlink()
    for kind in AI_RESULT_DIRS:
        _ai_result_path(kind, deck_id).unlink(missing_ok=True)
    return True


# AI-written results (card suggestions, cut suggestions) live in their own
# per-deck files, not on the Deck itself: generating them takes ~10s of LLM
# calls, and a load → wait → save of the whole deck around that would
# silently overwrite any edit made in the meantime (the exact lost-update
# race this codebase already has to live with elsewhere — no reason to add a
# new way to hit it). One directory per kind of result.
AI_RESULT_DIRS = {
    "suggestions": Path("data/suggestions"),
    "cuts": Path("data/cuts"),
    "discoveries": Path("data/discoveries"),
}


def _ai_result_path(kind: str, deck_id: str) -> Path:
    return AI_RESULT_DIRS[kind] / f"{deck_id}.json"


def deck_fingerprint(deck: Deck) -> str:
    """Identifies a deck's card contents, so a stored AI result can say
    whether the deck has changed since it was generated."""
    raw = json.dumps([deck.commander, sorted(deck.cards)])
    return hashlib.sha1(raw.encode()).hexdigest()


def load_ai_result(kind: str, deck_id: str) -> dict | None:
    path = _ai_result_path(kind, deck_id)
    if not path.exists():
        return None
    stored = json.loads(path.read_text())
    # Suggestions were first stored under "recommendations", before there
    # was more than one kind of result.
    if "recommendations" in stored:
        stored["items"] = stored.pop("recommendations")
    return stored


def save_ai_result(kind: str, deck: Deck, items: list[dict], **extra) -> dict:
    """`extra` is stored beside the items — whatever the result needs in order
    to say, later, what it was written for (e.g. which sets a discovery covers)."""
    stored = {
        "generated_at": _now(),
        "fingerprint": deck_fingerprint(deck),
        "items": items,
        **extra,
    }
    path = _ai_result_path(kind, deck.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stored, indent=2))
    return stored


@retry_on_conflict
def rename_deck(deck: Deck, name: str) -> Deck:
    deck.name = name.strip() or None
    save_deck(deck)
    return deck


@retry_on_conflict
def save_messages(deck: Deck, messages: list[dict]) -> None:
    """Writes only the conversation. Everything else on the deck is whatever
    is on disk now, not whatever it was when the turn began."""
    deck.messages = messages
    save_deck(deck)


@retry_on_conflict
def keep_card(deck: Deck, name: str) -> dict:
    if name not in deck.cards:
        return {"error": f"{name!r} is not in the deck"}
    if name not in deck.keep:
        deck.keep.append(name)
        save_deck(deck)
    return {"keep": deck.keep}


@retry_on_conflict
def unkeep_card(deck: Deck, name: str) -> dict:
    if name in deck.keep:
        deck.keep.remove(name)
        save_deck(deck)
    return {"keep": deck.keep}
