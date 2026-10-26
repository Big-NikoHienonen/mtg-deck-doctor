"""Server-side cache of Scryfall card lookups.

A card's type line, oracle text, legality, and color identity essentially
never change, and its price moves slowly — there's no reason to re-fetch
the same card from Scryfall every time something needs its data. One JSON
file cache keyed by exact card name, same pattern as deck.py/collection.py.

Two kinds of callers share this: the frontend's own display needs (price/
type/legality for the ledger and card modal — see api.py's /cards
endpoints), and tool_loop.py's lookup_card, which needs the same data
(plus color_identity) to validate a card before adding it to a deck.
lookup_card used to hit Scryfall directly and uncached, which both missed
out on this cache's benefit and — worse — had no error handling at all:
a single 429 partway through a bulk add (e.g. importing a pasted
decklist) crashed the whole request with a 500 instead of just failing
that one card. Routing it through here fixes both at once.
"""

import json
import os
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

CACHE_PATH = Path("data/card_cache.json")

# Confirmed via Scryfall's own docs (scryfall.com/docs/api/rate-limits),
# not guessed: /cards/named has a *hard* limit of 2 requests/second
# (500ms apart). This cache used to fetch with a 8-worker thread pool —
# up to 8 concurrent requests, 4x over the documented limit, on every
# single batch fetch. That's the real, documented explanation for this
# project's whole history of rate-limit trouble, not bad luck — and
# Scryfall's docs explicitly warn that continuing to overload the API
# "may result in a temporary or permanent ban" of the application. A
# small margin (550ms) on top of the 500ms minimum absorbs clock/network
# jitter. The lock only guards the wait+timestamp update, not the request
# itself, so dispatches are correctly paced while responses can still
# overlap — this isn't just a smaller thread pool, a smaller pool alone
# wouldn't guarantee the 500ms spacing between dispatches.
_scryfall_rate_lock = threading.Lock()
_last_scryfall_request_at = 0.0
_MIN_SCRYFALL_INTERVAL = 0.55


def throttle_scryfall() -> None:
    global _last_scryfall_request_at
    with _scryfall_rate_lock:
        wait = _last_scryfall_request_at + _MIN_SCRYFALL_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_scryfall_request_at = time.monotonic()

# Both Scryfall and EDHREC (tool_loop.py's other direct-fetch calls) are
# free and keyless; sending a descriptive User-Agent is good etiquette
# regardless (Scryfall's docs ask for it explicitly). Defined here, not
# tool_loop.py, so tool_loop.py can import from this module without a
# circular import back the other way.
API_HEADERS = {
    "User-Agent": "mtg-deck-doctor/0.1 (personal project)",
    "Accept": "application/json",
}

# Exempt from Commander's singleton rule — and, for the same reason,
# never worth recommending ("add a Forest"). Lives here as the shared
# base module so tool_loop.py and edhrec.py can both import it.
BASIC_LAND_NAMES = {"Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes"}


class CardNotFound(Exception):
    """A genuine Scryfall 404 — the name doesn't match any real card, as
    opposed to a failed *attempt* to check (rate limit, network error).
    Callers need this distinction: a typo should be shown as wrong, but a
    rate-limited lookup should be retried, never reported as "not a card".
    """


# Every field a cached entry must have to be trusted as-is. Guards against
# a cache written before a field was added (colorIdentity didn't exist
# until lookup_card started relying on it) silently reading as an empty/
# missing value instead of triggering a re-fetch — a stale entry defaulting
# color identity to [] would wrongly validate as colorless for any
# commander, a real correctness bug, not just a display gap.
_CACHED_INFO_FIELDS = {"id", "name", "typeLine", "priceUsd", "legality", "oracleText", "colorIdentity"}


def _is_current_schema(info: dict) -> bool:
    return _CACHED_INFO_FIELDS.issubset(info.keys())


def _valid_cached_info(cached: dict | None) -> dict | None:
    """A stale-schema cached entry is treated the same as no entry at all
    — never served as a fallback, since it's missing a field something
    now depends on for correctness (see _CACHED_INFO_FIELDS)."""
    if cached and _is_current_schema(cached["info"]):
        return cached["info"]
    return None


