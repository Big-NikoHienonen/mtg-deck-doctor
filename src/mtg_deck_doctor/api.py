"""HTTP layer over the tool-calling loop. Thin on purpose — every endpoint
just loads/saves a Deck and calls into tool_loop.py/deck.py; all the actual
logic (including validation) lives there, shared between the AI's tool
calls and these direct manual-edit endpoints.
"""

import hashlib
import json
import logging
import re
import threading
import time
from typing import Literal
from datetime import datetime, timezone

import anthropic
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from mtg_deck_doctor.card_cache import get_card_info, get_card_info_batch, peek_card_info
from mtg_deck_doctor.card_details import get_printings, get_rulings
from mtg_deck_doctor.collection import (
    add_many_to_collection,
    add_to_collection,
    load_collection,
    remove_from_collection,
)
from mtg_deck_doctor.deck import (
    Deck,
    DeckConflictError,
    create_deck,
    deck_fingerprint,
    delete_deck,
    duplicate_deck,
    keep_card,
    list_decks,
    load_ai_result,
    load_deck,
    rename_deck,
    save_ai_result,
    save_messages,
    unkeep_card,
)
from mtg_deck_doctor import ai_errors, deck_builder, wizard
from mtg_deck_doctor.edhrec import get_commander_includes, peek_commander_includes
from mtg_deck_doctor.new_cards import (
    latest_sets,
    load_new_commanders,
    new_card_pool,
    new_commander_pool,
    peek_latest_sets,
    save_new_commanders,
)
from mtg_deck_doctor.tool_loop import (
    MODEL,
    StructuredLoopError,
    add_card,
    add_cards,
    remove_card,
    run_conversation,
    set_commander,
    discover_new_cards,
    explain_commanders,
    pick_commanders,
    review_cuts,
    client,
    suggest_cards,
    swap_card,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="MTG Deck Doctor")

# Vite's and Create React App's default dev-server ports, so the frontend
# can call this from localhost without a CORS error.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# Every deck edit retries on its own when it loses a race (see
# deck.retry_on_conflict), so this only reaches the client when a deck was
# deleted mid-edit or kept changing under it.
@app.exception_handler(DeckConflictError)
def deck_conflict_handler(request: Request, exc: DeckConflictError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


# A failed model call — no credits, a rejected key, rate limiting, an outage —
# reaches the client as a typed error it can explain and act on, from any
# endpoint that calls the model. Left unhandled it would be a bare 500, which
# the browser reports as a network error (the response skips the CORS headers).
@app.exception_handler(anthropic.APIError)
def ai_failure_handler(request: Request, exc: anthropic.APIError) -> JSONResponse:
    status, body = ai_errors.describe(exc)
    logger.warning("model call failed on %s %s: %s (%s)", request.method, request.url.path, body["code"], type(exc).__name__)
    return JSONResponse(status_code=status, content=body)


# The cheapest call there is, for asking "is the model reachable now?" without
# sending anyone's message. The answer, good or bad, is reused for a few
# seconds, so a button pressed repeatedly makes one call.
_PROBE_REUSE_SECONDS = 3
_probe_lock = threading.Lock()
_last_probe: tuple[float, anthropic.APIError | None] = (0.0, None)


@app.get("/ai/status")
def ai_status_endpoint() -> dict:
    global _last_probe
    with _probe_lock:
        checked_at, failure = _last_probe
        if time.monotonic() - checked_at >= _PROBE_REUSE_SECONDS:
            try:
                client.messages.create(model=MODEL, max_tokens=1, messages=[{"role": "user", "content": "ping"}])
                failure = None
            except anthropic.APIError as err:
                failure = err
            _last_probe = (time.monotonic(), failure)
    if failure is not None:
        raise failure
    return {"ok": True}


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str
    deck: Deck


class CardNameRequest(BaseModel):
    name: str


class DeckNameRequest(BaseModel):
    name: str


class SuggestionsResponse(BaseModel):
    # None until suggestions have been generated for this deck at least once.
    suggestions: dict | None


class ReviewCandidate(BaseModel):
    cut: str
    add: str
    # Why the statistics flagged the cut card, in words — context for the review.
    flag: str = ""


class HealthMetricIn(BaseModel):
    label: str
    count: int
    target: list[int]
    cards: list[str] = []


class ReviewCutsRequest(BaseModel):
    candidates: list[ReviewCandidate]
    health: list[HealthMetricIn] = []


class CutsResponse(BaseModel):
    # None until cut suggestions have been requested for this deck at least once.
    cuts: dict | None


class SwapRequest(BaseModel):
    remove: str
    add: str


class BulkCardRequest(BaseModel):
    name: str
    count: int


class BulkAddResponse(BaseModel):
    deck: Deck
    added: int
    failed: int
    error: str | None = None


def _get_deck_or_404(deck_id: str) -> Deck:
    deck = load_deck(deck_id)
    if deck is None:
        raise HTTPException(status_code=404, detail=f"no deck with id {deck_id!r}")
    return deck


def _raise_if_error(result: dict) -> None:
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])


