"""Cached, failure-tolerant access to EDHREC's per-commander card data.

EDHREC's JSON endpoint is unofficial and undocumented (could change without
notice), but it's one small request per commander and its numbers move
slowly, so one fetch per commander per day is plenty. Cached on disk the
same way card_cache.py caches Scryfall lookups, and — like that module —
degrades to stale data instead of failing when the fetch does: the old
tool_loop.py fetch had no error handling at all, so a flaky EDHREC
response raised straight through the AI tool loop.
"""

import json
import re
import time
from pathlib import Path

import httpx

from mtg_deck_doctor.card_cache import API_HEADERS, BASIC_LAND_NAMES

CACHE_PATH = Path("data/edhrec_cache.json")
CACHE_TTL_SECONDS = 24 * 60 * 60

# The per-type lists partition a commander's non-basic cards; the rest
# (top/high-lift/new/game-changer) are overlapping "views" over those same
# cards, used here only to flag them.
_TYPE_TAGS = {
    "creatures",
    "instants",
    "sorceries",
    "utilityartifacts",
    "manaartifacts",
    "enchantments",
    "battles",
    "planeswalkers",
    "lands",
    "utilitylands",
}


def _slug(name: str) -> str:
    """EDHREC's URL slugs: lowercase, punctuation stripped, spaces -> hyphens."""
    slug = name.lower().replace("'", "").replace(",", "")
    return re.sub(r"[^a-z0-9]+", "-", slug).strip("-")


def commander_slug(name: str) -> str:
    """The name EDHREC uses for this commander in its page addresses."""
    return _slug(name)


def _load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    return json.loads(CACHE_PATH.read_text())


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache))


def fetch_commander_page(commander_name: str) -> dict:
    """Returns {"num_decks": int, "cardlists": [...]} or {"error": "..."}.

    Fresh cache wins; otherwise fetch. A failed fetch falls back to a stale
    cache entry rather than erroring, since day-old EDHREC numbers are far
    better than none. A genuine 404 isn't cached (it's a normal, cheap
    answer for a commander EDHREC simply doesn't have a page for).
    """
    slug = _slug(commander_name)
    cache = _load_cache()
    entry = cache.get(slug)
    if entry and time.time() - entry["fetchedAt"] < CACHE_TTL_SECONDS:
        return {"num_decks": entry["num_decks"], "cardlists": entry["cardlists"]}

    try:
        response = httpx.get(
            f"https://json.edhrec.com/pages/commanders/{slug}.json",
            headers=API_HEADERS,
            timeout=15,
        )
        # Verified via curl: EDHREC serves these from S3, which answers a
        # missing page with 403 AccessDenied rather than a 404.
        if response.status_code in (403, 404):
            return {"error": f"no EDHREC page found for commander {commander_name!r}"}
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError:
        if entry:
            return {"num_decks": entry["num_decks"], "cardlists": entry["cardlists"]}
        return {"error": "EDHREC couldn't be reached right now"}

    container = data.get("container", {}).get("json_dict", {})
    page = {
        "num_decks": container.get("card", {}).get("num_decks", 0),
        "cardlists": container.get("cardlists", []),
    }
    cache[slug] = {"fetchedAt": time.time(), **page}
    _save_cache(cache)
    return page


def get_commander_includes(commander_name: str) -> dict:
    """Every card EDHREC lists for this commander (basics excluded), with
    its inclusion rate, as one flat list the frontend can diff against the
    live deck. Returns {"available": False, "reason": ...} when EDHREC has
    nothing for this commander.

    Inclusion is num_decks / potential_decks — EDHREC's own definition,
    "of the decks that could have played this card, how many did" — which
    stays meaningful for newer cards that have had less time to be played,
    unlike a raw deck count.
    """
    page = fetch_commander_page(commander_name)
    if "error" in page:
        return {"available": False, "reason": page["error"]}
    return _includes_from_page(page)


def peek_commander_includes(commander_name: str) -> dict:
    """The same as get_commander_includes, from the cache only — never the
    network, and with no regard for age. For callers that would rather have
    day-old numbers than wait (the landing page, which reads several
    commanders at once)."""
    entry = _load_cache().get(_slug(commander_name))
    if not entry:
        return {"available": False, "reason": "not cached yet"}
    return _includes_from_page({"num_decks": entry["num_decks"], "cardlists": entry["cardlists"]})


def _includes_from_page(page: dict) -> dict:
    cards: dict[str, dict] = {}
    flags: dict[str, set[str]] = {}
    for cardlist in page["cardlists"]:
        tag = cardlist.get("tag")
        for view in cardlist.get("cardviews", []):
            name = view.get("name")
            if not name or name in BASIC_LAND_NAMES:
                continue
            if tag in _TYPE_TAGS:
                potential = view.get("potential_decks") or 0
                cards[name] = {
                    "name": name,
                    # A Scryfall card id (verified: its cards.scryfall.io image
                    # URLs resolve) — lets the frontend show art for a card
                    # with no lookup at all.
                    "id": view.get("id"),
                    "category": cardlist.get("header", "Other"),
                    "inclusion": (view.get("num_decks", 0) / potential) if potential else 0.0,
                    "synergy": view.get("synergy", 0.0),
                    "lift": view.get("lift", 0.0),
                    "num_decks": view.get("num_decks", 0),
                    "potential_decks": potential,
                }
            elif tag in ("gamechangers", "newcards"):
                flags.setdefault(name, set()).add(tag)

    for name, card in cards.items():
        card["game_changer"] = "gamechangers" in flags.get(name, set())
        card["is_new"] = "newcards" in flags.get(name, set())

    ranked = sorted(cards.values(), key=lambda c: (-c["inclusion"], -c["num_decks"]))
    return {"available": True, "num_decks": page["num_decks"], "cards": ranked}
