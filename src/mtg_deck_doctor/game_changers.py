"""The Commander Brackets' Game Changers list, from Scryfall (`is:gamechanger`, the
authoritative source; EDHREC's own flag for them never appears on its commander pages).

The list changes a few times a year, so it is cached on disk for a day. Like
card_cache.py, a failed fetch serves the stale copy instead of failing.
"""

import json
import os
import time
from pathlib import Path

import httpx

from mtg_deck_doctor.card_cache import API_HEADERS, throttle_scryfall

CACHE_PATH = Path("data/game_changers_cache.json")
CACHE_TTL_SECONDS = 24 * 60 * 60


def _fetch() -> list[str]:
    names: list[str] = []
    url, params = "https://api.scryfall.com/cards/search", {"q": "is:gamechanger", "unique": "cards"}
    while url:
        throttle_scryfall()
        response = httpx.get(url, params=params, headers=API_HEADERS, timeout=15)
        response.raise_for_status()
        body = response.json()
        names += [c["name"] for c in body["data"]]
        url, params = body.get("next_page") if body.get("has_more") else None, None
    return names


def game_changer_names() -> set[str] | None:
    """The names of the Game Changers. None if the list couldn't be read and none is cached."""
    entry = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else None
    if entry and time.time() - entry["fetchedAt"] < CACHE_TTL_SECONDS:
        return set(entry["names"])
    try:
        names = _fetch()
    except (httpx.HTTPError, KeyError, ValueError):
        return set(entry["names"]) if entry else None
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"fetchedAt": time.time(), "names": names}))
    os.replace(tmp, CACHE_PATH)
    return set(names)