def _generate(generate) -> list[dict]:
    """Runs an AI generation, turning "the model never finished" into a 502
    the frontend can show — rather than storing an empty result that would
    read as "the Doctor has nothing to suggest"."""
    try:
        return generate()
    except StructuredLoopError:
        raise HTTPException(status_code=502, detail="The Doctor didn't finish thinking that through. Try again.")


@app.post("/decks")
def create_deck_endpoint() -> Deck:
    return create_deck()


@app.get("/decks")
def list_decks_endpoint() -> list[Deck]:
    return list_decks()


@app.get("/decks/{deck_id}")
def get_deck_endpoint(deck_id: str) -> Deck:
    return _get_deck_or_404(deck_id)


@app.delete("/decks/{deck_id}")
def delete_deck_endpoint(deck_id: str) -> dict:
    if not delete_deck(deck_id):
        raise HTTPException(status_code=404, detail=f"no deck with id {deck_id!r}")
    return {"deleted": deck_id}


@app.post("/decks/{deck_id}/duplicate")
def duplicate_deck_endpoint(deck_id: str) -> Deck:
    copy = duplicate_deck(deck_id)
    if copy is None:
        raise HTTPException(status_code=404, detail=f"no deck with id {deck_id!r}")
    return copy


@app.post("/decks/{deck_id}/name")
def rename_deck_endpoint(deck_id: str, request: DeckNameRequest) -> Deck:
    return rename_deck(_get_deck_or_404(deck_id), request.name)


@app.post("/decks/{deck_id}/chat")
def chat_endpoint(deck_id: str, request: ChatRequest) -> ChatResponse:
    deck = _get_deck_or_404(deck_id)
    reply, messages = run_conversation(deck, deck.messages, request.message)
    save_messages(deck, messages)
    return ChatResponse(reply=reply, deck=deck)


@app.post("/decks/{deck_id}/commander")
def set_commander_endpoint(deck_id: str, request: CardNameRequest) -> Deck:
    deck = _get_deck_or_404(deck_id)
    _raise_if_error(set_commander(deck, request.name))
    return deck


@app.post("/decks/{deck_id}/cards")
def add_card_endpoint(deck_id: str, request: CardNameRequest) -> Deck:
    deck = _get_deck_or_404(deck_id)
    _raise_if_error(add_card(deck, request.name))
    return deck


@app.delete("/decks/{deck_id}/cards")
def remove_card_endpoint(deck_id: str, name: str) -> Deck:
    deck = _get_deck_or_404(deck_id)
    _raise_if_error(remove_card(deck, name))
    return deck


# Atomic: the replacement is validated against the deck as it will be once
# the cut is gone, and both changes are saved together or not at all — see
# tool_loop._check_swap.
@app.post("/decks/{deck_id}/swap")
def swap_card_endpoint(deck_id: str, request: SwapRequest) -> Deck:
    deck = _get_deck_or_404(deck_id)
    _raise_if_error(swap_card(deck, request.remove, request.add))
    return deck


@app.post("/decks/{deck_id}/keep")
def keep_card_endpoint(deck_id: str, request: CardNameRequest) -> Deck:
    deck = _get_deck_or_404(deck_id)
    _raise_if_error(keep_card(deck, request.name))
    return deck


@app.delete("/decks/{deck_id}/keep")
def unkeep_card_endpoint(deck_id: str, name: str) -> Deck:
    deck = _get_deck_or_404(deck_id)
    unkeep_card(deck, name)
    return deck


@app.post("/decks/{deck_id}/cards/bulk")
def add_cards_bulk_endpoint(deck_id: str, request: BulkCardRequest) -> BulkAddResponse:
    # Always 200 — partial success (e.g. hitting the 99-card cap mid-batch)
    # is a normal, expected outcome here, not an error condition. The
    # response's added/failed counts let the frontend show the real result
    # rather than an all-or-nothing pass/fail.
    deck = _get_deck_or_404(deck_id)
    if request.count < 1:
        raise HTTPException(status_code=400, detail="count must be at least 1")
    result = add_cards(deck, [request.name] * request.count)
    last_error = result["failed"][-1]["error"] if result["failed"] else None
    return BulkAddResponse(deck=deck, added=len(result["added"]), failed=len(result["failed"]), error=last_error)


