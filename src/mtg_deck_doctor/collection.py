"""The user's owned-card collection.

Tracked by card name only, no quantity or printing — Commander decks are
singleton except basic lands, so knowing whether a card is owned at all is
enough to tell whether a deck still needs to buy it. One JSON file, same
pattern as deck.py, standing in for a real database for now.
"""

import json
from pathlib import Path

COLLECTION_PATH = Path("data/collection.json")


def load_collection() -> list[str]:
    if not COLLECTION_PATH.exists():
        return []
    return json.loads(COLLECTION_PATH.read_text())


def _save(cards: list[str]) -> None:
    COLLECTION_PATH.parent.mkdir(parents=True, exist_ok=True)
    COLLECTION_PATH.write_text(json.dumps(sorted(cards), indent=2))


def add_to_collection(name: str) -> list[str]:
    cards = load_collection()
    if name not in cards:
        cards.append(name)
        _save(cards)
    return sorted(cards)


def add_many_to_collection(names: list[str]) -> list[str]:
    cards = load_collection()
    new_names = [name for name in dict.fromkeys(names) if name not in cards]
    if new_names:
        _save(cards + new_names)
    return sorted(cards + new_names)


def remove_from_collection(name: str) -> list[str]:
    cards = [c for c in load_collection() if c != name]
    _save(cards)
    return cards