def _load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    return json.loads(CACHE_PATH.read_text())


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Write-then-rename, so a reader on another thread never sees half a file.
    tmp = CACHE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cache, indent=2))
    os.replace(tmp, CACHE_PATH)


_cache_lock = threading.Lock()


def _merge_into_cache(entries: dict[str, dict]) -> None:
    """Adds `entries` to the cache on disk. Re-reads the file under a lock
    rather than writing back a dict loaded before a slow fetch: two lookups
    in flight at once (an import's card check and the insights tab's
    candidate fetch, say) would each write back a copy missing the other's
    entries, silently discarding whichever finished first — and the import's
    next step would then find its cards uncached and fetch them one by one.
    """
    if not entries:
        return
    with _cache_lock:
        cache = _load_cache()
        cache.update(entries)
        _save_cache(cache)


def _fetch_from_scryfall(name: str) -> dict:
    throttle_scryfall()
    response = httpx.get(
        "https://api.scryfall.com/cards/named",
        params={"exact": name},
        headers=API_HEADERS,
    )
    if response.status_code == 404:
        raise CardNotFound(name)
    response.raise_for_status()
    return _info_from_card(response.json())


def _info_from_card(card: dict) -> dict:
    oracle_text = card.get("oracle_text")
    if oracle_text is None and "card_faces" in card:
        oracle_text = (
            "\n//\n".join(face.get("oracle_text", "") for face in card["card_faces"] if face.get("oracle_text"))
            or None
        )

    return {
        "id": card.get("id"),
        "name": card.get("name"),
        "typeLine": card.get("type_line") or (card.get("card_faces") or [{}])[0].get("type_line"),
        "priceUsd": card.get("prices", {}).get("usd"),
        "legality": card.get("legalities", {}).get("commander"),
        "oracleText": oracle_text,
        "colorIdentity": card.get("color_identity", []),
        # Not in _CACHED_INFO_FIELDS: entries cached before these existed are
        # still good for everything else, and are filled in on demand (see
        # tool_loop.review_cuts) rather than all being thrown away at once.
        "manaCost": card.get("mana_cost") or (card.get("card_faces") or [{}])[0].get("mana_cost"),
        "cmc": card.get("cmc"),
    }


def peek_card_info(name: str) -> dict | None:
    """Cache only — never touches the network. For callers that want to
    enrich something with data *if we already have it* (e.g. adding art ids
    to stored suggestions) without being able to afford, or wanting to
    wait on, a throttled Scryfall fetch."""
    return _valid_cached_info(_load_cache().get(name))


def get_card_info(name: str, refresh: bool = False) -> dict | None:
    cache = _load_cache()
    cached = cache.get(name)
    if not refresh:
        valid = _valid_cached_info(cached)
        if valid is not None:
            return valid
    try:
        info = _fetch_from_scryfall(name)
    except CardNotFound:
        # Don't cache a permanent miss — a typo looked up today shouldn't
        # poison the cache forever.
        return _valid_cached_info(cached)
    except httpx.HTTPError:
        # Covers both a bad status code (HTTPStatusError, almost always
        # Scryfall's own rate limit) and a connection-level failure
        # (RequestError — DNS, timeout, refused). Either way: fall back to
        # whatever's cached rather than losing data the frontend already
        # had a moment ago, or 500ing the whole request.
        return _valid_cached_info(cached)
    _merge_into_cache({name: {"info": info, "fetchedAt": time.time()}})
    return info


# Scryfall's documented maximum identifiers per /cards/collection request.
COLLECTION_CHUNK_SIZE = 75


def _normalize(name: str) -> str:
    """Scryfall matches names ignoring case, accents and ligatures ("Lim-Dul's
    Vault" finds "Lim-Dûl's Vault", "Æther" finds "Aether") — so matching a
    returned card back to the name that was asked for has to as well."""
    folded = unicodedata.normalize("NFKD", name.replace("Æ", "Ae").replace("æ", "ae"))
    return " ".join("".join(ch for ch in folded if not unicodedata.combining(ch)).lower().split())


def _front_face(name: str) -> str:
    return name.split(" // ")[0]