class ImportEntry(BaseModel):
    name: str
    quantity: int


class ImportCardsRequest(BaseModel):
    entries: list[ImportEntry]


class ImportCardsResponse(BaseModel):
    deck: Deck
    added: int
    failed: list[dict]


@app.post("/decks/{deck_id}/cards/import")
def import_cards_endpoint(deck_id: str, request: ImportCardsRequest) -> ImportCardsResponse:
    # One deck load/save cycle for the whole pasted list (not one request
    # per card name) — same reasoning as the collection's own bulk-add:
    # avoids firing many overlapping writes at a deck with no per-write
    # locking. The frontend has already resolved/validated names against
    # Scryfall before calling this; add_cards re-validates for real
    # (legality, color identity, singleton) regardless, same as every
    # other path into a deck.
    deck = _get_deck_or_404(deck_id)
    flat_names = [entry.name for entry in request.entries for _ in range(entry.quantity)]
    result = add_cards(deck, flat_names)
    return ImportCardsResponse(deck=deck, added=len(result["added"]), failed=result["failed"])


def _present_suggestions(deck: Deck, stored: dict | None) -> SuggestionsResponse:
    """Stored suggestions as the frontend sees them: anything the deck has
    picked up since generation is dropped (no point suggesting a card it
    already has), and `deck_changed` says whether the deck's contents differ
    from what these were written for, so the UI can say so honestly. Each
    gets its Scryfall id from the card cache (no network) so the frontend can
    build a direct, rate-limit-free image URL for it."""
    if stored is None:
        return SuggestionsResponse(suggestions=None)
    owned = set(deck.cards) | ({deck.commander} if deck.commander else set())
    return SuggestionsResponse(
        suggestions={
            "generated_at": stored["generated_at"],
            "deck_changed": stored["fingerprint"] != deck_fingerprint(deck),
            "recommendations": [
                {**r, "id": (peek_card_info(r["name"]) or {}).get("id")}
                for r in stored["items"]
                if r.get("name") not in owned
            ],
        }
    )


# GET never generates anything (no hidden LLM spend from a read); the
# frontend decides when to POST a refresh.
@app.get("/decks/{deck_id}/suggestions")
def get_suggestions_endpoint(deck_id: str) -> SuggestionsResponse:
    deck = _get_deck_or_404(deck_id)
    return _present_suggestions(deck, load_ai_result("suggestions", deck_id))


@app.post("/decks/{deck_id}/suggestions/refresh")
def refresh_suggestions_endpoint(deck_id: str, count: int = 3) -> SuggestionsResponse:
    deck = _get_deck_or_404(deck_id)
    if not deck.commander:
        raise HTTPException(status_code=400, detail="Set a commander before requesting suggestions")
    return _present_suggestions(deck, save_ai_result("suggestions", deck, _generate(lambda: suggest_cards(deck, count))))


def _present_cuts(deck: Deck, stored: dict | None) -> CutsResponse:
    """A stored review as the frontend sees it, split into the swaps the
    Doctor recommends and the flagged cards it would keep. Anything no longer
    actionable is dropped — a swap whose cut has left the deck, whose
    replacement has joined it, or whose cut has since been marked a keeper;
    `deck_changed` says whether the deck differs from what the review was
    written for. Replacements get their Scryfall id from the card cache.
    Reviews stored before there were verdicts and separate reasons (the first
    version of this feature) read as no review at all."""
    if stored is None or any("verdict" not in item for item in stored["items"]):
        return CutsResponse(cuts=None)
    in_deck = set(deck.cards) | ({deck.commander} if deck.commander else set())
    actionable = [i for i in stored["items"] if i["cut"] in deck.cards and i["cut"] not in deck.keep]
    return CutsResponse(
        cuts={
            "generated_at": stored["generated_at"],
            "deck_changed": stored["fingerprint"] != deck_fingerprint(deck),
            "swaps": [
                {**i, "add_id": (peek_card_info(i["add"]) or {}).get("id")}
                for i in actionable
                if i["verdict"] == "swap" and i["add"] not in in_deck
            ],
            "kept": [i for i in actionable if i["verdict"] == "keep"],
        }
    )


# Same contract as suggestions: GET never spends tokens.
@app.get("/decks/{deck_id}/cuts")
def get_cuts_endpoint(deck_id: str) -> CutsResponse:
    deck = _get_deck_or_404(deck_id)
    return _present_cuts(deck, load_ai_result("cuts", deck_id))


