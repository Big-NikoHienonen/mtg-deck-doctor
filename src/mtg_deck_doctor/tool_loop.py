"""MTG Deck Doctor's tool-calling loop. Claude advises on Commander decks
through real Scryfall lookups and EDHREC synergy data, against a persistent
Deck object. It proposes changes through a validated tool; the player applies
each one.
"""

import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

import httpx
from anthropic import Anthropic
from dotenv import load_dotenv

from mtg_deck_doctor.card_cache import API_HEADERS, BASIC_LAND_NAMES, get_card_info, get_card_info_batch, peek_card_info
from mtg_deck_doctor.deck import Deck, load_deck, refresh_if_stale, retry_on_conflict, save_deck, save_messages
from mtg_deck_doctor.edhrec import fetch_commander_page, get_commander_includes
from mtg_deck_doctor import usage

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
def env_setting(name: str, default: str) -> str:
    """An environment setting, or `default` when it is unset or blank — which is what a copied
    .env.example leaves behind, and `os.environ.get(name, default)` would take for a real value."""
    return os.environ.get(name, "").strip() or default


MODEL = env_setting("ANTHROPIC_MODEL", "claude-sonnet-5")


def create_message(feature: str, **kwargs):
    """The one way the app calls the model: refuses once the day's budget is spent, and logs what
    the call used under `feature` (see usage.py). Takes the arguments of `messages.create`."""
    usage.check_budget()
    started = time.monotonic()
    response = client.messages.create(model=MODEL, **kwargs)
    usage.record(feature, MODEL, getattr(response, "usage", None), getattr(response, "stop_reason", None), time.monotonic() - started)
    return response


# Changes one suggest_changes call may propose. A longer list is cut, and the reply says so.
MAX_SUGGESTIONS = 30

# --- The tool menu -------------------------------------------------------
# This is the JSON schema the model sees. It never gets your Python code,
# just this description of what it's allowed to ask for. The chat can look
# things up and propose changes, but never makes one: the player applies each
# with a click, through the same endpoints as editing by hand.
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
        "name": "suggest_changes",
        "description": (
            "Propose changes to the deck: add a card, remove one, or change the commander. You cannot change "
            "the deck yourself. The player sees each proposal as a button and applies it with one click, so "
            "whenever you recommend a change, call this instead of only naming the card in your reply. Every "
            "proposal is checked against the real rules (legality, color identity, singleton, deck size) and "
            "the result says which were accepted and why the rest were not: fix a rejected one and call again, "
            "or say why it can't be done. An accepted proposal is not a change yet, so never say a card was "
            "added or removed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": {
                    "type": "array",
                    "description": f"At most {MAX_SUGGESTIONS} changes.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": ["add", "remove", "commander"]},
                            "name": {"type": "string", "description": "Exact card name"},
                            "why": {"type": "string", "description": "One sentence on why, shown beside the button"},
                        },
                        "required": ["action", "name", "why"],
                    },
                },
            },
            "required": ["changes"],
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
def _check_commander(name: str) -> dict:
    """Whether a card can lead a deck, with no side effects: returns {"error": ...} or
    {"card": <lookup_card result>}."""
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
    return {"card": card}


@retry_on_conflict
def set_commander(deck: Deck, name: str) -> dict:
    checked = _check_commander(name)
    if "error" in checked:
        return checked
    card = checked["card"]
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


