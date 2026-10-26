"""Cards from the most recently released sets, for a given commander's colors.

Scryfall has them the day they're released; EDHREC takes weeks to start
counting them in decks. So there is no popularity to rank them by — which is
the point of handing the pool to the model to judge instead.

Like the other caches here: a fresh entry wins, a failed fetch serves a stale
one, and the file is written whole via a temp file so a reader never sees half
of it.
"""

import datetime
import json
import os
import threading
import time
from pathlib import Path

import httpx

from mtg_deck_doctor.card_cache import API_HEADERS, throttle_scryfall

CACHE_PATH = Path("data/new_cards_cache.json")
CACHE_TTL_SECONDS = 24 * 60 * 60

# Set types that hold cards a player would think of as "the new set". Tokens,
# promos, memorabilia and the like are left out.
_PLAYABLE_SET_TYPES = {"expansion", "core", "commander", "draft_innovation", "masters", "eternal"}
# Enough for the five-colour commanders, whose pool is nearly all of two releases.
_MAX_POOL = 600

_lock = threading.Lock()


def _load() -> dict:
    return json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}


def _store(key: str, data: dict) -> None:
    with _lock:
        cache = _load()
        cache[key] = {"fetchedAt": time.time(), "data": data}
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cache))
        os.replace(tmp, CACHE_PATH)


def _cached(key: str, ttl: float, fetch):
    entry = _load().get(key)
    if entry and time.time() - entry["fetchedAt"] < ttl:
        return entry["data"]
    try:
        data = fetch()
    except (httpx.HTTPError, KeyError):
        return entry["data"] if entry else None
    _store(key, data)
    return data


def _get(url: str, params: dict | None = None) -> httpx.Response:
    throttle_scryfall()
    return httpx.get(url, params=params, headers=API_HEADERS, timeout=20)


# Under this key since the answer became the newest releases, not just the newest.
_SETS_KEY = "latest-releases-v2"

# Which set names a release, by type: the main set, not its Commander set or an
# "Eternal" companion.
_TITLE_ORDER = {"expansion": 0, "core": 0, "draft_innovation": 1, "masters": 1, "eternal": 2, "commander": 3}

# How many releases the Doctor looks through: the newest two that have new
# cards — a set's cards stay new for a while after the next one comes out.
_RELEASES = 2

# How many release dates, newest first, are checked for new cards before giving
# up on finding more.
_MAX_DATES_CHECKED = 8


def peek_latest_sets() -> dict | None:
    """The same as latest_sets, from the cache only, however old."""
    entry = _load().get(_SETS_KEY)
    return entry["data"] if entry else None


def _has_new_cards(codes: list[str]) -> bool:
    """Whether any of these sets has a card that is new — not a reprint — and
    legal in Commander. Some releases are all reprints (Mystery Booster, say)."""
    response = _get(
        "https://api.scryfall.com/cards/search",
        {"q": f"({' or '.join(f'set:{c}' for c in codes)}) -is:reprint legal:commander", "unique": "cards"},
    )
    if response.status_code == 404:  # nothing matches
        return False
    response.raise_for_status()
    return response.json().get("total_cards", 0) > 0


def latest_sets() -> dict | None:
    """The newest two releases up to today that have new cards in them (a main
    set and its Commander set come out together, and count as one release), as
    {"released_at" (the newest), "sets" (all of them, [{"code", "name"}]),
    "releases" (each one, newest first, {"released_at", "title" (its main
    set's name), "sets"})}. A release of
    nothing but reprints doesn't count — it would take the place of one worth
    looking through. None if Scryfall couldn't be reached and nothing is
    cached."""

    def fetch() -> dict:
        response = _get("https://api.scryfall.com/sets")
        response.raise_for_status()
        today = datetime.date.today().isoformat()
        released = [
            s
            for s in response.json()["data"]
            if s.get("released_at") and s["released_at"] <= today and s["set_type"] in _PLAYABLE_SET_TYPES
        ]
        dates = sorted({s["released_at"] for s in released}, reverse=True)

        def group(date: str) -> dict:
            members = sorted((s for s in released if s["released_at"] == date), key=lambda s: _TITLE_ORDER.get(s["set_type"], 4))
            return {
                "released_at": date,
                "title": members[0]["name"],
                "sets": [{"code": s["code"], "name": s["name"]} for s in members],
            }

        releases: list[dict] = []
        for date in dates[:_MAX_DATES_CHECKED]:
            candidate = group(date)
            if _has_new_cards([s["code"] for s in candidate["sets"]]):
                releases.append(candidate)
                if len(releases) == _RELEASES:
                    break
        releases = releases or [group(dates[0])]
        return {
            "released_at": releases[0]["released_at"],
            "sets": [s for r in releases for s in r["sets"]],
            "releases": releases,
        }

    return _cached(_SETS_KEY, CACHE_TTL_SECONDS, fetch)