@app.post("/decks/{deck_id}/cuts/review")
def review_cuts_endpoint(deck_id: str, request: ReviewCutsRequest) -> CutsResponse:
    deck = _get_deck_or_404(deck_id)
    if not deck.commander:
        raise HTTPException(status_code=400, detail="Set a commander before asking for a review")
    candidates = [c.model_dump() for c in request.candidates]
    health = [h.model_dump() for h in request.health]
    reviewed = _generate(lambda: review_cuts(deck, candidates, health))
    if not reviewed:
        raise HTTPException(status_code=400, detail="None of those swaps could be reviewed — the deck may have changed.")
    return _present_cuts(deck, save_ai_result("cuts", deck, reviewed))


def _present_discoveries(deck: Deck, stored: dict | None, current_codes: list[str] | None) -> dict | None:
    """Stored new-card picks as the frontend sees them: anything the deck has
    since picked up is dropped, and `current` says whether they were written
    for the sets released most recently (a newer set makes them stale — they
    are still shown, until replaced)."""
    if stored is None:
        return None
    in_deck = {*deck.cards, deck.commander}
    return {
        "generated_at": stored["generated_at"],
        "sets": stored.get("sets", []),
        "current": current_codes is not None and sorted(stored.get("sets", [])) == sorted(current_codes),
        "picks": [p for p in stored["items"] if p["name"] not in in_deck],
    }


@app.get("/decks/{deck_id}/discoveries")
def get_discoveries_endpoint(deck_id: str) -> dict:
    deck = _get_deck_or_404(deck_id)
    latest = peek_latest_sets()
    return {"discoveries": _present_discoveries(deck, load_ai_result("discoveries", deck_id), _codes(latest))}


def _codes(latest: dict | None) -> list[str] | None:
    return [s["code"] for s in latest["sets"]] if latest else None


# Looks through the most recently released sets for cards that could work in
# this deck. Run once per deck per set release — new sets come out every
# couple of months, and the picks don't change until one does.
#
# One look per deck at a time: a second request for the same deck (another tab,
# a reload while the first is running) waits for the first and, finding the
# picks already current, returns them instead of paying for another run.
_discovery_locks: dict[str, threading.Lock] = {}


@app.post("/decks/{deck_id}/discoveries/refresh")
def refresh_discoveries_endpoint(deck_id: str, force: bool = False) -> dict:
    with _discovery_locks.setdefault(deck_id, threading.Lock()):
        deck = _get_deck_or_404(deck_id)
        if not deck.commander:
            raise HTTPException(status_code=400, detail="Set a commander before looking for new cards")
        latest = latest_sets()
        if latest is None:
            raise HTTPException(status_code=502, detail="Couldn't reach Scryfall to find the newest sets. Try again.")
        codes = _codes(latest)

        stored = load_ai_result("discoveries", deck_id)
        if stored and not force and sorted(stored.get("sets", [])) == sorted(codes):
            return {"discoveries": _present_discoveries(deck, stored, codes)}

        pool = new_card_pool(codes, deck.commander_color_identity)
        if pool is None:
            raise HTTPException(status_code=502, detail="Couldn't reach Scryfall to load the new cards. Try again.")
        picks = _generate(lambda: discover_new_cards(deck, pool)) if pool else []
        stored = save_ai_result("discoveries", deck, picks, sets=codes, pool_size=len(pool))
        return {"discoveries": _present_discoveries(deck, stored, codes)}


def _present_new_commanders(stored: dict | None, current_codes: list[str] | None, decks: list[Deck]) -> dict | None:
    """The stored commander picks, with `current` saying whether they were
    written for the newest sets and for the decks as they are now — a new deck
    changes what the player enjoys, so it is worth looking again."""
    if stored is None:
        return None
    return {
        "generated_at": stored["generated_at"],
        "sets": stored["sets"],
        "current": current_codes is not None
        and sorted(stored["sets"]) == sorted(current_codes)
        and stored.get("decks") == sorted(d.commander for d in decks if d.commander),
        "picks": stored["picks"],
    }


# One look at a time, same reasoning as the per-deck one: a second request waits
# for the first and finds the picks already current.
_commander_lock = threading.Lock()


