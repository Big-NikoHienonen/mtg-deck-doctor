"""MTG Deck Doctor's tool-calling loop. Claude drives Commander deck
building through real Scryfall lookups and EDHREC synergy data, against a
persistent Deck object it can only change through validated tools.
"""

import json
import os
import re
from pathlib import Path

import httpx
from anthropic import Anthropic
from dotenv import load_dotenv

from mtg_deck_doctor.card_cache import API_HEADERS, BASIC_LAND_NAMES, get_card_info, get_card_info_batch, peek_card_info
from mtg_deck_doctor.deck import Deck, load_deck, refresh_if_stale, retry_on_conflict, save_deck, save_messages
from mtg_deck_doctor.edhrec import fetch_commander_page, get_commander_includes

load_dotenv()

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# Stable Commander-format rules knowledge — the kind of thing no card-data
# API encodes, but that strategic advice keeps needing (command zone
# mechanics, color identity, commander tax). Read once at startup and kept
# ambient in every system prompt, rather than a tool the model would have
# to remember to call. If this grows into a bigger reference library later
# (keyword glossary, archetypes), that's the point to switch to on-demand
# tool retrieval instead of always injecting it.
COMMANDER_RULES_PRIMER = (Path("context") / "commander_basics.md").read_text()

# Sonnet by default — worth the extra cost here since fabricating a wrong
# card ability undercuts the app's whole point. Override to a cheaper/faster
# model (e.g. claude-haiku-4-5-20251001) via .env when iterating on plumbing
# rather than answer quality.
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

# --- The tool menu -------------------------------------------------------
# This is the JSON schema the model sees. It never gets your Python code,
# just this description of what it's allowed to ask for.
TOOLS = [
    {
        "name": "lookup_card",
        "description": (
            "Look up a Magic: The Gathering card by exact name and return "
            "its color identity, oracle text, type line, Commander-format "
            "legality, and current market price in USD."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Exact card name, e.g. 'Krenko, Mob Boss'",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "find_synergies",
        "description": (
            "Given a Commander's exact name, return Magic: The Gathering "
            "cards that are statistically over-represented in decks built "
            "around that commander — i.e. cards that synergize well with "
            "it, sourced from real EDHREC deck data rather than guessed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "commander_name": {
                    "type": "string",
                    "description": "Exact commander name, e.g. 'Krenko, Mob Boss'",
                },
            },
            "required": ["commander_name"],
        },
    },
    {
        "name": "search_cards",
        "description": (
            "Search for Magic: The Gathering cards using Scryfall's search "
            "syntax, to discover real candidates for a deck slot instead "
            "of recalling names from memory. Results are sorted by EDHREC "
            "popularity and include name, type_line, color_identity, and "
            "price_usd. Always include 'id<=<letters>' for the current "
            "commander's color identity (e.g. 'id<=R') so results are "
            "guaranteed color-legal, and 'f:commander' to exclude cards "
            "banned in the format. Examples: 't:land id<=R f:commander "
            "usd<=2' for cheap red-legal lands; 't:creature id<=UB "
            "f:commander o:\"whenever you draw\"' for creatures with a "
            "draw-trigger ability; add 'usd<=N' to cap price."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Scryfall search query, e.g. 't:land id<=R f:commander usd<=2'",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_edhrec_categories",
        "description": (
            "Given a Commander's exact name, return EDHREC's category "
            "breakdown of commonly-played cards for that commander: "
            "Creatures, Instants, Sorceries, Enchantments, Mana Artifacts "
            "(ramp), Utility Artifacts, Lands, and Utility Lands, each "
            "with up to 15 real cards. Use this to build a type-balanced "
            "deck and find real land-base candidates, instead of relying "
            "on find_synergies' single flat list."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "commander_name": {
                    "type": "string",
                    "description": "Exact commander name, e.g. 'Krenko, Mob Boss'",
                },
            },
            "required": ["commander_name"],
        },
    },
    {
        "name": "set_commander",
        "description": "Set the Commander for the deck currently being built. Verifies the card is real before setting it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Exact commander card name"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "add_card",
        "description": (
            "Add a card to the deck currently being built, by exact name. "
            "Verifies the card is real and rejects it if already in the "
            "deck (Commander decks are singleton — one copy per card)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Exact card name to add"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "add_cards",
        "description": (
            "Add multiple cards to the deck at once, by exact name. Each "
            "is validated independently exactly like add_card (legality, "
            "color identity, singleton). Prefer this over calling "
            "add_card repeatedly when adding several cards — returns "
            "which succeeded and which failed with why."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Exact card names to add",
                },
            },
            "required": ["names"],
        },
    },
    {
        "name": "remove_card",
        "description": "Remove a card from the deck currently being built, by exact name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Exact card name to remove"},
            },
            "required": ["name"],
        },
    },
]


# --- The real implementation ----------------------------------------------


def lookup_card(name: str) -> dict:
    # Routed through card_cache.py instead of a direct, uncached Scryfall
    # call: most names here have already been fetched for some deck's own
    # display, so this is usually a cache hit; and a lookup that genuinely
    # fails now degrades to a clean per-card error instead of raising an
    # unhandled httpx.HTTPStatusError that used to crash the whole request
    # (a single 429 partway through a bulk add, e.g. importing a pasted
    # decklist, took down the entire batch — confirmed live in the backend
    # log, not hypothetical).
    info = get_card_info(name)
    if info is None:
        return {"error": f"no card named {name!r} found, or Scryfall couldn't be reached right now"}
    return {
        "name": info.get("name") or name,
        "color_identity": info.get("colorIdentity", []),
        "oracle_text": info.get("oracleText"),
        "type_line": info.get("typeLine") or "",
        "legal_in_commander": info.get("legality") == "legal",
        "price_usd": info.get("priceUsd"),
    }


def search_cards(query: str) -> dict:
    response = httpx.get(
        "https://api.scryfall.com/cards/search",
        params={"q": query, "order": "edhrec", "dir": "asc"},
        headers=API_HEADERS,
    )
    if response.status_code == 404:
        return {"results": [], "note": "no cards matched this query"}
    response.raise_for_status()
    data = response.json()
    results = [
        {
            "name": card["name"],
            "type_line": card.get("type_line", ""),
            "color_identity": card.get("color_identity", []),
            "price_usd": card.get("prices", {}).get("usd"),
        }
        for card in data.get("data", [])[:20]
    ]
    return {"results": results, "total_available": data.get("total_cards", len(results))}


def _fetch_edhrec_cardlists(commander_name: str) -> dict:
    """Shared fetch for find_synergies and get_edhrec_categories. Returns
    {"cardlists": [...]} on success or {"error": ...} on failure — now
    served from edhrec.py's cache, which also swallows network failures
    (this used to call raise_for_status unguarded).
    """
    page = fetch_commander_page(commander_name)
    if "error" in page:
        return page
    return {"cardlists": page["cardlists"]}


def find_synergies(commander_name: str) -> dict:
    fetched = _fetch_edhrec_cardlists(commander_name)
    if "error" in fetched:
        return fetched

    synergy_list = next(
        (cl for cl in fetched["cardlists"] if cl.get("tag") == "highsynergycards"), None
    )
    if synergy_list is None:
        return {"error": "no high-synergy card list found for this commander"}

    return {
        "commander": commander_name,
        "high_synergy_cards": [
            card["name"] for card in synergy_list.get("cardviews", [])[:15]
        ],
    }


# EDHREC's per-commander cardlists, keyed by tag, that matter for building a
# type-balanced deck (excludes noisier ones like "newcards"/"gamechangers").
EDHREC_CATEGORY_TAGS = [
    "creatures",
    "instants",
    "sorceries",
    "enchantments",
    "manaartifacts",
    "utilityartifacts",
    "lands",
    "utilitylands",
]


def get_edhrec_categories(commander_name: str) -> dict:
    fetched = _fetch_edhrec_cardlists(commander_name)
    if "error" in fetched:
        return fetched

    by_tag = {cl.get("tag"): cl for cl in fetched["cardlists"]}
    categories = {}
    for tag in EDHREC_CATEGORY_TAGS:
        cardlist = by_tag.get(tag)
        if cardlist:
            categories[cardlist["header"]] = [
                card["name"] for card in cardlist.get("cardviews", [])[:15]
            ]
    return {"commander": commander_name, "categories": categories}


# --- Deck mutation ---------------------------------------------------------
# Each mutating tool is built fresh per deck by make_tool_implementations,
# rather than closing over one hardcoded global — a server handles requests
# for many different decks, so there's no single deck to hardcode against.
# Every check here verifies against real Scryfall data before touching
# state, then saves immediately. This is the validator from the original
# design — implemented as a guard on each mutation instead of a separate
# post-hoc pass, since decks are built one card at a time rather than
# generated whole and checked afterward.
MAX_NON_COMMANDER_CARDS = 99


# These take `deck` explicitly (rather than closing over one) so the same
# validated logic is reusable both from the AI tool loop and directly from
# manual REST endpoints (api.py) when the user edits the deck by hand —
# one source of truth for legality/color-identity/singleton either way.
@retry_on_conflict
def set_commander(deck: Deck, name: str) -> dict:
    card = lookup_card(name)
    if "error" in card:
        return card
    if not card["legal_in_commander"]:
        return {"error": f"{name!r} is banned in the Commander format"}
    is_legendary_creature = "Legendary" in card["type_line"] and "Creature" in card["type_line"]
    can_be_commander = "can be your commander" in (card["oracle_text"] or "").lower()
    if not (is_legendary_creature or can_be_commander):
        return {
            "error": (
                f"{name!r} can't be a commander — it's not a legendary "
                "creature and its text doesn't say 'can be your commander'"
            )
        }
    deck.commander = name
    deck.commander_color_identity = card["color_identity"]
    save_deck(deck)
    return {
        "commander": deck.commander,
        "color_identity": deck.commander_color_identity,
        "oracle_text": card["oracle_text"],
        "cards": deck.cards,
    }


