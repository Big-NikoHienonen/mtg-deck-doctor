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


PRINTINGS_CACHE_VERSION = 4 # Bump when a printing gains a field or the list's coverage changes, so older cached lists aren't served.

# Scryfall's `promo_types` values worth naming. Others are left out of the label list.
_PROMO_LABELS = {
    "prerelease": "Prerelease",
    "bundle": "Bundle",
    "buyabox": "Buy-a-box",
    "serialized": "Serialized",
    "surgefoil": "Surge foil",
    "galaxyfoil": "Galaxy foil",
    "textured": "Textured",
}


def _foil_price(card: dict) -> str | None:
    """What the foil copy sells for. Scryfall prices etched foils separately
    (`usd_etched`); a printing that only comes etched has no `usd_foil`, so
    that stands in for it."""
    prices = card.get("prices") or {}
    return prices.get("usd_foil") or prices.get("usd_etched")


def _treatments(card: dict) -> list[str]:
    """The ways a printing looks or is sold differently from the plain one:
    "Borderless", "Showcase", "Foil only" and so on. These are what you tell
    two printings in the same set apart by, and what the picker's search
    matches on."""
    labels = []
    if card.get("border_color") == "borderless":
        labels.append("Borderless")
    effects = card.get("frame_effects") or []
    if "showcase" in effects:
        labels.append("Showcase")
    if "extendedart" in effects:
        labels.append("Extended art")
    if card.get("full_art"):
        labels.append("Full art")
    if card.get("promo"):
        labels.append("Promo")
    labels += [_PROMO_LABELS[p] for p in card.get("promo_types") or [] if p in _PROMO_LABELS]
    finishes = card.get("finishes") or []
    if finishes == ["foil"]:
        labels.append("Foil only")
    elif finishes == ["etched"]:
        labels.append("Etched only")
    return labels


MAX_PRINTING_PAGES = 20  # 175 printings a page; a safety stop, since Forest has about 900 (6 pages).


def get_printings(name: str) -> list[dict] | None:
    """Every printing of a card by exact name, newest first. Follows all of
    Scryfall's results pages (175 each): a basic land has hundreds of
    printings, and stopping at the first page left out everything older than
    a few years. A page that fails fails the whole lookup, so a cut-short
    list is never cached as if it were complete."""

    def fetch() -> list[dict]:
        url, params = "https://api.scryfall.com/cards/search", {"q": f'!"{name}"', "unique": "prints", "order": "released", "dir": "desc"}
        printings: list[dict] = []
        for _ in range(MAX_PRINTING_PAGES):
            response = _get(url, params)
            if response.status_code == 404:
                return printings  # No match at all: []. Never reached on a later page.
            response.raise_for_status()
            body = response.json()
            printings += [
                {
                    "id": c["id"],
                    "setName": c.get("set_name"),
                    "set": c.get("set"),
                    "collectorNumber": c.get("collector_number"),
                    "releasedAt": c.get("released_at"),
                    "priceUsd": (c.get("prices") or {}).get("usd"),
                    "priceUsdFoil": _foil_price(c),
                    "finishes": c.get("finishes") or [],
                    "treatments": _treatments(c),
                }
                for c in body.get("data", [])
            ]
            if not body.get("has_more") or not body.get("next_page"):
                break
            url, params = body["next_page"], None  # next_page is a full URL, query included.
        return printings

    return _cached(PRINTINGS_PATH, f"v{PRINTINGS_CACHE_VERSION}:{name}", PRINTINGS_TTL_SECONDS, fetch)