@app.post("/commanders/new/refresh")
def refresh_new_commanders_endpoint(force: bool = False) -> dict:
    with _commander_lock:
        latest = latest_sets()
        if latest is None:
            raise HTTPException(status_code=502, detail="Couldn't reach Scryfall to find the newest sets. Try again.")
        codes = _codes(latest)
        decks = [d for d in list_decks() if d.commander]

        stored = load_new_commanders()
        if stored and not force and _present_new_commanders(stored, codes, decks)["current"]:
            return {"commanders": _present_new_commanders(stored, codes, decks)}

        pool = new_commander_pool(codes)
        if pool is None:
            raise HTTPException(status_code=502, detail="Couldn't reach Scryfall to load the new commanders. Try again.")
        # Cards already shown to this player as additions for their decks.
        shown = {
            p["name"] for d in decks for p in (load_ai_result("discoveries", d.id) or {"items": []})["items"]
        }
        picks = _generate(lambda: pick_commanders(decks, pool, shown)) if pool else []

        # What EDHREC players do with each — real numbers, not the model's claims.
        for pick in picks:
            includes = get_commander_includes(pick["name"])
            if includes.get("available"):
                pick["edhrec_decks"] = includes["num_decks"]
                pick["pairs_with"] = [
                    c["name"] for c in sorted(includes["cards"], key=lambda c: -c["synergy"]) if c["synergy"] > 0
                ][:4]
            else:
                pick["edhrec_decks"], pick["pairs_with"] = None, []

        stored = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "sets": codes,
            "decks": sorted(d.commander for d in decks),
            "pool_size": len(pool),
            "picks": picks,
        }
        save_new_commanders(stored)
        return {"commanders": _present_new_commanders(stored, codes, decks)}


# -- the new-deck helper ------------------------------------------------------


def _wizard_colors(colors: str) -> str:
    try:
        return wizard.canonical_colors(colors)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))


@app.get("/wizard/themes")
def wizard_themes_endpoint(colors: str, themes: str) -> dict:
    """How many commanders each of the comma-separated themes has in these colours."""
    slugs = [t for t in themes.split(",") if re.fullmatch(r"[a-z0-9-]{1,40}", t)][:60]
    return {"counts": wizard.theme_counts(_wizard_colors(colors), slugs)}


@app.get("/wizard/commanders")
def wizard_commanders_endpoint(colors: str, theme: str | None = None, bracket: int | None = None, niche: bool = False) -> dict:
    if theme is not None and not re.fullmatch(r"[a-z0-9-]{1,40}", theme):
        raise HTTPException(status_code=400, detail="unknown theme")
    if bracket is not None and bracket not in wizard.BRACKET_PAGES:
        raise HTTPException(status_code=400, detail="bracket must be 1-4")
    return wizard.candidates(_wizard_colors(colors), theme, bracket, niche)


def _starter_list(
    commander: str,
    bracket: int,
    budget: float | None,
    caps: dict[str, float] | None = None,
    invest: list[str] | None = None,
    include: list[str] | None = None,
    avoid: list[str] | None = None,
) -> dict:
    if budget is not None and not 10 <= budget <= 10000:
        raise HTTPException(status_code=400, detail="budget must be between $10 and $10,000")
    if any(cap > 10000 for cap in (caps or {}).values()):
        raise HTTPException(status_code=400, detail="a spending limit can't be more than $10,000")
    try:
        return wizard.starter_list(commander, bracket, budget, caps, invest, include, avoid)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))
    except wizard.WizardDataError as err:
        raise HTTPException(status_code=502, detail=str(err))


def _parse_caps(caps: str | None) -> dict[str, float]:
    """"lands:35,rocks:20" -> {"lands": 35.0, "rocks": 20.0}."""
    parsed: dict[str, float] = {}
    for part in filter(None, (caps or "").split(",")):
        area, _, amount = part.partition(":")
        try:
            parsed[area.strip()] = float(amount)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"{part!r} isn't a spending limit like lands:35")
    return parsed


@app.get("/wizard/preview")
def wizard_preview_endpoint(
    commander: str, bracket: int, budget: float | None = None, caps: str | None = None, invest: str | None = None
) -> dict:
    return _starter_list(commander, bracket, budget, _parse_caps(caps), [a for a in (invest or "").split(",") if a])


class BuildBrief(BaseModel):
    """What the player gave the new-deck page (every part optional) and said in their
    own words, for the Doctor to build a deck from."""

    text: str = Field(default="", max_length=1000)
    # The styles the form offers, as the names the backend recognises.
    styles: list[str]
    colors: list[str] = []
    colorless: bool = False
    theme: str | None = None
    bracket: int | None = None
    # A dollar cap, "none" for no limit, or null for no preference.
    budget: float | Literal["none"] | None = None
    caps: dict[str, float] = {}
    invest: list[str] = []
    lesser_known: bool = False
    commander: str | None = None


