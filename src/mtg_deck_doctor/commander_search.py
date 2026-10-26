"""Finding commanders for what a player has said so far.

The Doctor turns the facts it has gathered into Scryfall searches — card text, colors,
keywords, "makes Treasure, red, attacks" — and Scryfall returns the commanders that match,
most-played first. Those are then checked against EDHREC: a deck is built from EDHREC's
data for its commander, so a commander it has nothing on can't be offered.

The searches are the model's, so they are treated as untrusted: they always run limited to
legal commanders, are length-capped, and one that Scryfall rejects or that finds nothing is
simply skipped.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

import httpx

from mtg_deck_doctor import wizard
from mtg_deck_doctor.card_cache import API_HEADERS, throttle_scryfall

logger = logging.getLogger(__name__)

# Added to every search, whatever the model wrote.
_REQUIRED = "is:commander legal:commander"
_MAX_QUERY_CHARS = 300
# How many of a search's best (most-played) results are kept.
PER_QUERY = 14


def _limited(query: str) -> str:
    """The search as it will run: the model's words, capped, always among legal commanders."""
    query = " ".join(query.split())[:_MAX_QUERY_CHARS]
    return f"({query}) {_REQUIRED}" if query else _REQUIRED


def _name(card: dict) -> str:
    """The name EDHREC and the card cache know a card by: the front face of a double-faced card."""
    return card["name"].split(" // ")[0]


def _search(query: str) -> list[dict]:
    try:
        throttle_scryfall()
        response = httpx.get(
            "https://api.scryfall.com/cards/search",
            params={"q": _limited(query), "order": "edhrec", "unique": "cards"},
            headers=API_HEADERS,
            timeout=20,
        )
    except httpx.HTTPError:
        return []
    if response.status_code != 200:  # 404: nothing matches; 400: a search Scryfall can't read
        logger.info("Scryfall search %r -> %s", query, response.status_code)
        return []
    out = []
    for card in response.json().get("data", [])[:PER_QUERY]:
        faces = card.get("card_faces") or []
        out.append(
            {
                "name": _name(card),
                "id": card["id"],
                "colors": "".join(c for c in "WUBRG" if c in card.get("color_identity", [])),
                "type_line": card.get("type_line") or (faces[0].get("type_line") if faces else ""),
            }
        )
    return out


def scryfall_candidates(queries: list[str]) -> list[dict]:
    """The commanders found by `queries` ({name, id, colors, type_line}), each once, the
    results of the first search first and then the others in turn — so the most specific
    search leads and the broader ones fill in."""
    results = [_search(q) for q in queries if q.strip()]
    out: list[dict] = []
    seen: set[str] = set()
    for i in range(max((len(r) for r in results), default=0)):
        for rows in results:
            if i < len(rows) and rows[i]["name"] not in seen:
                out.append(rows[i])
                seen.add(rows[i]["name"])
    return out


def with_edhrec(candidates: list[dict], bracket: int) -> list[dict]:
    """The candidates that EDHREC has data for, as the rows the rest of the helper uses
    (name, id, decks, decks at the power level, themes, signature cards). Looked up
    together; commanders EDHREC has no page for are dropped."""

    def row(c: dict) -> dict | None:
        summary = wizard.commander_summary(c["name"])
        if summary is None:
            return None
        return {
            "name": c["name"],
            "id": c["id"],
            "num_decks": summary["num_decks"],
            "themed_decks": None,
            "decks_at_bracket": summary["bracket_counts"].get(str(bracket), 0),
            "bracket_counts": summary["bracket_counts"],
            "themes": summary["themes"],
            "signature": summary["signature"],
        }

    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(row, candidates))
    return [r for r in rows if r is not None]
