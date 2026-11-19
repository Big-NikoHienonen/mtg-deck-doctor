"""Tests for what the card cache records about mana production, and how entries cached before that was
recorded are completed. Scryfall is stubbed, so no network. Run with

    uv run python tests/test_card_cache.py
"""

import json
import tempfile
from pathlib import Path

import mtg_deck_doctor.card_cache as C

C.CACHE_PATH = Path(tempfile.mkdtemp()) / "card_cache.json"
results: list[bool] = []


def check(name: str, ok: object, detail: str = "") -> None:
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


# --- what a card can tap for ---------------------------------------------------------------------------

check("a basic land taps for its color", C._info_from_card({"produced_mana": ["G"]})["producedMana"] == ["G"])
check("a dual land taps for both, sorted", C._info_from_card({"produced_mana": ["U", "B"]})["producedMana"] == ["B", "U"])
check("a card that makes no mana has an empty list, not a missing key", C._info_from_card({"name": "Lightning Bolt"})["producedMana"] == [])
check(
    "a double-faced card's faces are combined",
    C._info_from_card({"card_faces": [{"produced_mana": ["W"]}, {"produced_mana": ["B", "W"]}]})["producedMana"] == ["B", "W"],
)
check("colorless is recorded as C", C._info_from_card({"produced_mana": ["C"]})["producedMana"] == ["C"])


# --- entries cached before it was recorded -------------------------------------------------------------


def entry(name: str, **extra) -> dict:
    info = {"id": name.lower(), "name": name, "typeLine": "Land", "priceUsd": None, "legality": "legal", "oracleText": None, "colorIdentity": [], **extra}
    return {"info": info, "fetchedAt": 1}


C.CACHE_PATH.write_text(
    json.dumps(
        {
            "Fresh": entry("Fresh", producedMana=["G"]),
            "Stale": entry("Stale"),  # Current in every other way, but cached before producedMana.
            "Ancient": {"info": {"id": "x", "name": "Ancient"}, "fetchedAt": 1},  # Missing a required field.
        }
    )
)

asked: list[list[str]] = []
answer = {"found": {}, "not_found": [], "unmatched": [], "failed": []}


def fake_collection(names: list[str]):
    asked.append(list(names))
    return (
        {n: C._info_from_card({"id": n.lower(), "name": n, "color_identity": [], "produced_mana": ["R"]}) for n in names if n not in answer["failed"] and n not in answer["not_found"]},
        [n for n in names if n in answer["not_found"]],
        [],
        [n for n in names if n in answer["failed"]],
    )


C._fetch_collection = fake_collection

first = C.get_card_info_batch(["Fresh", "Stale", "Ancient"])
check("a batch asks Scryfall again for a cached card that lacks producedMana, and for a stale one, not for a complete one", asked == [["Stale", "Ancient"]], str(asked))
check("...and every card comes back with producedMana", all("producedMana" in first["info"][n] for n in ("Fresh", "Stale", "Ancient")), str(first["info"]))
check("...and what it learned is cached", "producedMana" in json.loads(C.CACHE_PATH.read_text())["Stale"]["info"])
asked.clear()
C.get_card_info_batch(["Fresh", "Stale", "Ancient"])
check("a second batch asks for nothing", asked == [])

# Scryfall can't be reached: the old entry is still served, since it is good for everything else.
C.CACHE_PATH.write_text(json.dumps({"Stale": entry("Stale"), "Ancient": {"info": {"id": "x", "name": "Ancient"}, "fetchedAt": 1}}))
answer.update(failed=["Stale", "Ancient"], not_found=[])
down = C.get_card_info_batch(["Stale", "Ancient"])
check("when Scryfall can't be reached, the entry without producedMana is still served", "Stale" in down["info"] and "producedMana" not in down["info"]["Stale"])
check("...an entry that is unusable is reported as failed, not served", "Ancient" not in down["info"] and down["failed"] == ["Ancient"], str(down))
check("...and nothing is reported as a wrong name", down["not_found"] == [])

# Scryfall no longer has a card we already know: it is not a typo.
answer.update(failed=[], not_found=["Stale"])
gone = C.get_card_info_batch(["Stale"])
check("a cached card Scryfall says it doesn't have is served and not reported as a wrong name", "Stale" in gone["info"] and gone["not_found"] == [], str(gone))

# A name nobody has cached that Scryfall doesn't have is still a wrong name.
answer.update(failed=[], not_found=["Typo Card"])
typo = C.get_card_info_batch(["Typo Card"])
check("a name that was never cached and isn't a card is still reported as one", typo["not_found"] == ["Typo Card"] and "Typo Card" not in typo["info"], str(typo))

# A refresh still replaces everything.
C.CACHE_PATH.write_text(json.dumps({"Fresh": entry("Fresh", producedMana=["G"])}))
asked.clear()
answer.update(failed=[], not_found=[])
C.get_card_info_batch(["Fresh"], refresh=True)
check("a refresh asks for a card that is complete", asked == [["Fresh"]])

print(f"\n{sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