@app.exception_handler(deck_builder.BuildError)
def build_error_handler(request: Request, exc: deck_builder.BuildError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"detail": exc.detail, "code": "build_error"})


@app.post("/builds")
def start_build_endpoint(brief: BuildBrief) -> dict:
    """Starts building a deck with the Doctor, phase by phase, from the brief. The
    page follows it with GET /builds/{id}; nothing becomes a deck until /create."""
    if brief.theme is not None and not re.fullmatch(r"[a-z0-9-]{1,40}", brief.theme):
        raise HTTPException(status_code=400, detail="unknown theme")
    if brief.bracket is not None and brief.bracket not in wizard.BRACKET_PAGES:
        raise HTTPException(status_code=400, detail="bracket must be 1-4")
    if isinstance(brief.budget, float) and not 10 <= brief.budget <= 10000:
        raise HTTPException(status_code=400, detail="budget must be between $10 and $10,000")
    if any(len(c) != 1 or c not in "WUBRG" for c in brief.colors):
        raise HTTPException(status_code=400, detail="unknown color")
    if any(cap > 10000 for cap in brief.caps.values()):
        raise HTTPException(status_code=400, detail="a spending limit can't be more than $10,000")
    try:
        wizard._check_spend(brief.caps, brief.invest)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))
    payload = {**brief.model_dump(), "styles": [s for s in brief.styles if re.fullmatch(r"[a-z0-9-]{1,40}", s)][:80]}
    return {"id": deck_builder.create(payload)}


@app.get("/builds/{build_id}")
def get_build_endpoint(build_id: str) -> dict:
    return deck_builder.public(deck_builder.get(build_id))


class BuildCommanderRequest(BaseModel):
    name: str


class Rejection(BaseModel):
    name: str
    reason: str = Field(default="", max_length=200)


class BuildRefineRequest(BaseModel):
    """The player's answer to the commanders offered: more about what they want, commanders
    that aren't it (with why), ones that are close, facts to take back."""

    text: str = Field(default="", max_length=600)
    reject: list[Rejection] = []
    like: list[str] = []
    drop: list[str] = []


@app.post("/builds/{build_id}/commander/refine")
def build_refine_endpoint(build_id: str, request: BuildRefineRequest) -> dict:
    deck_builder.refine_commanders(build_id, request.text, [r.model_dump() for r in request.reject], request.like, request.drop)
    return deck_builder.public(deck_builder.get(build_id))


@app.post("/builds/{build_id}/commander")
def build_commander_endpoint(build_id: str, request: BuildCommanderRequest) -> dict:
    deck_builder.choose_commander(build_id, request.name)
    return deck_builder.public(deck_builder.get(build_id))


@app.post("/builds/{build_id}/begin")
def build_begin_endpoint(build_id: str) -> dict:
    deck_builder.begin(build_id)
    return deck_builder.public(deck_builder.get(build_id))


class BuildLockRequest(BaseModel):
    keep: list[str]


@app.post("/builds/{build_id}/phases/{phase_id}/lock")
def build_lock_endpoint(build_id: str, phase_id: str, request: BuildLockRequest) -> dict:
    deck_builder.lock_phase(build_id, phase_id, request.keep)
    return deck_builder.public(deck_builder.get(build_id))


class BuildRedoRequest(BaseModel):
    remove: list[str] = []
    note: str = Field(default="", max_length=400)


@app.post("/builds/{build_id}/phases/{phase_id}/redo")
def build_redo_endpoint(build_id: str, phase_id: str, request: BuildRedoRequest) -> dict:
    deck_builder.redo_phase(build_id, phase_id, request.remove, request.note)
    return deck_builder.public(deck_builder.get(build_id))


@app.post("/builds/{build_id}/retry")
def build_retry_endpoint(build_id: str) -> dict:
    deck_builder.retry(build_id)
    return deck_builder.public(deck_builder.get(build_id))


@app.post("/builds/{build_id}/create")
def build_create_deck_endpoint(build_id: str) -> dict:
    """Makes the deck from a finished build, with the Doctor's account of how it was
    built as the first messages of its Correspondence tab. Once only: asking again
    returns the deck already made."""
    with deck_builder.session_lock(build_id):
        s = deck_builder.get(build_id)
        if s["deck_id"]:
            return {"deck": load_deck(s["deck_id"]), "added": 0, "failed": []}
        if s["stage"] != "review":
            raise HTTPException(status_code=409, detail="Finish the phases first.")
        deck = create_deck()
        started = set_commander(deck, s["commander"]["name"])
        if "error" in started:
            delete_deck(deck.id)
            raise HTTPException(status_code=400, detail=started["error"])
        outcome = add_cards(deck, deck_builder.final_cards(s))
        save_messages(deck, deck_builder.conversation(s))
        deck_builder.mark_done(build_id, deck.id)
        return {"deck": deck, "added": len(outcome["added"]), "failed": outcome["failed"]}