def suggest_changes(deck: Deck, changes: object) -> dict:
    """Checks the changes the Doctor proposes against `deck`, and changes nothing. Returns
    {"accepted": [{"action", "name", "why", "oracle_text"}], "rejected": [{"action", "name", "error"}]},
    each in the order proposed. Removals and a new commander count before additions, so a swap
    isn't refused on a full deck; two additions can't both take the last slot. An accepted name is the
    card's own spelling, so applying it adds what was checked."""
    if not isinstance(changes, list):
        return {"error": "changes must be a list of {action, name, why}"}
    proposed = changes[:MAX_SUGGESTIONS]
    # Checked against a copy, so each accepted change counts for the ones after it.
    trial = replace(deck, cards=list(deck.cards))
    outcomes: list[dict | None] = [None] * len(proposed)

    def entry(change: object) -> tuple[str, str, str]:
        item = change if isinstance(change, dict) else {}
        return str(item.get("action", "")), str(item.get("name", "")).strip(), str(item.get("why", "")).strip()

    for after_removals in (False, True):
        for i, change in enumerate(proposed):
            action, name, why = entry(change)
            if (action == "add") != after_removals:
                continue
            if action not in ("add", "remove", "commander") or not name:
                outcomes[i] = {"action": action, "name": name, "error": "each change needs an action (add, remove or commander) and a card name"}
                continue
            if action == "remove":
                if name in trial.cards:
                    trial.cards.remove(name)
                    outcomes[i] = {"action": action, "name": name, "why": why}
                else:
                    outcomes[i] = {"action": action, "name": name, "error": f"{name!r} is not in the deck"}
            elif action == "commander":
                checked = _check_commander(name)
                card = checked.get("card")
                if card is None:
                    outcomes[i] = {"action": action, "name": name, "error": checked["error"]}
                elif card["name"] == trial.commander:
                    outcomes[i] = {"action": action, "name": name, "error": f"{card['name']!r} is already the commander"}
                else:
                    trial.commander, trial.commander_color_identity = card["name"], card["color_identity"]
                    outcomes[i] = {"action": action, "name": card["name"], "why": why, "oracle_text": card["oracle_text"]}
            else:
                checked = _check_addable(trial, name)
                card = checked.get("card")
                if card is None:
                    outcomes[i] = {"action": action, "name": name, "error": checked["error"]}
                elif card["name"] not in BASIC_LAND_NAMES and (card["name"] in trial.cards or card["name"] == trial.commander):
                    outcomes[i] = {"action": action, "name": name, "error": f"{card['name']!r} is already in the deck (singleton, except basic lands)"}
                else:
                    trial.cards.append(card["name"])
                    outcomes[i] = {"action": action, "name": card["name"], "why": why, "oracle_text": card["oracle_text"]}

    result: dict = {
        "accepted": [o for o in outcomes if o and "error" not in o],
        "rejected": [o for o in outcomes if o and "error" in o],
    }
    if len(changes) > MAX_SUGGESTIONS:
        result["note"] = f"Only the first {MAX_SUGGESTIONS} changes were considered; the other {len(changes) - MAX_SUGGESTIONS} were left out."
    return result


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
    # Logged under the name of the function that asked, so the usage page can tell the features apart.
    feature = f"structured:{sys._getframe(1).f_code.co_name}"
    for _ in range(8):
        response = create_message(
            feature,
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
        effort="medium",
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


def make_tool_implementations(deck: Deck) -> dict:
    return {
        "lookup_card": lookup_card,
        "search_cards": search_cards,
        "find_synergies": find_synergies,
        "get_edhrec_categories": get_edhrec_categories,
        "suggest_changes": lambda changes: suggest_changes(deck, changes),
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


# Room for one chat turn. Thinking comes out of the same budget, and a turn that looks up several
# cards in parallel can spend most of 2,048 tokens before its last tool call is finished.
CHAT_MAX_TOKENS = 8000


class ConversationCutOff(Exception):
    """The model ran out of tokens in the middle of a tool call, so there is nothing to act on."""


def _without_dangling_tool_use(messages: list[dict]) -> list[dict]:
    """`messages` without a last assistant turn whose tool calls never got results. A turn cut off
    at the token limit used to be saved that way, and the API rejects every message after it."""
    last = messages[-1] if messages else None
    content = last["content"] if last and last["role"] == "assistant" and isinstance(last["content"], list) else []
    return messages[:-1] if any(b.get("type") == "tool_use" for b in content) else messages


# Model calls one user message may make. The last gets no tools and has to wrap up, so a message
# that keeps calling tools ends in a reply instead of running up the bill. Real turns take 2 to 7;
# the cap is a guard against a loop that never ends, not a limit on building a deck.
def _rounds_setting() -> int:
    try:
        return max(2, int(env_setting("CHAT_MAX_TOOL_ROUNDS", "20")))
    except ValueError:
        return 20


MAX_TOOL_ROUNDS = _rounds_setting()

# How hard the model thinks on a chat turn. Anything else than a level the API knows is "medium".
CHAT_EFFORT = env_setting("ANTHROPIC_CHAT_EFFORT", "medium").lower()
if CHAT_EFFORT not in ("low", "medium", "high", "xhigh", "max"):
    CHAT_EFFORT = "medium"

# What the model is shown of earlier turns: at most this many turns, the current one included.
HISTORY_TURNS = 20
# Of the card lookups in earlier turns, the most recent few stay, so it still has their card text.
KEPT_LOOKUPS = 12

WRAP_UP_NOTE = (
    "You have used all the tool calls available for this message. Do not call tools. Tell the user what you "
    "did, what is still left to do, and that they can ask you to continue."
)


def _is_tool_result(message: dict) -> bool:
    content = message["content"]
    return message["role"] == "user" and isinstance(content, list) and any(b.get("type") == "tool_result" for b in content)


def _starts_turn(message: dict) -> bool:
    return message["role"] == "user" and not _is_tool_result(message)


def compact_history(messages: list[dict]) -> list[dict]:
    """`messages` as the model is shown them. The current turn (from the user's latest message on)
    is sent whole, thinking and all, as the API needs. Earlier turns keep what was said, in both
    directions, and the most recent card lookups; their thinking and other tool calls are dropped,
    since the deck's current state is in the system prompt each time. At most HISTORY_TURNS turns
    are shown. The stored conversation is not changed: this is only what is sent."""
    starts = [i for i, m in enumerate(messages) if _starts_turn(m)]
    if len(starts) < 2:
        return messages
    current = starts[-1]
    older = messages[starts[max(0, len(starts) - HISTORY_TURNS)] : current]
    lookups = [
        b["id"]
        for m in older
        if m["role"] == "assistant" and isinstance(m["content"], list)
        for b in m["content"]
        if b.get("type") == "tool_use" and b.get("name") == "lookup_card"
    ]
    keep = set(lookups[-KEPT_LOOKUPS:])
    compacted = []
    for m in older:
        if isinstance(m["content"], str):
            compacted.append(m)
            continue
        blocks = [
            b
            for b in m["content"]
            if b.get("type") == "text"
            or (b.get("type") == "tool_use" and b["id"] in keep)
            or (b.get("type") == "tool_result" and b["tool_use_id"] in keep)
        ]
        if blocks:
            compacted.append({"role": m["role"], "content": blocks})
    return [*compacted, *messages[current:]]


def _with_wrap_up_note(messages: list[dict]) -> list[dict]:
    """`messages` with the instruction to stop calling tools added to the last one, a user turn."""
    last = messages[-1]
    content = last["content"] if isinstance(last["content"], list) else [{"type": "text", "text": last["content"]}]
    return [*messages[:-1], {"role": "user", "content": [*content, {"type": "text", "text": WRAP_UP_NOTE}]}]


def run_conversation(deck: Deck, messages: list[dict], user_message: str) -> tuple[str, list[dict]]:
    """Runs the tool-calling loop for one user turn against `deck`, starting
    from `messages` (prior conversation history, [] for a new deck). Returns
    (reply_text, updated_messages) — the caller decides whether/how to
    persist the updated messages (the CLI and the API both do, via
    deck.messages).
    """
    tool_implementations = make_tool_implementations(deck)
    messages = [*_without_dangling_tool_use(messages), {"role": "user", "content": user_message}]
    rounds = 0

    while True:
        rounds += 1
        wrapping_up = rounds >= MAX_TOOL_ROUNDS
        # Rebuilt every iteration, not just once, so a mutation from an
        # earlier tool call this same turn is visible on the next one — and
        # the deck is brought up to date first, so an edit the user made by
        # hand while this turn was running is too.
        refresh_if_stale(deck)
        stable_prompt = (
            "You are a Magic: The Gathering Commander deck-building "
            "assistant. Always use tools for card data and synergy "
            "suggestions — never rely on memory. "
            "When you describe what a card does (a new commander, a card "
            "you just added, anything else), base that description ONLY "
            "on the 'oracle_text' field in the tool result you received "
            "for it in THIS conversation — never from what you recall "
            "about the card, even a famous one. If a tool result you're "
            "about to describe has no oracle_text, call lookup_card for "
            "that exact name first rather than guessing.\n\n"
            f"{COMMANDER_RULES_PRIMER}\n\n"
            "You cannot change the deck yourself. To add a card, remove "
            "one, or change the commander, call suggest_changes: the "
            "player sees each proposal as a button and applies it with "
            "one click. Always propose changes that way, not only by "
            "naming the cards in your reply, and say in your reply what "
            "you propose and why. A proposal is not a change, so never "
            "say a card was added or removed. If suggest_changes rejects "
            "a proposal, fix it and call again, or tell the player why "
            "it can't be done.\n\n"
            "When building a deck from scratch or filling out an "
            "incomplete one, aim for roughly this composition out of 99 "
            "non-commander cards: 36-38 lands (use search_cards or "
            "get_edhrec_categories' Lands/Utility Lands for real "
            "candidates — never invent land names), ~10 ramp/mana "
            "rocks, ~10 removal or interaction, ~8-10 card draw or "
            "advantage, and the rest synergy pieces and win conditions. "
            "If the user hasn't stated a budget preference (cheapest / "
            "best-performing / a middle ground) before you propose "
            "priced cards in bulk, ask first — then use search_cards' "
            "usd<= filter or sort by price_usd yourself to honor it. "
            f"Put related proposals in one suggest_changes call (up to {MAX_SUGGESTIONS} changes) "
            "rather than calling it once per card."
        )
        # The instructions come first and are cached, so a turn pays full price for them once; the deck's
        # state changes with every edit and comes after them.
        system_prompt = [
            {"type": "text", "text": stable_prompt, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": f"Current deck state:\n{describe_deck(deck)}"},
        ]
        request_messages = compact_history(messages)
        if wrapping_up:
            request_messages = _with_wrap_up_note(request_messages)
        response = create_message(
            "chat",
            max_tokens=CHAT_MAX_TOKENS,
            system=system_prompt,
            tools=TOOLS,
            messages=request_messages,
            # Caches the conversation so far, so the next call of this turn pays full price only for what is new.
            cache_control={"type": "ephemeral"},
            **({"tool_choice": {"type": "none"}} if wrapping_up else {}),
            output_config={"effort": CHAT_EFFORT},
        )

        # A tool call cut off at the limit is half-written, so it can't be answered, and saving it
        # would leave a history the API refuses. Nothing is saved: the caller never sees this turn.
        if response.stop_reason == "max_tokens" and any(b.type == "tool_use" for b in response.content):
            raise ConversationCutOff("ran out of tokens in the middle of a tool call")

        assistant_content = [_serialize_block(block) for block in response.content]
        if wrapping_up:
            # No tools were on offer, so there should be no calls; none is kept, as it would have no result.
            assistant_content = [b for b in assistant_content if b["type"] != "tool_use"]
            if not any(b["type"] == "text" for b in assistant_content):
                assistant_content.append({"type": "text", "text": "I ran out of steps before I could finish. Ask me to continue and I'll pick up from here."})
        messages.append({"role": "assistant", "content": assistant_content})

        if wrapping_up or response.stop_reason != "tool_use":
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