def _compact(card: dict) -> dict:
    faces = card.get("card_faces") or []
    oracle = card.get("oracle_text") or "\n//\n".join(f.get("oracle_text", "") for f in faces if f.get("oracle_text"))
    return {
        "id": card["id"],
        "name": card["name"],
        "manaCost": card.get("mana_cost") or (faces[0].get("mana_cost") if faces else None),
        "cmc": card.get("cmc"),
        "typeLine": card.get("type_line") or (faces[0].get("type_line") if faces else ""),
        "oracleText": oracle,
        "rarity": card.get("rarity"),
        "set": card.get("set"),
        "priceUsd": (card.get("prices") or {}).get("usd"),
        "colorIdentity": card.get("color_identity", []),
    }


def new_card_pool(set_codes: list[str], color_identity: list[str]) -> list[dict] | None:
    """Every card from `set_codes` that is new (not a reprint), legal in
    Commander and inside `color_identity`, as compact dicts. None if it
    couldn't be fetched and nothing is cached."""
    identity = "".join(color_identity) or "c"
    query = f"({' or '.join(f'set:{c}' for c in set_codes)}) id<={identity} legal:commander -is:reprint -t:basic"

    def fetch() -> list[dict]:
        cards: list[dict] = []
        response = _get("https://api.scryfall.com/cards/search", {"q": query, "unique": "cards", "order": "released"})
        while True:
            if response.status_code == 404:  # nothing matches
                return cards
            response.raise_for_status()
            body = response.json()
            cards.extend(_compact(c) for c in body["data"])
            if not body.get("has_more") or len(cards) >= _MAX_POOL:
                return cards[:_MAX_POOL]
            response = _get(body["next_page"])

    return _cached(f"pool:{'+'.join(sorted(set_codes))}:{identity}", CACHE_TTL_SECONDS, fetch)


def new_commander_pool(set_codes: list[str]) -> list[dict] | None:
    """Every new (not reprinted) card from `set_codes` that can be a commander
    and is legal as one, in any colours. None if it couldn't be fetched and
    nothing is cached."""
    query = f"({' or '.join(f'set:{c}' for c in set_codes)}) is:commander legal:commander -is:reprint"

    def fetch() -> list[dict]:
        cards: list[dict] = []
        response = _get("https://api.scryfall.com/cards/search", {"q": query, "unique": "cards", "order": "released"})
        while True:
            if response.status_code == 404:
                return cards
            response.raise_for_status()
            body = response.json()
            cards.extend(_compact(c) for c in body["data"])
            if not body.get("has_more") or len(cards) >= _MAX_POOL:
                return cards[:_MAX_POOL]
            response = _get(body["next_page"])

    return _cached(f"commanders:{'+'.join(sorted(set_codes))}", CACHE_TTL_SECONDS, fetch)


# The Doctor's picks of new commanders for this player. One result for the
# whole collection of decks, not one per deck, so it lives in a file of its own.
COMMANDERS_PATH = Path("data/new_commanders.json")


def load_new_commanders() -> dict | None:
    return json.loads(COMMANDERS_PATH.read_text()) if COMMANDERS_PATH.exists() else None


def save_new_commanders(data: dict) -> None:
    COMMANDERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = COMMANDERS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, COMMANDERS_PATH)