def _check_addable(deck: Deck, name: str) -> dict:
    """Every rule a card must pass to join this deck, with no side effects:
    returns {"error": ...} or {"card": <lookup_card result>}. Shared by
    add_card and the swap path, so there is exactly one definition of
    "legal to add"."""
    if name not in BASIC_LAND_NAMES and (name == deck.commander or name in deck.cards):
        return {"error": f"{name!r} is already in the deck (singleton, except basic lands)"}
    if len(deck.cards) >= MAX_NON_COMMANDER_CARDS:
        return {"error": f"deck already has {MAX_NON_COMMANDER_CARDS} cards, the Commander-format max"}
    card = lookup_card(name)
    if "error" in card:
        return card
    if not card["legal_in_commander"]:
        return {"error": f"{name!r} is banned in the Commander format"}
    if deck.commander and not set(card["color_identity"]) <= set(deck.commander_color_identity):
        return {
            "error": (
                f"{name!r} has color identity {card['color_identity']}, "
                f"outside {deck.commander!r}'s color identity "
                f"{deck.commander_color_identity}"
            )
        }
    return {"card": card}


@retry_on_conflict
def add_card(deck: Deck, name: str) -> dict:
    checked = _check_addable(deck, name)
    if "error" in checked:
        return checked
    deck.cards.append(name)
    save_deck(deck)
    return {"commander": deck.commander, "cards": deck.cards, "oracle_text": checked["card"]["oracle_text"]}


def add_cards(deck: Deck, names: list[str]) -> dict:
    # `failed` is a list, not a dict keyed by name — the same name can
    # appear more than once (e.g. bulk-adding several basic lands), and a
    # dict would silently collapse repeated failures for that name into a
    # single entry, undercounting.
    added, failed = [], []
    for name in names:
        result = add_card(deck, name)
        if "error" in result:
            failed.append({"name": name, "error": result["error"]})
        else:
            added.append({"name": name, "oracle_text": result["oracle_text"]})
    return {"added": added, "failed": failed, "commander": deck.commander, "cards": deck.cards}


@retry_on_conflict
def remove_card(deck: Deck, name: str) -> dict:
    if name not in deck.cards:
        return {"error": f"{name!r} is not in the deck"}
    deck.cards.remove(name)
    save_deck(deck)
    return {"commander": deck.commander, "cards": deck.cards}


def _check_swap(deck: Deck, remove: str, add: str, *, commit: bool) -> dict:
    """Validates `add` against the deck *as it will be after* `remove` is
    gone — which is the whole point of a swap: on a full deck, adding first
    would always be rejected for being at the card cap, and removing first
    would leave the deck a card down if the add then fails. The removal is
    done in memory only, undone on any failure, and the deck is saved once,
    with both changes, only on success (never when `commit` is False).
    """
    if remove == add:
        return {"error": "can't swap a card for itself"}
    if remove not in deck.cards:
        return {"error": f"{remove!r} is not in the deck"}
    original = list(deck.cards)
    deck.cards.remove(remove)
    try:
        checked = _check_addable(deck, add)
        if "error" in checked:
            deck.cards[:] = original
            return checked
        if not commit:
            deck.cards[:] = original
            return {"ok": True, "card": checked["card"]}
        deck.cards.append(add)
        save_deck(deck)
        return {"ok": True, "card": checked["card"]}
    except Exception:
        deck.cards[:] = original
        raise


@retry_on_conflict
def swap_card(deck: Deck, remove: str, add: str) -> dict:
    return _check_swap(deck, remove, add, commit=True)


def check_swap(deck: Deck, remove: str, add: str) -> dict:
    """Same validation as swap_card, without changing anything."""
    return _check_swap(deck, remove, add, commit=False)


RETURN_RECOMMENDATIONS_TOOL = {
    "name": "return_recommendations",
    "description": (
        "Return your final list of recommended cards for this deck. Call "
        "this exactly once, only after using lookup_card/search_cards to "
        "confirm each card is real, Commander-legal, and within the "
        "commander's color identity."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "recommendations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Exact card name"},
                        "reason": {
                            "type": "string",
                            "description": "One sentence on why this card fits the deck",
                        },
                    },
                    "required": ["name", "reason"],
                },
            },
        },
        "required": ["recommendations"],
    },
}

# Read-only subset of TOOLS — recommending cards should never be able to
# mutate the deck itself (set_commander/add_card/etc. are deliberately
# excluded), only look things up.
_READ_ONLY_TOOL_NAMES = {"lookup_card", "search_cards", "find_synergies", "get_edhrec_categories"}
RECOMMENDATION_TOOLS = [t for t in TOOLS if t["name"] in _READ_ONLY_TOOL_NAMES] + [
    RETURN_RECOMMENDATIONS_TOOL
]


_READ_ONLY_IMPLEMENTATIONS = {
    "lookup_card": lookup_card,
    "search_cards": search_cards,
    "find_synergies": find_synergies,
    "get_edhrec_categories": get_edhrec_categories,
}


# Per response, and it has to cover the model's thinking as well as its tool
# call: judging a whole deck can spend well over a thousand tokens on
# thinking alone, and a response cut off mid-thought has no tool call in it.
STRUCTURED_LOOP_MAX_TOKENS = 8000


class StructuredLoopError(Exception):
    """The model ended without calling the final tool — cut off, out of
    rounds, or it stopped on its own. Distinct from a call that returned an
    empty list, which is an answer: callers must not store this as one."""


def _run_structured_loop(
    system_prompt: str,
    user_message: str,
    tools: list[dict],
    final_tool: str,
    key: str,
    *,
    effort: str | None = None,
    max_tokens: int = STRUCTURED_LOOP_MAX_TOKENS,
    flat_keys: tuple[str, ...] = (),
) -> list[dict]:
    """A bounded tool-calling conversation (max 8 rounds) that never touches
    deck.messages — these are sidebar features, not chat turns. Uses
    tool-calling purely as a structured-output mechanism: the model must
    call `final_tool` with its answer instead of writing prose, so the
    result is renderable data, not text to parse. Returns the raw list
    under `key` (unvalidated — callers re-check everything); raises
    StructuredLoopError if the model never produced one. `effort` sets how
    hard the model thinks ("low" to "max"); left unset it uses the model's
    default, which on this model is "high" and can spend most of a long
    response's budget on thinking.
    """
    messages = [{"role": "user", "content": user_message}]
    for _ in range(8):
        response = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=system_prompt,
            tools=tools,
            messages=messages,
            **({"output_config": {"effort": effort}} if effort else {}),
        )

        # A response cut off at the limit may still contain the final tool
        # call, but with its input half-written — never an answer.
        if response.stop_reason == "max_tokens":
            raise StructuredLoopError(f"ran out of tokens before finishing {final_tool}")

        final = next((b for b in response.content if b.type == "tool_use" and b.name == final_tool), None)
        if final:
            # A model sometimes puts an object's fields at the top level instead of
            # under `key`; for calls that return an object, `flat_keys` names fields
            # that say so, and the whole input is the answer.
            if key not in final.input and any(k in final.input for k in flat_keys):
                return final.input
            return final.input.get(key, [])

        if response.stop_reason != "tool_use":
            raise StructuredLoopError(f"stopped without calling {final_tool} (stop_reason={response.stop_reason})")

        messages.append({"role": "assistant", "content": [_serialize_block(b) for b in response.content]})
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result = _READ_ONLY_IMPLEMENTATIONS[block.name](**block.input)
            tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result)})
        messages.append({"role": "user", "content": tool_results})
    raise StructuredLoopError(f"didn't call {final_tool} within 8 rounds")


def suggest_cards(deck: Deck, count: int = 3) -> list[dict]:
    """Asks the model for `count` real, grounded card recommendations for
    `deck` (see _run_structured_loop for how)."""
    system_prompt = (
        "You are recommending cards to add to a Magic: The Gathering "
        "Commander deck. Use tools to find real candidates — never invent "
        "or recall card names from memory. Never recommend a card already "
        "in the deck, the commander itself, or anything outside the "
        "commander's color identity.\n\n"
        f"{COMMANDER_RULES_PRIMER}\n\n"
        f"Current deck state:\n{describe_deck(deck)}\n\n"
        f"When you have {count} good, verified candidates, call "
        "return_recommendations exactly once with your final list."
    )
    raw_recommendations = _run_structured_loop(
        system_prompt,
        f"Recommend {count} cards for this deck.",
        RECOMMENDATION_TOOLS,
        "return_recommendations",
        "recommendations",
    )

    # Never trust the model's own compliance with "verify first" — re-check
    # every suggestion against real data before it reaches the user, same
    # principle as every mutation tool above.
    validated = []
    for rec in raw_recommendations:
        name = rec.get("name")
        if not name or name == deck.commander or name in deck.cards:
            continue
        card = lookup_card(name)
        if "error" in card or not card["legal_in_commander"]:
            continue
        if deck.commander and not set(card["color_identity"]) <= set(deck.commander_color_identity):
            continue
        validated.append({"name": name, "reason": rec.get("reason", ""), "price_usd": card.get("price_usd")})
        if len(validated) >= count:
            break
    return validated


RETURN_REVIEW_TOOL = {
    "name": "return_review",
    "description": (
        "Return your verdict on every candidate swap, plus any swaps of your "
        "own. Call this exactly once, after you have read the card texts and "
        "verified (lookup_card) anything you recommend that you were not "
        "given."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "reviews": {
                "type": "array",
                "description": "Recommended swaps first, best first; then a keep verdict for every other candidate.",
                "items": {
                    "type": "object",
                    "properties": {
                        "cut": {"type": "string", "description": "Exact name of a card currently in the deck"},
                        "verdict": {"type": "string", "enum": ["swap", "keep"]},
                        "add": {
                            "type": "string",
                            "description": (
                                "Exact name of the card to add in its place. Required for a swap — the proposed "
                                "replacement, a better one you verified, or your own — and omitted for a keep."
                            ),
                        },
                        "reason_cut": {
                            "type": "string",
                            "description": (
                                "For a swap: why this card is the weak link in THIS deck — what it does, which cards "
                                "already do its job (named), or how it misses the commander's plan. For a keep: why the "
                                "card earns its slot."
                            ),
                        },
                        "reason_add": {
                            "type": "string",
                            "description": (
                                "For a swap: why players run the added card with this commander — what it does and "
                                "how that connects to the commander or the deck's plan, or what role it fills that "
                                "the deck is short on. Omitted for a keep."
                            ),
                        },
                    },
                    "required": ["cut", "verdict", "reason_cut"],
                },
            },
        },
        "required": ["reviews"],
    },
}
REVIEW_TOOLS = [t for t in TOOLS if t["name"] in _READ_ONLY_TOOL_NAMES] + [RETURN_REVIEW_TOOL]