class WizardExplainRequest(BaseModel):
    colors: str
    theme: str | None = None
    bracket: int | None = None
    budget: float | None = None
    niche: bool = False


@app.post("/wizard/explain")
def wizard_explain_endpoint(request: WizardExplainRequest) -> dict:
    """One sentence per commander on why it suits the answers — for the
    commanders the answers give, worked out here, never taken from the client.
    Kept for a day per answer set, so asking again costs nothing."""
    colors = _wizard_colors(request.colors)
    if request.theme is not None and not re.fullmatch(r"[a-z0-9-]{1,40}", request.theme):
        raise HTTPException(status_code=400, detail="unknown theme")
    if request.bracket is not None and request.bracket not in wizard.BRACKET_PAGES:
        raise HTTPException(status_code=400, detail="bracket must be 1-4")
    result = wizard.candidates(colors, request.theme, request.bracket, request.niche)
    if result["unavailable"] or not result["commanders"]:
        raise HTTPException(status_code=502, detail="There are no commanders to explain right now.")
    names = [c["name"] for c in result["commanders"]]
    key = "explain:" + hashlib.sha1(json.dumps([colors, request.theme, request.bracket, request.budget, request.niche, names]).encode()).hexdigest()
    reasons = wizard.cached_get(key)
    if reasons is None:
        answers = wizard.answers_in_words(colors, request.theme, request.bracket, request.budget, request.niche)
        reasons = _generate(lambda: explain_commanders(answers, wizard.explain_context(result)))
        if reasons:
            wizard.cached_put(key, reasons)
    return {"reasons": reasons}


class WizardBuildRequest(BaseModel):
    commander: str
    bracket: int
    budget: float | None = None
    caps: dict[str, float] = {}
    invest: list[str] = []


@app.post("/wizard/build")
def wizard_build_endpoint(request: WizardBuildRequest) -> dict:
    """Creates the deck: the commander, then the starting list the preview
    showed — rebuilt here from the answers, never taken from the client, and
    every card validated like any other add."""
    commander = request.commander
    plan = _starter_list(commander, request.bracket, request.budget, request.caps, request.invest)
    deck = create_deck()
    started = set_commander(deck, commander)
    if "error" in started:
        delete_deck(deck.id)
        raise HTTPException(status_code=400, detail=started["error"])
    outcome = add_cards(deck, [c["name"] for c in plan["cards"] for _ in range(c["quantity"])])
    return {"deck": deck, "added": len(outcome["added"]), "failed": outcome["failed"], "notes": plan["notes"]}


# Orders shown on the landing page. A handful, on purpose: a short list the
# Doctor stands behind, not an inbox.
MAX_ORDERS = 3


def _deck_title(deck: Deck) -> str:
    return deck.name or deck.commander or "Untitled deck"