def _fetch_collection(names: list[str]) -> tuple[dict[str, dict], list[str], list[str], list[str]]:
    """Looks up `names` through /cards/collection, 75 per request — one
    throttled request where /cards/named takes one per card, which is the
    difference between a 100-card import taking a minute and taking a second.

    Returns (found {name: info}, not_found, unmatched, failed):
    - not_found: a plain name Scryfall has no card for. Confirmed — the
      collection endpoint matches names the way /cards/named's `exact` does
      (same handling of case, accents, ligatures and face names), so there's
      no second opinion to get.
    - unmatched: names that need one. The collection endpoint can't take the
      full "A // B" form of a split or double-faced card, so those go in by
      front face and are checked against the full name afterwards; one that
      doesn't match (a wrong back face) lands here.
    - failed: the request itself failed (almost always the rate limit).
    """
    found: dict[str, dict] = {}
    not_found: list[str] = []
    unmatched: list[str] = []
    failed: list[str] = []
    for start in range(0, len(names), COLLECTION_CHUNK_SIZE):
        chunk = names[start : start + COLLECTION_CHUNK_SIZE]
        identifiers = list(dict.fromkeys(_front_face(n) for n in chunk))
        try:
            throttle_scryfall()
            response = httpx.post(
                "https://api.scryfall.com/cards/collection",
                json={"identifiers": [{"name": i} for i in identifiers]},
                headers=API_HEADERS,
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError:
            failed.extend(chunk)
            continue

        # A card is indexed under its full name and under each face's name;
        # full names win a clash, so "Fire // Ice" never resolves to some
        # other card that happens to have a face called "Fire".
        by_name: dict[str, dict] = {}
        for card in payload["data"]:
            by_name.setdefault(_normalize(card["name"]), card)
        for card in payload["data"]:
            for face in card.get("card_faces") or []:
                by_name.setdefault(_normalize(face["name"]), card)
        missing = {entry["name"] for entry in payload["not_found"]}

        for name in chunk:
            card = by_name.get(_normalize(name))
            if card is not None:
                found[name] = _info_from_card(card)
            elif name == _front_face(name) and name in missing:
                not_found.append(name)
            else:
                unmatched.append(name)
    return found, not_found, unmatched, failed


def get_card_info_batch(names: list[str], refresh: bool = False) -> dict:
    """Returns {"info": {name: CardInfo}, "not_found": [...], "failed": [...]}.

    "not_found" names are a confirmed Scryfall 404 — genuinely not a real
    card (or a typo). "failed" names are ones a lookup attempt failed on
    (almost always the rate limit) — still worth retrying, not a dead end.
    A plain `name in info` check (as before this distinction existed)
    can't tell these apart, which matters a lot for an import flow: a
    rate-limited burst while resolving a 100-card pasted list shouldn't
    read as "half these names are wrong".
    """
    cache = _load_cache()
    to_fetch = list(dict.fromkeys(name for name in names if refresh or _valid_cached_info(cache.get(name)) is None))
    not_found: set[str] = set()
    fetched: dict[str, dict] = {}

    if to_fetch:
        found, confirmed_missing, unmatched, _failed = _fetch_collection(to_fetch)
        fetched.update({name: {"info": info, "fetchedAt": time.time()} for name, info in found.items()})
        not_found.update(confirmed_missing)

        # The rare name the collection lookup couldn't place gets a second
        # opinion from /cards/named — one throttled request each.
        def check_one(name: str) -> tuple[str, dict | None, bool]:
            try:
                return name, _fetch_from_scryfall(name), False
            except CardNotFound:
                return name, None, True
            except httpx.HTTPError:
                return name, None, False

        if unmatched:
            with ThreadPoolExecutor(max_workers=4) as executor:
                for name, info, is_missing in executor.map(check_one, unmatched):
                    if info is not None:
                        fetched[name] = {"info": info, "fetchedAt": time.time()}
                    elif is_missing:
                        not_found.add(name)
        _merge_into_cache(fetched)

    info_result = {}
    for name in names:
        valid = _valid_cached_info(fetched.get(name) or cache.get(name))
        if valid is not None:
            info_result[name] = valid
    failed = [name for name in names if name not in info_result and name not in not_found]
    return {"info": info_result, "not_found": sorted(not_found), "failed": failed}