REVIEW_INSTRUCTIONS = (
    "You are reviewing proposed swaps for a Magic: The Gathering Commander deck. A statistical pass has already "
    "flagged cards that EDHREC players rarely run with this commander and paired each with a card they run often. "
    "Statistics are a lead, not a verdict: your job is to find out whether each swap is actually right, and to say why.\n\n"
    "For every candidate, decide:\n"
    '- "swap": cutting this card and adding that one makes the deck better.\n'
    '- "keep": the card earns its slot (it carries the strategy, fills a role the deck needs, enables a combo), or the '
    "replacement wouldn't help this deck.\n\n"
    "How to judge:\n"
    "- Read the commander's text and work out the deck's plan: what wins, what enables it, which kinds of card the deck "
    "wants more of. Then ask what each card does for that plan.\n"
    "- A card EDHREC players rarely run can be the best card in this particular list (a theme piece, a combo enabler), "
    "and a popular card can do nothing here. Popularity is evidence about a card, not the answer.\n"
    "- Look for redundancy: which cards already in the deck do the cut card's job? Look for gaps: the deck-health "
    "numbers show where it is over or under on lands, ramp, card draw and interaction.\n"
    "- You may recommend a better replacement than the proposed one (from the list of cards the deck lacks, or one you "
    "find with the tools), or a swap of your own, if it is clearly better. Anything you recommend must be verified "
    "Commander-legal, within the commander's color identity, and not already in the deck.\n\n"
    "Quality bar — this matters more than how many swaps you recommend:\n"
    "- Recommend a swap only when it is a clear net gain for this deck's plan: the replacement has to beat the card it "
    "replaces *here*, not merely be popular. Weigh what the deck gives up by the cut as well as what it gains. When "
    "you are unsure, keep. Two excellent swaps beat six plausible ones; recommending none is a fine outcome.\n"
    "- List recommended swaps best first. Then give a keep verdict, with its reason, for every other candidate.\n\n"
    "How to write the reasons — each is one to three sentences, concrete, about these specific cards:\n"
    "- reason_cut: what the card does in this deck and why it is the weak link — name the cards that already do its "
    "job, or say how it fails to connect to the commander's plan, or why it is too slow, narrow or costly — and what "
    "the deck gives up by cutting it, if anything. For a keep, say why it earns its slot.\n"
    "- reason_add: why players run this card with this commander — what it does and how that connects to the "
    "commander's ability or the deck's plan, or what role it fills that the deck is short on. The synergy figure is how "
    "much more often the card is played with this commander than with other commanders of its colors; treat it as "
    "evidence and explain the mechanism behind it.\n"
    "- Never give the statistics as the reason (\"played in 40% of decks\", \"rarely played\") — they are the evidence, "
    "not the reason. No filler (\"provides value\", \"strong card\", \"fits the strategy\") without saying how.\n"
    "- Each swap must stand on its own: the owner may apply only some of them, so never justify one swap by pointing at "
    "another in your list.\n"
    "- Card text, mana costs and mana values (MV) come only from what is given below or from lookup_card, never from "
    "memory. When you call a card cheap or expensive, use its MV as given.\n\n"
    "Everything needed to judge the candidates is given below. Use tools only for something that isn't — a "
    "substitute you want to recommend, or a card you want to check."
)

# Room for the thinking as well as a verdict and two reasons per candidate.
REVIEW_MAX_TOKENS = 12000
MAX_REVIEW_CANDIDATES = 10
MAX_RECOMMENDED_SWAPS = 6
# A reason shorter than this can't be doing the job of explaining.
MIN_REASON_CHARS = 40
_ORACLE_CHARS = 400


def _card_line(name: str, info: dict | None, extra: str = "") -> str:
    """`Name [type] (extra) — oracle text`, from the card cache."""
    info = info or {}
    oracle = (info.get("oracleText") or "").replace("\n", " ")
    if len(oracle) > _ORACLE_CHARS:
        oracle = oracle[:_ORACLE_CHARS] + "…"
    cost = f" {info['manaCost']}" if info.get("manaCost") else ""
    mana_value = f", MV {info['cmc']:g}" if info.get("manaCost") and info.get("cmc") is not None else ""
    type_line = f" [{info['typeLine']}{mana_value}]" if info.get("typeLine") else ""
    return f"{name}{cost}{type_line}" + (f" ({extra})" if extra else "") + (f" — {oracle}" if oracle else "")


def _text(value: object) -> str:
    """A model-written field as stripped text — "" for anything that isn't a
    string. Everything the model returns is untrusted, including its shape."""
    return value.strip() if isinstance(value, str) else ""


def _backfill_mana_costs(names: list[str]) -> None:
    """Cards cached before mana costs were recorded get them now — one batched
    request for the lot, and only the first use for a deck pays for it."""
    stale = [
        n for n in set(names) - BASIC_LAND_NAMES if (info := peek_card_info(n)) is not None and "manaCost" not in info
    ]
    if stale:
        get_card_info_batch(stale, refresh=True)


def _edhrec_extra(card: dict | None) -> str:
    if card is None:
        return "not among the cards EDHREC lists for this commander"
    return f"EDHREC: {card['inclusion']:.0%} of decks, {card['synergy']:+.0%} synergy, {card['category']}"


def review_cuts(deck: Deck, candidates: list[dict], health: list[dict]) -> list[dict]:
    """Has the model review swaps the statistics flagged: for each, whether it
    is really worth making, and the actual reasons — why the card should go and
    why players run its replacement with this commander. `candidates` are
    {"cut", "add", "flag"} dicts from the frontend's ranking; `health` is its
    deck-composition read ({"label", "count", "target", "cards"}). Neither is
    trusted: candidates are re-checked as swaps before the model sees them, and
    everything the model returns is re-validated before it is stored.

    Returns items of two kinds: {"cut", "verdict": "swap", "add", "reason_cut",
    "reason_add", "source", "price_usd"} and {"cut", "verdict": "keep",
    "reason_cut"}."""
    keep = [name for name in deck.keep if name in deck.cards]
    includes = get_commander_includes(deck.commander) if deck.commander else {"available": False}
    by_name = {c["name"]: c for c in includes["cards"]} if includes.get("available") else {}

    pairs: list[tuple[str, str, str]] = []
    for candidate in candidates[:MAX_REVIEW_CANDIDATES]:
        cut, add = candidate.get("cut"), candidate.get("add")
        if not cut or not add or cut in keep or any(cut == p[0] or add == p[1] for p in pairs):
            continue
        if "error" in check_swap(deck, cut, add):
            continue
        pairs.append((cut, add, candidate.get("flag") or ""))
    if not pairs:
        return []

    _backfill_mana_costs([deck.commander, *deck.cards, *(add for _, add, _ in pairs)])

    commander_info = peek_card_info(deck.commander)
    lines = [
        "COMMANDER",
        _card_line(deck.commander, commander_info, f"color identity {''.join(deck.commander_color_identity) or 'colorless'}"),
        "",
        "DECK HEALTH (the deck's composition against the standard Commander mix, estimated from card text)",
    ]
    for metric in health:
        names = ", ".join(metric.get("cards", [])[:40])
        lines.append(f"- {metric['label']}: {metric['count']} (target {metric['target'][0]}–{metric['target'][1]})" + (f" — {names}" if names else ""))

    lines += ["", f"THE DECK ({len(deck.cards)}/{MAX_NON_COMMANDER_CARDS} cards; EDHREC % is the share of {deck.commander} decks that run the card)"]
    for name in sorted(set(deck.cards)):
        copies = deck.cards.count(name)
        if name in BASIC_LAND_NAMES:
            lines.append(f"- {name} ×{copies} (basic land)")
        else:
            lines.append("- " + _card_line(name, peek_card_info(name), _edhrec_extra(by_name.get(name)) if by_name else ""))
    if keep:
        lines.append(f"The owner has marked these as keepers — never cut them: {', '.join(keep)}")

    lines += ["", "CANDIDATE SWAPS"]
    for i, (cut, add, flag) in enumerate(pairs, 1):
        lines.append(f"{i}. CUT {_card_line(cut, peek_card_info(cut), _edhrec_extra(by_name.get(cut)) if by_name else '')}")
        if flag:
            lines.append(f"   flagged because: {flag}")
        lines.append(f"   ADD {_card_line(add, get_card_info(add), _edhrec_extra(by_name.get(add)))}")

    proposed_adds = {add for _, add, _ in pairs}
    others = [c for c in by_name.values() if c["name"] not in deck.cards and c["name"] not in proposed_adds][:25]
    if others:
        lines += ["", "OTHER CARDS EDHREC PLAYERS RUN WITH THIS COMMANDER THAT THE DECK LACKS (for substitutions)"]
        lines += [f"- {c['name']} ({c['inclusion']:.0%} of decks, {c['synergy']:+.0%} synergy, {c['category']})" for c in others]

    system_prompt = f"{REVIEW_INSTRUCTIONS}\n\n{COMMANDER_RULES_PRIMER}"
    raw = _run_structured_loop(
        system_prompt,
        "\n".join(lines) + f"\n\nReview the {len(pairs)} candidate swaps and call return_review.",
        REVIEW_TOOLS,
        "return_review",
        "reviews",
        effort="medium",
        max_tokens=REVIEW_MAX_TOKENS,
    )

    # Re-validate everything: the model is trusted for judgment and wording,
    # not for what is legal or already in the deck.
    candidate_pairs = {(cut, add) for cut, add, _ in pairs}
    reviewed: list[dict] = []
    seen_cuts: set[str] = set()
    used_adds: set[str] = set()
    swaps = 0
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        cut, verdict = _text(entry.get("cut")), entry.get("verdict")
        reason_cut = _text(entry.get("reason_cut"))
        if not cut or cut not in deck.cards or cut in keep or cut in seen_cuts or not reason_cut:
            continue
        if verdict == "keep":
            seen_cuts.add(cut)
            reviewed.append({"cut": cut, "verdict": "keep", "reason_cut": reason_cut})
        elif verdict == "swap":
            add = _text(entry.get("add"))
            reason_add = _text(entry.get("reason_add"))
            if (
                not add
                or add in used_adds
                or swaps >= MAX_RECOMMENDED_SWAPS
                or len(reason_cut) < MIN_REASON_CHARS
                or len(reason_add) < MIN_REASON_CHARS
            ):
                continue
            checked = check_swap(deck, cut, add)
            if "error" in checked:
                continue
            seen_cuts.add(cut)
            used_adds.add(add)
            swaps += 1
            reviewed.append(
                {
                    "cut": cut,
                    "verdict": "swap",
                    "add": add,
                    "reason_cut": reason_cut,
                    "reason_add": reason_add,
                    # "data" when it is one of the pairs the statistics proposed.
                    "source": "data" if (cut, add) in candidate_pairs else "doctor",
                    "price_usd": checked["card"].get("price_usd"),
                }
            )
    return reviewed


