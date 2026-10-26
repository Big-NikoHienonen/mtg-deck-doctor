"""Cached rulings and printings — the two per-card Scryfall lookups the
frontend used to make straight from the browser, once per modal/picker open.

Both are slow-moving data (rulings are rare additions; the printings list
only changes with a set release, and prices once a day — Scryfall's own
docs say fetching prices more often than every 24 hours yields nothing
new), so there's no reason to ask the API twice. Moving them here also puts
them behind card_cache's shared throttle, which matters now that arrowing
through cards in the modal fires one rulings lookup per card.

Like card_cache.py and edhrec.py: a failed fetch falls back to a stale
entry rather than erroring, and "nothing to show" is kept distinct from
"couldn't find out" — a rate-limited lookup used to render as "No rulings
for this card", which is a lie.
"""

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from mtg_deck_doctor.card_cache import API_HEADERS, throttle_scryfall

RULINGS_PATH = Path("data/rulings_cache.json")
PRINTINGS_PATH = Path("data/printings_cache.json")
RULINGS_TTL_SECONDS = 7 * 24 * 60 * 60
PRINTINGS_TTL_SECONDS = 24 * 60 * 60


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _save(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache))


def _cached(path: Path, key: str, ttl: float, fetch: Callable[[], Any]) -> Any | None:
    """Fresh cache wins; otherwise fetch. A failed fetch (rate limit,
    network) returns whatever stale entry exists, or None if there's
    nothing at all — None means "couldn't find out", never "empty": an
    empty list is a real answer and is cached like any other."""
    cache = _load(path)
    entry = cache.get(key)
    if entry and time.time() - entry["fetchedAt"] < ttl:
        return entry["data"]
    try:
        data = fetch()
    except httpx.HTTPError:
        return entry["data"] if entry else None
    cache[key] = {"fetchedAt": time.time(), "data": data}
    _save(path, cache)
    return data


def _get(url: str, params: dict | None = None) -> httpx.Response:
    throttle_scryfall()
    return httpx.get(url, params=params, headers=API_HEADERS, timeout=15)


def get_rulings(card_id: str) -> list[dict] | None:
    def fetch() -> list[dict]:
        response = _get(f"https://api.scryfall.com/cards/{card_id}/rulings")
        response.raise_for_status()
        return [
            {"source": r.get("source"), "publishedAt": r.get("published_at"), "comment": r.get("comment")}
            for r in response.json().get("data", [])
        ]

    return _cached(RULINGS_PATH, card_id, RULINGS_TTL_SECONDS, fetch)


def get_printings(name: str) -> list[dict] | None:
    """Every printing of a card by exact name, newest first. Only the first
    results page (175, Scryfall's own page size) — plenty for virtually any
    card; only extreme outliers like heavily-reprinted basics have more, and
    the newest 175 is a reasonable cap for a picker."""

    def fetch() -> list[dict]:
        response = _get(
            "https://api.scryfall.com/cards/search",
            {"q": f'!"{name}"', "unique": "prints", "order": "released", "dir": "desc"},
        )
        if response.status_code == 404:
            return []
        response.raise_for_status()
        return [
            {
                "id": c["id"],
                "setName": c.get("set_name"),
                "releasedAt": c.get("released_at"),
                "priceUsd": (c.get("prices") or {}).get("usd"),
            }
            for c in response.json().get("data", [])
        ]

    return _cached(PRINTINGS_PATH, name, PRINTINGS_TTL_SECONDS, fetch)