# Everything the landing page shows, in one read: the Doctor's best moves
# across all decks, and a summary of each deck. Reads only what is stored or
# cached — it never spends tokens and never waits on the network, so it is as
# fast as the files it reads.
#
# Ranking is a heuristic for now. Each deck's own order is respected (the
# review lists its best swap first); across decks, every deck's first swap
# comes before any deck's second, and within a rank the replacement more
# EDHREC decks run goes first. Nothing yet weighs how much a swap helps one
# deck against another.
@app.get("/hub")
def hub_endpoint() -> dict:
    latest = latest_sets()
    decks, candidates = [], []
    for deck in list_decks():
        includes = peek_commander_includes(deck.commander) if deck.commander else {"available": False}
        by_name = {c["name"]: c for c in includes["cards"]} if includes.get("available") else {}
        commander_info = peek_card_info(deck.commander) if deck.commander else None
        price = sum(float((peek_card_info(n) or {}).get("priceUsd") or 0) for n in [*deck.cards, deck.commander or ""])
        cuts = _present_cuts(deck, load_ai_result("cuts", deck.id)).cuts

        decks.append(
            {
                "id": deck.id,
                "title": _deck_title(deck),
                "commander": deck.commander,
                "commander_id": (commander_info or {}).get("id"),
                "color_identity": deck.commander_color_identity,
                "card_count": len(deck.cards) + (1 if deck.commander else 0),
                "price_usd": round(price, 2),
                "updated_at": deck.updated_at,
                "discoveries": _present_discoveries(deck, load_ai_result("discoveries", deck.id), _codes(latest)),
                "review": (
                    {
                        "swaps": len(cuts["swaps"]),
                        "kept": len(cuts["kept"]),
                        "generated_at": cuts["generated_at"],
                        "deck_changed": cuts["deck_changed"],
                    }
                    if cuts
                    else None
                ),
            }
        )
        for rank, swap in enumerate((cuts or {}).get("swaps", [])):
            add = by_name.get(swap["add"]) or {}
            cut = by_name.get(swap["cut"])
            candidates.append(
                {
                    **swap,
                    "deck_id": deck.id,
                    "deck_title": _deck_title(deck),
                    "rank_in_deck": rank,
                    "cut_id": (peek_card_info(swap["cut"]) or {}).get("id"),
                    "cut_inclusion": cut["inclusion"] if cut else None,
                    "add_inclusion": add.get("inclusion"),
                    "add_synergy": add.get("synergy"),
                    "deck_changed": cuts["deck_changed"],
                }
            )

    candidates.sort(key=lambda o: (o["rank_in_deck"], -(o["add_inclusion"] or 0)))
    return {
        "latest_sets": latest,
        "commanders": _present_new_commanders(load_new_commanders(), _codes(latest), [d for d in list_decks() if d.commander]),
        "orders": candidates[:MAX_ORDERS],
        "more_swaps": max(0, len(candidates) - MAX_ORDERS),
        "decks": decks,
    }


# The commander's name is a query param, not a path segment, same
# reasoning as every other name-keyed endpoint here.
@app.get("/edhrec/commander")
def get_commander_includes_endpoint(name: str) -> dict:
    includes = get_commander_includes(name)
    # EDHREC's own Game Changer flag never appears on its commander pages, so
    # mark them from Scryfall's list (left as EDHREC had it if that can't be read).
    flagged = wizard.game_changer_names()
    if includes.get("available") and flagged is not None:
        for card in includes["cards"]:
            card["game_changer"] = card["name"] in flagged
    return includes


class CollectionResponse(BaseModel):
    cards: list[str]


class BulkCollectionRequest(BaseModel):
    names: list[str]


@app.get("/collection")
def get_collection_endpoint() -> CollectionResponse:
    return CollectionResponse(cards=load_collection())


@app.post("/collection")
def add_to_collection_endpoint(request: CardNameRequest) -> CollectionResponse:
    return CollectionResponse(cards=add_to_collection(request.name))


@app.post("/collection/bulk")
def add_many_to_collection_endpoint(request: BulkCollectionRequest) -> CollectionResponse:
    return CollectionResponse(cards=add_many_to_collection(request.names))


@app.delete("/collection")
def remove_from_collection_endpoint(name: str) -> CollectionResponse:
    return CollectionResponse(cards=remove_from_collection(name))


class CardInfoResponse(BaseModel):
    info: dict | None


class CardInfoBatchRequest(BaseModel):
    names: list[str]
    refresh: bool = False


class CardInfoBatchResponse(BaseModel):
    info: dict[str, dict]
    # Confirmed Scryfall 404s (genuinely not a real card / a typo) versus
    # names a lookup attempt simply failed on (almost always the rate
    # limit) — see card_cache.get_card_info_batch's own docstring for why
    # this distinction matters.
    not_found: list[str]
    failed: list[str]


# name is a query param, not a path segment, same reasoning as every other
# card-name endpoint here — split-card names contain "//".
@app.get("/cards")
def get_card_info_endpoint(name: str, refresh: bool = False) -> CardInfoResponse:
    return CardInfoResponse(info=get_card_info(name, refresh=refresh))


# `null` in either response means the lookup failed and nothing was cached
# to fall back on — distinct from an empty list, which is a real answer
# ("this card has no rulings"). The frontend renders the two differently.
@app.get("/cards/rulings")
def get_rulings_endpoint(id: str) -> dict:
    return {"rulings": get_rulings(id)}


@app.get("/cards/printings")
def get_printings_endpoint(name: str) -> dict:
    return {"printings": get_printings(name)}


@app.post("/cards/batch")
def get_card_info_batch_endpoint(request: CardInfoBatchRequest) -> CardInfoBatchResponse:
    result = get_card_info_batch(request.names, refresh=request.refresh)
    return CardInfoBatchResponse(**result)