RETURN_DISCOVERIES_TOOL = {
    "name": "return_discoveries",
    "description": (
        "Return the new cards you'd show this player, best first — only ones you can explain with specifics. "
        "Call this exactly once. An empty list is a fine answer."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "picks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Exact name of a card from the new-card list"},
                        "why": {
                            "type": "string",
                            "description": (
                                "One to three sentences: what the card does and how it plays with this deck — "
                                "concrete, warm, no filler."
                            ),
                        },
                        "works_with": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "One to three exact names of cards in the deck (commander included) it works with",
                        },
                    },
                    "required": ["name", "why", "works_with"],
                },
            },
        },
        "required": ["picks"],
    },
}

DISCOVERY_INSTRUCTIONS = (
    "You are helping a Magic: The Gathering Commander player discover cards from recently released sets that could work "
    "in a deck they already love. This is discovery, not criticism: the deck is theirs and it is fine as it is, so "
    "never say or imply that anything is wrong with it, and don't talk about cuts or replacements. You are looking for "
    "cards that would be fun or strong *here*.\n\n"
    "A good pick does something this deck already wants to do — better or differently — or opens up something the deck "
    "can't do yet that its commander makes exciting. Read the commander's text, work out the deck's plan from its list, "
    "then look through the new cards for ones that connect, and name the specific cards in the deck (or the "
    "commander's ability) each pick works with.\n\n"
    "Quality bar: only pick a card you can explain with specifics. Two cards you are genuinely excited about beat four "
    "that are merely in the right colours; picking none is a fine answer. List the best first.\n\n"
    "Write 'why' in one to three concrete sentences about this card and this deck. No filler (\"great card\", "
    "\"fits the strategy\") without saying how. Card text, mana costs, mana values (MV), card types and creature types "
    "come only from what is given below, never from memory — a card is a Dragon only if its type line says Dragon. "
    "Don't do arithmetic on costs (no \"as little as…\"); if you mention a cost, give it as printed."
)

MAX_DISCOVERIES = 4


def discover_new_cards(deck: Deck, pool: list[dict]) -> list[dict]:
    """Has the model look through `pool` — cards from the newest sets,
    already limited to this commander's colours and to Commander-legal new
    cards — for ones that could work in `deck`, and say how. Returns
    [{"name", "id", "why", "works_with", "price_usd", ...}], best first, empty
    if nothing earned a place. The model is trusted for judgment and wording,
    not for what is in the pool: every pick is checked against it."""
    _backfill_mana_costs([deck.commander, *deck.cards])
    lines = [
        "COMMANDER",
        _card_line(deck.commander, peek_card_info(deck.commander), f"color identity {''.join(deck.commander_color_identity) or 'colorless'}"),
        "",
        f"THE DECK ({len(deck.cards)}/{MAX_NON_COMMANDER_CARDS} cards)",
    ]
    for name in sorted(set(deck.cards)):
        copies = deck.cards.count(name)
        lines.append(
            f"- {name} ×{copies} (basic land)" if name in BASIC_LAND_NAMES else "- " + _card_line(name, peek_card_info(name))
        )
    lines += ["", f"NEW CARDS ({len(pool)}, all legal in Commander and within the commander's colours)"]
    lines += ["- " + _card_line(c["name"], c, c["rarity"] or "") for c in pool]

    raw = _run_structured_loop(
        DISCOVERY_INSTRUCTIONS + "\n\n" + COMMANDER_RULES_PRIMER,
        "\n".join(lines) + "\n\nPick the new cards worth showing this player and call return_discoveries.",
        [RETURN_DISCOVERIES_TOOL],
        "return_discoveries",
        "picks",
        effort="medium",
        max_tokens=REVIEW_MAX_TOKENS,
    )

    by_name = {c["name"]: c for c in pool}
    in_deck = {*deck.cards, deck.commander}
    picks: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        card = by_name.get(_text(entry.get("name")))
        why = _text(entry.get("why"))
        if card is None or card["name"] in in_deck or any(p["name"] == card["name"] for p in picks) or len(why) < MIN_REASON_CHARS:
            continue
        picks.append(
            {
                "name": card["name"],
                "id": card["id"],
                "why": why,
                "works_with": [n for n in (entry.get("works_with") or []) if isinstance(n, str) and n in in_deck][:3]
                if isinstance(entry.get("works_with"), list)
                else [],
                "price_usd": card["priceUsd"],
                "mana_cost": card["manaCost"],
                "type_line": card["typeLine"],
                "rarity": card["rarity"],
                "set": card["set"],
            }
        )
        if len(picks) >= MAX_DISCOVERIES:
            break
    return picks


RETURN_COMMANDERS_TOOL = {
    "name": "return_commanders",
    "description": (
        "Return the new commanders you'd show this player, best first — only ones you can explain with specifics. "
        "Call this exactly once. An empty list is a fine answer."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "picks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Exact name of a commander from the new-commander list"},
                        "why": {
                            "type": "string",
                            "description": (
                                "Two or three sentences: what the commander does, what kind of deck it asks you to "
                                "build, and — where it applies — how that connects to the decks the player already has."
                            ),
                        },
                        "like_decks": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Exact commander names of the player's existing decks this one is in the spirit of. "
                                "Empty if it is a genuinely different direction."
                            ),
                        },
                    },
                    "required": ["name", "why", "like_decks"],
                },
            },
        },
        "required": ["picks"],
    },
}

COMMANDER_INSTRUCTIONS = (
    "You are helping a Magic: The Gathering Commander player find a new commander, from recently released sets, that "
    "they would be excited to build a deck around. This is discovery, not criticism: never say or imply that anything "
    "is wrong with the decks they already have.\n\n"
    "Read their existing decks to see what they enjoy — the plans, the creature types, the colours. Favour commanders "
    "that connect to that, and say how. If one of the new commanders would open up a genuinely different direction "
    "they'd probably love, include it and say what makes it different. A commander is worth showing when its text "
    "gives a deck an exciting job to do, not just when it is in the right colours.\n\n"
    "Quality bar: pick at most four, only ones you can explain with specifics; fewer is better, and none is a fine "
    "answer. List the best first.\n\n"
    "Write 'why' in two or three concrete sentences: what the commander does (from its text), what kind of deck it asks "
    "you to build, and how it relates to their decks where it does. No filler (\"great commander\", \"fits the "
    "strategy\") without saying how. Card text, mana costs, mana values (MV), card types and creature types come only "
    "from what is given below, never from memory — a card is a Dragon only if its type line says Dragon. Don't do "
    "arithmetic on costs; if you mention a cost, give it as printed."
)

MAX_COMMANDER_PICKS = 4


def pick_commanders(decks: list[Deck], pool: list[dict], exclude: set[str] | None = None) -> list[dict]:
    """Has the model choose, from `pool` (new commanders), the ones this
    player would most like to build around given the decks they already have.
    `exclude` are cards already being shown elsewhere. Every pick is checked
    against the pool."""
    exclude = exclude or set()
    pool = [c for c in pool if c["name"] not in exclude]
    lines = ["THE PLAYER'S DECKS" + ("" if decks else " — none yet")]
    for deck in decks:
        _backfill_mana_costs([deck.commander])
        names = ", ".join(sorted(n for n in set(deck.cards) if n not in BASIC_LAND_NAMES))
        lines.append(
            _card_line(deck.commander, peek_card_info(deck.commander), f"colours {''.join(deck.commander_color_identity) or 'colourless'}")
        )
        lines.append(f"  deck list: {names}")
    lines += ["", f"NEW COMMANDERS ({len(pool)})"]
    lines += [
        "- " + _card_line(c["name"], c, f"{''.join(c['colorIdentity']) or 'colourless'}, {c['rarity'] or ''}")
        for c in pool
    ]

    raw = _run_structured_loop(
        COMMANDER_INSTRUCTIONS + "\n\n" + COMMANDER_RULES_PRIMER,
        "\n".join(lines) + "\n\nPick the new commanders worth showing this player and call return_commanders.",
        [RETURN_COMMANDERS_TOOL],
        "return_commanders",
        "picks",
        effort="medium",
        max_tokens=REVIEW_MAX_TOKENS,
    )

    by_name = {c["name"]: c for c in pool}
    deck_commanders = {d.commander for d in decks}
    picks: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        card = by_name.get(_text(entry.get("name")))
        why = _text(entry.get("why"))
        if card is None or any(p["name"] == card["name"] for p in picks) or len(why) < MIN_REASON_CHARS:
            continue
        like = entry.get("like_decks")
        picks.append(
            {
                "name": card["name"],
                "id": card["id"],
                "why": why,
                "like_decks": [n for n in like if isinstance(n, str) and n in deck_commanders] if isinstance(like, list) else [],
                "price_usd": card["priceUsd"],
                "mana_cost": card["manaCost"],
                "type_line": card["typeLine"],
                "color_identity": card["colorIdentity"],
                "rarity": card["rarity"],
                "set": card["set"],
            }
        )
        if len(picks) >= MAX_COMMANDER_PICKS:
            break
    return picks


# -- the new-deck helper's agent --------------------------------------------
# The helper's lists are rules over data (wizard.py): EDHREC's average list,
# fitted to the power level and budget. The model's part is what rules can't do:
# read what the player wants in their own words (`interpret_deck_request`),
# choose the commander (`choose_commander`), tailor the list to the request
# (`tailor_deck`), and say in a sentence why each commander on a list suits
# the answers (`explain_commanders`). Anything it names is checked by the rules.

RETURN_ANSWERS_TOOL = {
    "name": "return_answers",
    "description": "Return how you read the player's description, as answers to the form. Call this exactly once.",
    "input_schema": {
        "type": "object",
        "properties": {
            "answers": {
                "type": "object",
                "properties": {
                    "colors": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["W", "U", "B", "R", "G"]},
                        "description": "The colours the deck should be, only if they said or clearly implied them. Empty if not.",
                    },
                    "colorless": {"type": "boolean", "description": "True only if they asked for a colourless deck."},
                    "style": {"type": "string", "description": "Exactly one of the allowed styles, or an empty string if none fits or none was said."},
                    "power": {"type": "integer", "description": "1-4 as described, or 0 if they didn't say or imply how strong."},
                    "budget": {
                        "type": "string",
                        "enum": ["50", "100", "250", "none", "unspecified"],
                        "description": "The cap in dollars that fits what they said ('none' if they said money is no object, 'unspecified' if they didn't say).",
                    },
                    "commander": {"type": "string", "description": "Only if they named a specific commander: its name. Otherwise an empty string."},
                    "color_options": {
                        "type": "array",
                        "items": {"type": "string", "description": "Letters from WUBRG, e.g. \"R\", \"BR\", \"URG\"."},
                        "description": "Only when neither the player's form answers nor their words settle the colours: up to three colour combinations that would make the deck they describe work, best first. Always give at least one then, even for a vague request — choose what suits it. Prefer simpler combinations (one to three colours) unless the deck needs more, and include a single colour when it fits. Empty only when the colours are settled.",
                    },
                    "theme_hints": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Up to three lowercase EDHREC theme names that describe the deck they want (e.g. \"treasure\", \"artifacts\", \"aggro\", \"lifegain\"), used to look for commanders. Empty if none fits.",
                    },
                    "focus": {
                        "type": "string",
                        "description": "One or two sentences, in your words: what the deck should be about, and anything they want in it or kept out of it (themes, mechanics, cards, things to avoid). Empty if they said nothing about that.",
                    },
                    "lesser_known": {
                        "type": "boolean",
                        "description": "True if they want a commander that isn't well known, popular or widely played — a hidden gem, something off the beaten path, underplayed. False if they didn't say.",
                    },
                    "understood": {
                        "type": "string",
                        "description": "One friendly sentence saying how you read it — what you filled in, and anything you left open.",
                    },
                },
                "required": ["colors", "colorless", "style", "power", "budget", "commander", "color_options", "theme_hints", "focus", "lesser_known", "understood"],
            }
        },
        "required": ["answers"],
    },
}

POWER_LEVELS = (
    "1 Exhibition: theme first, silly and casual. 2 Core: about a preconstructed deck's level. "
    "3 Upgraded: tuned past a precon. 4 Optimized: high power, fast mana, tutors, efficient combos."
)

INTERPRET_INSTRUCTIONS = (
    "A player is describing the Magic: The Gathering Commander deck they'd like to build. Turn what they wrote into "
    "answers to a fixed form. Fill in only what they said or clearly implied, and leave the rest open — never guess to "
    "fill a gap. A colour is clearly implied by a colour word or a guild, shard or clan name — not by a card "
    "name (you may misremember a card's colours, and a named commander brings its own) and not by a mood "
    "('spooky', 'friendly').\n\n"
    f"Power levels: {POWER_LEVELS} 'Casual', 'chill', 'relaxed', 'for fun', 'not too strong' mean 2 — the usual "
    "level for friendly games. Use 1 only when they ask for something silly, jank, or theme over winning. 'Strong', "
    "'tuned' mean 3; 'competitive', 'optimized' mean 4. "
    "Budget: pick the cap that fits ('cheap', 'under a hundred' → 100; 'budget' alone → 100), or 'none' if they say money "
    "is no object.\n\n"
    "If they want a commander that isn't well known, popular or widely played ('hidden gem', 'underplayed', 'off the "
    "beaten path', 'not the usual ones'), set lesser_known; popularity is not a style, so leave the style open for it.\n\n"
    "The player may already have answered parts of a form (given below as ALREADY DECIDED). Those answers are final: "
    "don't contradict them, and fill in only what they left open from their words. If their words go beyond the form "
    "— what the deck should do, cards or themes they love, things to avoid — put that in 'focus'.\n\n"
    "Use only the allowed styles you are given, exactly as spelled, and only when one clearly matches. If they name a "
    "commander, return its name as they gave it. Finish with one friendly sentence, 'understood', saying how you read "
    "it and what you left open."
)

MAX_TEXT_CHARS = 600


def _as_object(raw: object, wrapper: str | None = None) -> dict:
    """A tool's object field as a dict. A model sometimes sends an object as a
    string of JSON, or wraps it in the field's own name a second time
    ({"tailoring": {"tailoring": {...}}}); both are undone, and anything else
    that isn't an object is {}."""
    for _ in range(3):
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                return {}
        if isinstance(raw, dict) and wrapper and list(raw) == [wrapper]:
            raw = raw[wrapper]
            continue
        break
    return raw if isinstance(raw, dict) else {}


def _colour_letters(value: object) -> list[str]:
    """Colours from model output: only W, U, B, R, G, each once, in the order given."""
    seen: list[str] = []
    for c in value if isinstance(value, list) else []:
        if isinstance(c, str) and len(c) == 1 and c in "WUBRG" and c not in seen:
            seen.append(c)
    return seen


def _colour_combos(value: object) -> list[str]:
    """Up to three colour combinations from model output, each as WUBRG letters in order, each once."""
    out: list[str] = []
    for entry in _as_list(value):
        letters = "".join(c for c in "WUBRG" if isinstance(entry, str) and c in entry.upper())
        if letters and letters not in out:
            out.append(letters)
    return out[:3]


def _theme_hints(value: object) -> list[str]:
    """Up to three EDHREC theme names from model output: lowercase words, hyphens allowed."""
    out: list[str] = []
    for entry in _as_list(value):
        name = entry.strip().lower().replace(" ", "-") if isinstance(entry, str) else ""
        if re.fullmatch(r"[a-z0-9-]{2,40}", name) and name not in out:
            out.append(name)
    return out[:3]


def _decided_block(given: dict | None) -> str:
    """What the player already answered on the form, for the model to respect."""
    if not given:
        return "ALREADY DECIDED BY THE PLAYER: nothing."
    lines = []
    if given.get("commander"):
        lines.append(f"commander: {given['commander']}")
    if given.get("colors"):
        lines.append("colours: " + ", ".join(given["colors"]))
    elif given.get("colorless"):
        lines.append("colours: colourless")
    if given.get("style"):
        lines.append(f"style: {given['style']}")
    if given.get("power"):
        lines.append(f"power level: {given['power']}")
    if given.get("budget") is not None:
        lines.append("budget: " + ("no limit" if given["budget"] == "none" else f"up to ${given['budget']}"))
    if given.get("lesser_known"):
        lines.append("wants a lesser-known commander")
    return "ALREADY DECIDED BY THE PLAYER: " + ("; ".join(lines) if lines else "nothing.")


def interpret_deck_request(text: str, styles: list[str], given: dict | None = None) -> dict:
    """Reads a free-text description of a wanted deck, with the form answers the
    player already gave (`given`: the same keys as the result), into the helper's
    brief: {"colors", "colorless", "style", "power", "budget" (50/100/250/"none"/
    None for unspecified), "commander" (a name as written, unverified),
    "color_options" (colour combinations the model would try, for when nothing else
    settles the colours), "theme_hints" (EDHREC theme names that fit),
    "focus" (what the deck is about and what to keep out), "lesser_known",
    "understood"}. `styles` are the style names the form offers. Nothing is
    trusted: every value is checked against what the form allows."""
    system = INTERPRET_INSTRUCTIONS + "\n\nAllowed styles: " + ", ".join(styles)
    raw = _run_structured_loop(
        system,
        _decided_block(given) + "\n\nTHEIR WORDS: " + text[:MAX_TEXT_CHARS],
        [RETURN_ANSWERS_TOOL],
        "return_answers",
        "answers",
        effort="low",
        max_tokens=2000,
    )
    raw = _as_object(raw, "answers")
    seen = _colour_letters(raw.get("colors"))
    style = _text(raw.get("style"))
    power = raw.get("power")
    budget = _text(raw.get("budget"))
    return {
        "colors": seen,
        "colorless": raw.get("colorless") is True and not seen,
        "style": style if style in styles else None,
        "power": power if isinstance(power, int) and not isinstance(power, bool) and 1 <= power <= 4 else None,
        "budget": {"50": 50, "100": 100, "250": 250, "none": "none"}.get(budget),
        "commander": _text(raw.get("commander")) or None,
        "color_options": _colour_combos(raw.get("color_options")),
        "theme_hints": _theme_hints(raw.get("theme_hints")),
        "focus": _text(raw.get("focus"))[:400],
        "lesser_known": raw.get("lesser_known") is True,
        "understood": _text(raw.get("understood"))[:300] or "Here's how I read that.",
    }


def _as_list(raw: object) -> list:
    """A tool's array field as a list, reading it from a string of JSON if that is what came."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    return raw if isinstance(raw, list) else []


def _named_reasons(entries: object, allowed: set[str] | None, limit: int) -> list[dict]:
    """[{"name", "why"}] from model output: well-formed entries only, each name
    once, only names in `allowed` when given, at most `limit`."""
    out: list[dict] = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        name, why = _text(entry.get("name")), _text(entry.get("why"))
        if not name or len(why) < 10 or any(o["name"] == name for o in out) or (allowed is not None and name not in allowed):
            continue
        out.append({"name": name, "why": why[:300]})
        if len(out) >= limit:
            break
    return out


# -- finding the commander, a round at a time ----------------------------------------
# The player says what they want; the Doctor keeps a short list of what it has learnt
# (the "facts"), searches for commanders that match them, and offers the closest. Each
# round the player can say more, reject one with a reason, or ask for more like another,
# and the facts — and so the search — get sharper.

MAX_FACTS = 8

RETURN_SEARCH_PLAN_TOOL = {
    "name": "return_search_plan",
    "description": "Return what you now know and how to search for it. Call this exactly once.",
    "input_schema": {
        "type": "object",
        "properties": {
            "plan": {
                "type": "object",
                "properties": {
                    "facts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "What the commander and deck must be, as short statements of at most eight words each, at most eight in all.",
                    },
                    "understood": {
                        "type": "string",
                        "description": "One sentence to the player, as \"you\": what you are now looking for, and what changed since the last round.",
                    },
                    "queries": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "q": {"type": "string", "description": "A Scryfall search, without is:commander or legal:commander."},
                                "why": {"type": "string", "description": "A few words on what this search looks for."},
                            },
                            "required": ["q", "why"],
                        },
                        "description": "One to three Scryfall searches, the most specific first and one broader as a fallback.",
                    },
                    "colors": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "The exact colour identities the commander must have, as WUBRG letters (\"BR\" is exactly black and red, not mono-black or mono-red), \"C\" for colourless; up to three. Empty only if the facts don't fix the colours. Repeat the colours every round while the facts still fix them.",
                    },
                    "color_options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Up to three colour combinations (WUBRG letters) to look in if the searches find too little and the colours aren't fixed; empty if the facts don't point to any.",
                    },
                    "theme_hints": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Up to three lowercase EDHREC theme names that fit, used with the colour combinations.",
                    },
                },
                "required": ["facts", "understood", "queries", "colors", "color_options", "theme_hints"],
            }
        },
        "required": ["plan"],
    },
}

SEARCH_PLAN_INSTRUCTIONS = (
    "A Magic: The Gathering Commander player is looking for the commander for a deck they have in mind, over a few "
    "rounds: each time you offer some, they can tell you more, reject one, or ask for more like another. You are "
    "given what they first asked for, the facts you have collected, what they said this round, the commanders they "
    "rejected (and why) and the ones they liked. Do two things.\n\n"
    "1. Update the facts: short statements (at most eight words, at most eight facts) of what the commander and deck "
    "must be — mechanics, colours, speed, how well known, price feel. Keep every earlier fact unless their new words "
    "withdraw or contradict it; add what the new words tell you; turn a rejection's reason into a fact (\"not a slow "
    "value engine\"); when they like a commander, don't write a fact naming it — write the mechanic of it they like "
    "as a fact, and search for others that share it. Be specific about the mechanic, not just the theme: "
    "\"makes Treasure when attacking\" is a better fact than \"treasure\". Facts are only what they said or clearly implied: never invent a mechanic, a colour, "
    "a budget or a power level they didn't mention, and never write filler facts like \"colours open\" or \"no budget "
    "limit\". If they have said little, there are few facts, and that is fine.\n\n"
    "2. Write one to three Scryfall searches that find commanders satisfying the facts — the most specific first, and "
    "the last one broader so something is always found. Scryfall syntax: o:\"text\" matches rules text (o:treasure, "
    "o:\"whenever ~ attacks\", o:\"create a Treasure\"); t:legendary t:creature; id<=r means colour identity within "
    "red (id<=rg red-green, id:c colourless); mv<=4; pow>=3; kw:haste (keywords); combine with spaces (and) and "
    "\"or\", group with parentheses; -o:\"text\" excludes. Never write is:commander or legal:commander (added for you). "
    "When the colours are fixed, every search uses id=<letters> (exactly those colours: id=br is Rakdos only) and never "
    "id<=, which also matches mono-coloured commanders; a guild, shard or wedge name (Rakdos, Esper, Jund…) fixes the "
    "colours too. Put the colours in the colours field as well, and keep them there each round until the player withdraws them. "
    "Searches are sorted by how many decks play the card, so a specific search finds the well-known ones first.\n\n"
    "Also give colour combinations and EDHREC theme names to fall back on, and say in one sentence to the player, as "
    "\"you\" (never \"the player\"), what you are now looking for."
)


def _checked_search_plan(raw: object) -> dict:
    raw = _as_object(raw, "plan")
    facts: list[str] = []
    for entry in _as_list(raw.get("facts")):
        fact = _text(entry)[:80]
        if fact and fact not in facts:
            facts.append(fact)
    queries = []
    for entry in _as_list(raw.get("queries")):
        entry = entry if isinstance(entry, dict) else {}
        q = _text(entry.get("q"))
        if q and all(q != x["q"] for x in queries):
            queries.append({"q": q[:300], "why": _text(entry.get("why"))[:120]})
    colors = _colour_combos(raw.get("colors"))
    if any(isinstance(c, str) and c.strip().lower() in ("c", "colorless", "colourless") for c in _as_list(raw.get("colors"))) and "" not in colors:
        colors = [*colors, ""][:3]
    return {
        "facts": facts[:MAX_FACTS],
        "understood": _text(raw.get("understood"))[:400],
        "queries": queries[:3],
        "colors": colors,
        "color_options": _colour_combos(raw.get("color_options")),
        "theme_hints": _theme_hints(raw.get("theme_hints")),
    }


def plan_commander_search(
    brief: str,
    facts: list[str],
    said: str | None,
    rejected: list[dict],
    liked: list[str],
    offered: list[str],
) -> dict:
    """Has the model update what it knows from this round and plan the search: {"facts",
    "understood", "queries": [{"q", "why"}], "colors" (exact identities required, "" for
    colourless; empty if not fixed), "color_options", "theme_hints"}. `rejected` is
    [{"name", "reason"}]; `offered` the commanders shown last round."""
    lines = [
        f"WHAT THEY FIRST ASKED FOR: {brief}",
        f"FACTS SO FAR: {'; '.join(facts) if facts else 'none yet'}",
        f"THEY SAID THIS ROUND: {said.strip() if said and said.strip() else '(nothing new)'}",
    ]
    if offered:
        lines.append(f"OFFERED LAST ROUND: {', '.join(offered)}")
    if rejected:
        lines.append("REJECTED: " + "; ".join(f"{r['name']}" + (f" ({r['reason']})" if r.get("reason") else "") for r in rejected))
    if liked:
        lines.append(f"LIKED (find more like these): {', '.join(liked)}")
    raw = _run_structured_loop(
        SEARCH_PLAN_INSTRUCTIONS,
        "\n".join(lines) + "\n\nUpdate the facts, plan the search and call return_search_plan.",
        [RETURN_SEARCH_PLAN_TOOL],
        "return_search_plan",
        "plan",
        effort="low",
        max_tokens=2500,
        flat_keys=("facts", "queries"),
    )
    return _checked_search_plan(raw)


RETURN_COMMANDER_OPTIONS_TOOL = {
    "name": "return_commander_options",
    "description": "Return the commanders you would offer the player, best first. Call this exactly once.",
    "input_schema": {
        "type": "object",
        "properties": {
            "options": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Exact name of one of the listed commanders."},
                        "why": {"type": "string", "description": "Two or three sentences to the player: what the commander does and how it fits what they want."},
                        "fits": {"type": "array", "items": {"type": "string"}, "description": "The facts this commander satisfies, copied exactly."},
                        "misses": {"type": "array", "items": {"type": "string"}, "description": "The facts it doesn't satisfy, copied exactly; empty if it satisfies them all."},
                    },
                    "required": ["name", "why", "fits", "misses"],
                },
            }
        },
        "required": ["options"],
    },
}

COMMANDER_OPTIONS_INSTRUCTIONS = (
    "A Magic: The Gathering Commander player is looking for the commander for a deck they have in mind, over a few "
    "rounds. Below are the facts collected about what they want, anything they rejected or liked, and the commanders "
    "found for those facts, with what EDHREC shows for each. Offer up to three, best first: the ones that satisfy the "
    "most facts, and honestly the closest if none satisfy them all. Never offer a rejected commander. Offer different "
    "directions only when the facts leave room for them; when they are specific, offer the closest three to them.\n\n"
    "For each, list which facts it satisfies (fits) and which it doesn't (misses), copying the fact text exactly, and "
    "write 'why' as two or three concrete sentences to the player, as \"you\" and \"your\" (never \"the player\"): what the "
    "commander does, from its text, and how that matches what you asked for — name any fact it misses. Card text, types "
    "and creature types come only from what is given, never from memory. No filler."
)

MAX_COMMANDER_OPTIONS = 3


def _checked_options(raw: object, names: set[str], facts: list[str]) -> list[dict]:
    """[{"name", "why", "fits", "misses"}] from model output: only names on the menu, once each,
    with a reason, and fits / misses limited to the facts as given."""
    out: list[dict] = []
    for entry in _as_list(raw):
        if not isinstance(entry, dict):
            continue
        name, why = _text(entry.get("name")), _text(entry.get("why"))
        if name not in names or len(why) < 10 or any(o["name"] == name for o in out):
            continue
        keep = lambda value: [f for f in dict.fromkeys(_text(x) for x in _as_list(value)) if f in facts]
        out.append({"name": name, "why": why[:400], "fits": keep(entry.get("fits")), "misses": keep(entry.get("misses"))})
        if len(out) >= MAX_COMMANDER_OPTIONS:
            break
    return out


def propose_commanders(brief: str, facts: list[str], menu: list[dict], rejected: list[dict] | None = None, liked: list[str] | None = None) -> list[dict]:
    """Has the model offer up to three commanders from `menu` (each {"name", "type_line",
    "mana_cost", "colors", "oracle", "themes", "signature", "num_decks", "decks_at_bracket"},
    as wizard.explain_context gives) for the `facts` collected: [{"name", "why", "fits",
    "misses"}], best first, only names on the menu."""
    lines = [
        f"THEIR BRIEF: {brief}",
        f"FACTS: {'; '.join(facts) if facts else 'none yet'}",
    ]
    if rejected:
        lines.append("REJECTED: " + "; ".join(r["name"] + (f" ({r['reason']})" if r.get("reason") else "") for r in rejected))
    if liked:
        lines.append(f"LIKED: {', '.join(liked)}")
    lines += ["", f"COMMANDERS ({len(menu)})"]
    for c in menu:
        head = f"- {c['name']}" + (f" {c['mana_cost']}" if c.get("mana_cost") else "") + (f" [{c['type_line']}]" if c.get("type_line") else "")
        lines.append(head + f" — {c.get('oracle') or '(no text)'}")
        lines.append(
            f"    colors: {c.get('colors') or 'colorless'}; EDHREC: {c['num_decks']:,} decks; themes: {', '.join(c.get('themes') or []) or 'none listed'}; "
            f"signature cards: {', '.join(c.get('signature') or []) or 'none listed'}"
        )
    raw = _run_structured_loop(
        COMMANDER_OPTIONS_INSTRUCTIONS,
        "\n".join(lines) + "\n\nOffer up to three and call return_commander_options.",
        [RETURN_COMMANDER_OPTIONS_TOOL],
        "return_commander_options",
        "options",
        effort="medium",
        max_tokens=3500,
    )
    return _checked_options(raw, {c["name"] for c in menu}, facts)


# -- building a deck in phases -------------------------------------------------
# The Doctor builds a deck as a sequence of phases, each filling one part of it. It
# decides which phases the deck needs and in what order, from the commander and the
# brief; the player reviews each phase before the next begins.

# kind -> (label, what the phase is for). The model chooses among these.
PHASE_KINDS = {
    "must_haves": ("Must-haves", "The cards this deck is built around: the engines and payoffs that make the commander's plan work, and the commander's best partners."),
    "creatures": ("Creatures", "The creatures that carry the plan: engines, tribal members, threats, and the bodies the plan needs."),
    "spells": ("Instants and sorceries", "The instants and sorceries that carry the plan."),
    "ramp": ("Ramp", "Mana acceleration: mana rocks, rituals, land ramp."),
    "draw": ("Card draw", "Ways to refill the hand and keep the engine fed."),
    "removal": ("Removal", "Spot removal and other interaction with what opponents do."),
    "wipes": ("Board wipes", "Mass removal, only as much as the plan can use."),
    "protection": ("Protection", "Keeping the commander and the key pieces alive: counterspells, hexproof, indestructible, flicker."),
    "win_cons": ("Win conditions", "How the deck actually wins: finishers and, where the power level allows, combos."),
    "utility": ("Utility", "Recursion, tutors where the power level allows, and the other support the plan needs."),
    "lands": ("Lands", "The mana base: the non-basic lands worth playing, then basics split by what the deck's cards cost."),
    "flex": ("Best of the rest", "The remaining slots, filled with the best cards left for this deck."),
}

RETURN_PLAN_TOOL = {
    "name": "return_plan",
    "description": "Return the plan for building the deck. Call this exactly once.",
    "input_schema": {
        "type": "object",
        "properties": {
            "plan": {
                "type": "object",
                "properties": {
                    "strategy": {"type": "string", "description": "Two or three sentences to the player: what this deck does and how it wins."},
                    "order_reason": {"type": "string", "description": "One or two sentences to the player: why the phases come in this order for this deck."},
                    "phases": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "kind": {"type": "string", "enum": list(PHASE_KINDS)},
                                "count": {"type": "integer", "description": "How many cards this phase fills (for lands, how many lands in all)."},
                                "why": {"type": "string", "description": "One sentence to the player: what this phase needs to do for THIS deck, and why it comes here."},
                            },
                            "required": ["kind", "count", "why"],
                        },
                    },
                },
                "required": ["strategy", "order_reason", "phases"],
            }
        },
        "required": ["plan"],
    },
}

PLAN_INSTRUCTIONS = (
    "A Magic: The Gathering Commander player is building a deck with you, one phase at a time; each phase fills one "
    "part of the 99 cards besides the commander, and they review each before the next. The commander is chosen. Decide "
    "which phases this deck needs, in what order, and how many cards each fills, so they come to 99 in all.\n\n"
    "Order matters: build first what the deck's plan depends on and what later choices depend on. A creature-based "
    "commander (tokens, tribal, voltron) wants its creatures first; a spells deck wants its payoff spells first; an "
    "engine deck wants its must-haves first. Lands usually come late, once the colored costs of the other cards are "
    "known, unless the deck is built around lands. Only use phases the deck needs, and size them for it: a typical "
    "deck has about 36 lands (fewer with a lot of ramp and a low curve), 8-12 ramp, 7-10 card draw, 6-10 removal, "
    "0-3 board wipes, a few protection pieces, and the rest in the plan's own phases.\n\n"
    "Phase kinds you may use (each at most once):\n"
    + "\n".join(f"- {k}: {label} — {goal}" for k, (label, goal) in PHASE_KINDS.items())
    + "\n\nAlways include lands. End with flex, which takes whatever slots remain. Write every 'why' to the player as "
    "\"you\" and \"your\", specific to this deck, no filler. Card text and creature types come only from what is given."
)

DEFAULT_PHASES = [("must_haves", 10), ("creatures", 14), ("ramp", 10), ("draw", 8), ("removal", 8), ("lands", 36)]
MIN_FLEX = 4


def _checked_plan(raw: object) -> dict:
    """The model's plan as one the builder can run: known phase kinds, each once, sane
    counts, lands present, flex last, and 99 cards in all. Whatever the model got
    wrong is repaired, not refused — a plan with no usable phases becomes the default."""
    raw = _as_object(raw, "plan")
    phases: list[dict] = []
    for entry in _as_list(raw.get("phases")):
        if not isinstance(entry, dict):
            continue
        kind, count = _text(entry.get("kind")), entry.get("count")
        if kind not in PHASE_KINDS or kind == "flex" or any(p["kind"] == kind for p in phases):
            continue
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            continue
        phases.append({"kind": kind, "count": min(count, 60), "why": _text(entry.get("why"))[:300]})
    if not phases:
        phases = [{"kind": k, "count": n, "why": ""} for k, n in DEFAULT_PHASES]
    lands = next((p for p in phases if p["kind"] == "lands"), None)
    if lands is None:
        lands = {"kind": "lands", "count": 36, "why": ""}
        phases.append(lands)
    lands["count"] = max(28, min(lands["count"], 42))
    # The rest must leave room for flex: trim the biggest non-land phases first.
    while sum(p["count"] for p in phases) > 99 - MIN_FLEX:
        biggest = max((p for p in phases if p["kind"] != "lands" and p["count"] > 1), key=lambda p: p["count"], default=None)
        if biggest is None:
            lands["count"] -= 1
        else:
            biggest["count"] -= 1
    phases.append({"kind": "flex", "count": 99 - sum(p["count"] for p in phases), "why": ""})
    return {
        "strategy": _text(raw.get("strategy"))[:600],
        "order_reason": _text(raw.get("order_reason"))[:400],
        "phases": phases,
    }


def plan_phases(brief: str, commander: dict, constraints: str) -> dict:
    """Has the model plan the build: {"strategy", "order_reason", "phases": [{"kind",
    "count", "why"}]}, the phases in the order to build them and totalling 99
    cards, flex last. `commander` is {"name", "oracle", ...}."""
    raw = _run_structured_loop(
        PLAN_INSTRUCTIONS + "\n\n" + COMMANDER_RULES_PRIMER,
        f"THEIR BRIEF: {brief}\nCONSTRAINTS: {constraints}\n\nCOMMANDER: {commander['name']} — {commander.get('oracle') or '(no text)'}"
        "\n\nPlan the build and call return_plan.",
        [RETURN_PLAN_TOOL],
        "return_plan",
        "plan",
        effort="medium",
        max_tokens=3000,
        flat_keys=("strategy", "phases"),
    )
    return _checked_plan(raw)


RETURN_PHASE_TOOL = {
    "name": "return_phase",
    "description": "Return the cards you choose for this phase. Call this exactly once.",
    "input_schema": {
        "type": "object",
        "properties": {
            "phase": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "One or two sentences to the player: what this phase does for the deck."},
                    "picks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "Exact name of a card on the candidate list."},
                                "why": {"type": "string", "description": "One or two sentences, specific to this deck: what it does here and what in the deck it works with."},
                            },
                            "required": ["name", "why"],
                        },
                    },
                },
                "required": ["summary", "picks"],
            }
        },
        "required": ["phase"],
    },
}

PHASE_INSTRUCTIONS = (
    "You are building a Magic: The Gathering Commander deck with a player, one phase at a time. You are given the "
    "brief, the commander, the cards already chosen, the phase to fill and a list of candidate cards (real EDHREC "
    "data for this commander, already limited to what is legal and in the commander's colors). Choose the cards for "
    "this phase from the candidates, best first.\n\n"
    "Quality over quantity: choose as many as the phase asks for only if that many are good; fewer is fine. Think "
    "about what the deck already has — don't double up on a role, and prefer cards that work with what's chosen and "
    "with the commander. Respect the power level and the budget given. Choose only names on the list, spelled "
    "exactly.\n\n"
    "Write each 'why' to the player as \"you\" and \"your\", one or two sentences specific to this deck: what the card "
    "does here, and name a card already in the deck when it works with it. Card text, mana costs, card types and "
    "creature types come only from what is given, never from memory — a card is a Zombie only if its type line says "
    "so. Write 'summary' to the player too: what this phase adds to the deck."
)

LANDS_INSTRUCTIONS = (
    "You are building a Magic: The Gathering Commander deck with a player, one phase at a time. This phase is the "
    "mana base. Choose the non-basic lands worth playing from the candidates, best first — duals and fixing that suit "
    "the deck's colors, utility lands that help the plan — as many as you can justify, no more than the maximum "
    "given. Basic lands fill the rest, split by the deck's colored costs, which is done for you. Respect the budget: "
    "don't spend on a land that adds little. Choose only names on the list, spelled exactly.\n\n"
    "Write each 'why' to the player as \"you\" and \"your\", one sentence: what the land does for this deck. Land "
    "text comes only from what is given. Write 'summary' to the player too: how the mana base is put together."
)

MAX_PHASE_NOTE_CHARS = 400


def _checked_phase(raw: object, pool_names: set[str], limit: int) -> dict:
    raw = _as_object(raw, "phase")
    return {
        "summary": _text(raw.get("summary"))[:500],
        "picks": _named_reasons(_as_list(raw.get("picks")), pool_names, limit),
    }


def propose_phase(
    brief: str,
    commander: dict,
    phase: dict,
    deck_lines: list[str],
    pool: list[dict],
    constraints: str,
    budget: str,
    note: str = "",
    limit: int | None = None,
) -> dict:
    """Has the model choose cards for one phase. `phase` is {"kind", "label",
    "goal", "count", "why"}; `deck_lines` what is chosen so far; `pool` the
    candidates ({"name", "category", "type", "cmc", "price", "inclusion", "oracle"}),
    already filtered to what may be chosen; `budget` the money guidance in words;
    `note` what the player asked for when they asked for different cards. `limit`
    caps how many picks are taken (default: the phase's count). Returns {"summary",
    "picks": [{"name", "why"}]} — names checked against the pool, nothing else."""
    lands = phase["kind"] == "lands"
    lines = [
        f"THEIR BRIEF: {brief}",
        f"CONSTRAINTS: {constraints}",
        f"BUDGET: {budget}",
        "",
        f"COMMANDER: {commander['name']} — {commander.get('oracle') or '(no text)'}",
        "",
        f"CHOSEN SO FAR ({len(deck_lines)} lines)" if deck_lines else "CHOSEN SO FAR: nothing yet",
        *deck_lines,
        "",
        f"THIS PHASE: {phase['label']} — {phase['goal']}",
        f"Why it is here: {phase.get('why') or 'part of the plan'}",
        (f"Choose up to {limit} non-basic lands (the deck has {phase['count']} lands in all)." if lands else f"Choose up to {limit if limit is not None else phase['count']} cards."),
    ]
    if note:
        lines.append(f"THE PLAYER ASKED FOR: {note[:MAX_PHASE_NOTE_CHARS]}")
    lines += ["", f"CANDIDATES ({len(pool)})"]
    for c in pool:
        price = f", ${c['price']:.0f}" if c.get("price", 0) >= 1 else ""
        lines.append(f"- {c['name']} [{c['category']}, MV {c['cmc']:g}{price}, in {c['inclusion']:.0%} of decks] — {c.get('oracle') or ''}")
    take = limit if limit is not None else phase["count"]
    raw = _run_structured_loop(
        (LANDS_INSTRUCTIONS if lands else PHASE_INSTRUCTIONS) + "\n\n" + COMMANDER_RULES_PRIMER,
        "\n".join(lines) + "\n\nChoose the cards and call return_phase.",
        [RETURN_PHASE_TOOL],
        "return_phase",
        "phase",
        effort="medium",
        max_tokens=REVIEW_MAX_TOKENS,
        flat_keys=("summary", "picks"),
    )
    return _checked_phase(raw, {c["name"] for c in pool}, take)


RETURN_REASONS_TOOL = {
    "name": "return_reasons",
    "description": "Return one sentence per commander. Call this exactly once.",
    "input_schema": {
        "type": "object",
        "properties": {
            "reasons": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Exact name of one of the listed commanders"},
                        "reason": {"type": "string", "description": "One sentence, at most 30 words."},
                    },
                    "required": ["name", "reason"],
                },
            }
        },
        "required": ["reasons"],
    },
}

EXPLAIN_INSTRUCTIONS = (
    "A player is choosing a Commander for a deck and has answered a short form (below). For each commander listed, "
    "write one sentence — at most 30 words — saying what the commander does and why it suits those answers.\n\n"
    "Use only the facts given for it: its text, its type, and what EDHREC shows (themes, signature cards, deck counts). "
    "Be specific to this commander; no filler (\"great commander\", \"fits your style\"). Card types and creature types "
    "come only from the type line; don't do arithmetic on costs. Say nothing about price or budget — you aren't given "
    "prices. Don't compare the commanders or rank them."
)


def explain_commanders(answers: str, commanders: list[dict]) -> dict[str, str]:
    """One sentence per commander on `commanders` (each {"name", "type_line",
    "mana_cost", "oracle", "themes", "signature", "num_decks", "decks_at_bracket"})
    on why it suits `answers` (the form's answers, in words). {name: sentence};
    commanders the model skipped or wrote too little for are simply absent."""
    lines = [f"THEIR ANSWERS: {answers}", "", "COMMANDERS"]
    for c in commanders:
        head = f"- {c['name']}" + (f" {c['mana_cost']}" if c.get("mana_cost") else "") + (f" [{c['type_line']}]" if c.get("type_line") else "")
        facts = f"{c['num_decks']:,} decks on EDHREC" + (f", {c['decks_at_bracket']:,} at their chosen power level" if c.get("decks_at_bracket") is not None else "")
        lines.append(head + f" — {c.get('oracle') or '(no text)'}")
        lines.append(f"    EDHREC: {facts}; themes: {', '.join(c.get('themes') or []) or 'none listed'}; signature cards: {', '.join(c.get('signature') or []) or 'none listed'}")
    raw = _run_structured_loop(
        EXPLAIN_INSTRUCTIONS,
        "\n".join(lines) + "\n\nWrite one sentence per commander and call return_reasons.",
        [RETURN_REASONS_TOOL],
        "return_reasons",
        "reasons",
        effort="low",
        max_tokens=3000,
    )
    names = {c["name"] for c in commanders}
    reasons: dict[str, str] = {}
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        name, reason = _text(entry.get("name")), _text(entry.get("reason"))
        if name in names and name not in reasons and len(reason) >= 25:
            reasons[name] = reason
    return reasons


def make_tool_implementations(deck: Deck) -> dict:
    return {
        "lookup_card": lookup_card,
        "search_cards": search_cards,
        "find_synergies": find_synergies,
        "get_edhrec_categories": get_edhrec_categories,
        "set_commander": lambda name: set_commander(deck, name),
        "add_card": lambda name: add_card(deck, name),
        "add_cards": lambda names: add_cards(deck, names),
        "remove_card": lambda name: remove_card(deck, name),
    }


def describe_deck(deck: Deck) -> str:
    if not deck.commander and not deck.cards:
        return "No deck started yet — nothing set as commander, no cards added."
    return (
        f"Commander: {deck.commander or '(not chosen yet)'} "
        f"(color identity: {deck.commander_color_identity or 'n/a'})\n"
        f"Cards in deck: {len(deck.cards)}/{MAX_NON_COMMANDER_CARDS}\n"
        f"{', '.join(deck.cards) or '(none yet)'}"
    )


def _serialize_block(block) -> dict:
    """Anthropic's response content blocks carry SDK-only metadata (e.g.
    `caller`) that the request schema doesn't expect back. Keep only what a
    request actually needs, so `messages` stays plain, JSON-safe data that
    can be persisted to disk and replayed in a later process untouched.
    """
    if block.type == "text":
        return {"type": "text", "text": block.text}
    if block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    if block.type == "thinking":
        # Sonnet's extended-thinking blocks. The signature is required by
        # the API to accept this block back in a later request — dropping
        # it (the old fallback below did) causes a 400 on the next call.
        return {"type": "thinking", "thinking": block.thinking, "signature": block.signature}
    if block.type == "redacted_thinking":
        return {"type": "redacted_thinking", "data": block.data}
    return {"type": block.type}


def run_conversation(deck: Deck, messages: list[dict], user_message: str) -> tuple[str, list[dict]]:
    """Runs the tool-calling loop for one user turn against `deck`, starting
    from `messages` (prior conversation history, [] for a new deck). Returns
    (reply_text, updated_messages) — the caller decides whether/how to
    persist the updated messages (the CLI and the API both do, via
    deck.messages).
    """
    tool_implementations = make_tool_implementations(deck)
    messages = [*messages, {"role": "user", "content": user_message}]

    while True:
        # Rebuilt every iteration, not just once, so a mutation from an
        # earlier tool call this same turn is visible on the next one — and
        # the deck is brought up to date first, so an edit the user made by
        # hand while this turn was running is too.
        refresh_if_stale(deck)
        system_prompt = (
            "You are a Magic: The Gathering Commander deck-building "
            "assistant. Always use tools for card data, synergy "
            "suggestions, and deck changes — never rely on memory. "
            "When you describe what a card does (a new commander, a card "
            "you just added, anything else), base that description ONLY "
            "on the 'oracle_text' field in the tool result you received "
            "for it in THIS conversation — never from what you recall "
            "about the card, even a famous one. If a tool result you're "
            "about to describe has no oracle_text, call lookup_card for "
            "that exact name first rather than guessing.\n\n"
            f"{COMMANDER_RULES_PRIMER}\n\n"
            "Strict output rule for add_card: if the tool result has no "
            "'error' key, the call succeeded — your reply's first "
            "sentence MUST start with the literal word 'Added'. The exact "
            "phrase 'already in' is BANNED from any reply describing a "
            "successful add_card call.\n\n"
            "When building a deck from scratch or filling out an "
            "incomplete one, target roughly this composition out of 99 "
            "non-commander cards: 36-38 lands (use search_cards or "
            "get_edhrec_categories' Lands/Utility Lands for real "
            "candidates — never invent land names), ~10 ramp/mana "
            "rocks, ~10 removal or interaction, ~8-10 card draw or "
            "advantage, and the rest synergy pieces and win conditions. "
            "If the user hasn't stated a budget preference (cheapest / "
            "best-performing / a middle ground) before you start adding "
            "priced cards in bulk, ask first — then use search_cards' "
            "usd<= filter or sort by price_usd yourself to honor it. "
            "Use add_cards instead of many add_card calls when adding "
            "more than a couple of cards at once.\n\n"
            f"Current deck state:\n{describe_deck(deck)}"
        )
        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=system_prompt,
            tools=TOOLS,
            messages=messages,
        )

        assistant_content = [_serialize_block(block) for block in response.content]
        messages.append({"role": "assistant", "content": assistant_content})

        if response.stop_reason != "tool_use":
            reply_text = "".join(
                block["text"] for block in assistant_content if block["type"] == "text"
            )
            return reply_text, messages

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            implementation = tool_implementations[block.name]
            result = implementation(**block.input)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                }
            )

        # All tool results for this round go back as one user turn.
        messages.append({"role": "user", "content": tool_results})


if __name__ == "__main__":
    CLI_DECK_ID = "cli"
    deck = load_deck(CLI_DECK_ID) or Deck(id=CLI_DECK_ID)
    messages = deck.messages

    print("MTG Deck Doctor tool-loop demo. Type a message, or 'quit' to exit.")
    print(f"\n[loaded] {describe_deck(deck)}")
    while True:
        try:
            user_message = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_message or user_message.lower() in {"quit", "exit"}:
            break
        reply, messages = run_conversation(deck, messages, user_message)
        save_messages(deck, messages)
        print(f"\nDeck Doctor: {reply}")
        print(f"\n[deck state] {describe_deck(deck)}")
