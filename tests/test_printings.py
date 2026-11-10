"""Tests for the printings lookup behind the Change printing picker: the fields each printing
carries for the picker's search, and the cache. Scryfall is stubbed, so no network. Run with

    uv run python tests/test_printings.py
"""

import json
import tempfile
from pathlib import Path

import httpx

import mtg_deck_doctor.card_details as C

C.PRINTINGS_PATH = Path(tempfile.mkdtemp()) / "printings_cache.json"
results: list[bool] = []


def check(name: str, ok: object, detail: str = "") -> None:
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


class Reply:
    def __init__(self, status: int, data: list[dict], next_page: str | None = None):
        self.status_code, self._data, self._next = status, data, next_page

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad", request=httpx.Request("GET", "x"), response=httpx.Response(self.status_code))

    def json(self) -> dict:
        return {"data": self._data, "has_more": self._next is not None, **({"next_page": self._next} if self._next else {})}


CARDS = [
    {"id": "aaa", "set_name": "Commander Legends", "set": "cmr", "collector_number": "472", "released_at": "2020-11-20", "prices": {"usd": "1.20", "usd_foil": "3.40"},
     "border_color": "borderless", "frame_effects": ["inverted"], "finishes": ["nonfoil", "foil"]},
    {"id": "bbb", "set_name": "Secret Lair Drop", "set": "sld", "collector_number": "1234a", "released_at": "2021-03-01", "prices": {"usd_foil": "9.99"},
     "frame_effects": ["showcase", "extendedart"], "full_art": True, "promo": True, "promo_types": ["bundle", "unheard-of"], "finishes": ["foil"]},
    {"id": "ccc", "set_name": "Alpha", "set": "lea", "collector_number": "269", "released_at": "1993-08-05", "finishes": ["nonfoil"]},
    {"id": "ddd", "set_name": "Strixhaven Mystical Archive", "set": "sta", "collector_number": "9", "released_at": "2021-04-23", "prices": {"usd_etched": "7.50"}, "finishes": ["etched"]},
]
calls: list[dict] = []
urls: list[str] = []
reply = Reply(200, CARDS)
pages: list[Reply | Exception] | None = None  # When set, each ask takes the next one.


def fake_get(url: str, params: dict | None = None) -> Reply:
    calls.append(params or {})
    urls.append(url)
    answer = pages.pop(0) if pages is not None else reply
    if isinstance(answer, Exception):
        raise answer
    return answer


C._get = fake_get

got = C.get_printings("Sol Ring")
check("each printing keeps its id, set name, set code, number, date, prices and finishes", got[0] == {
    "id": "aaa", "setName": "Commander Legends", "set": "cmr", "collectorNumber": "472", "releasedAt": "2020-11-20", "priceUsd": "1.20",
    "priceUsdFoil": "3.40", "finishes": ["nonfoil", "foil"], "treatments": ["Borderless"],
}, str(got[0]))
check("a foil-only printing has a foil price and no regular one, not an error", got[1]["priceUsd"] is None and got[1]["priceUsdFoil"] == "9.99" and got[1]["finishes"] == ["foil"])
check("an etched-only printing's foil price is its etched price", got[3]["priceUsdFoil"] == "7.50" and got[3]["finishes"] == ["etched"])
check("a printing that doesn't come in foil has no foil price", got[2]["priceUsdFoil"] is None and got[2]["finishes"] == ["nonfoil"])
check("showcase, extended art, full art, promo, bundle and foil-only are all named, in that order; unknown promo types are left out",
      got[1]["treatments"] == ["Showcase", "Extended art", "Full art", "Promo", "Bundle", "Foil only"], str(got[1]["treatments"]))
check("a plain printing has no treatments", got[2]["treatments"] == [])
check("a printing only sold as an etched foil says so", got[3]["treatments"] == ["Etched only"])
check("a printing sold as nonfoil and foil is not called foil-only", "Foil only" not in got[0]["treatments"])

check("it asks Scryfall once, by exact name, newest first, every printing", len(calls) == 1 and calls[0] == {"q": '!"Sol Ring"', "unique": "prints", "order": "released", "dir": "desc"}, str(calls))
C.get_printings("Sol Ring")
check("the second ask is served from the cache", len(calls) == 1)

saved = json.loads(C.PRINTINGS_PATH.read_text())
check("the cache key carries the version, so lists cached before a field was added aren't served", list(saved) == [f"v{C.PRINTINGS_CACHE_VERSION}:Sol Ring"], str(list(saved)))

# A list cached under the old, unversioned key is ignored.
C.PRINTINGS_PATH.write_text(json.dumps({"Arcane Signet": {"fetchedAt": 9e12, "data": [{"id": "old"}]}}))
reply = Reply(200, CARDS[:1])
fresh = C.get_printings("Arcane Signet")
check("an old unversioned entry is not used", fresh is not None and fresh[0]["id"] == "aaa" and "treatments" in fresh[0])

reply = Reply(404, [])
check("a card Scryfall doesn't know is an empty list, a real answer", C.get_printings("Zzz Not A Card") == [])

reply = httpx.ConnectError("down")
check("a failed lookup with nothing cached is None, not an empty list", C.get_printings("Brainstorm") is None)
C.PRINTINGS_PATH.write_text(json.dumps({f"v{C.PRINTINGS_CACHE_VERSION}:Brainstorm": {"fetchedAt": 0, "data": [{"id": "stale"}]}}))
stale = C.get_printings("Brainstorm")
check("...but an expired entry is served when the lookup fails", stale == [{"id": "stale"}], str(stale))

# A card with more printings than one results page holds (a basic land): every page is read.
def card(i: int, set_code: str = "xxx") -> dict:
    return {"id": f"id{i}", "set_name": f"Set {i}", "set": set_code, "collector_number": str(i), "released_at": "2020-01-01"}


NEXT_2, NEXT_3 = "https://api.scryfall.com/cards/search?page=2&q=x", "https://api.scryfall.com/cards/search?page=3&q=x"
calls.clear(), urls.clear()
pages = [Reply(200, [card(1), card(2)], NEXT_2), Reply(200, [card(3), card(4)], NEXT_3), Reply(200, [card(5, "neo")])]
forest = C.get_printings("Forest")
check("every page is read and the order is kept", [p["id"] for p in forest] == ["id1", "id2", "id3", "id4", "id5"], str([p["id"] for p in forest]))
check("a printing from the last page, the oldest, is there", forest[-1]["set"] == "neo")
check("the first ask has the search params; the next ones follow next_page with none", urls == ["https://api.scryfall.com/cards/search", NEXT_2, NEXT_3] and calls[0]["q"] == '!"Forest"' and calls[1:] == [{}, {}], str(urls))
calls.clear()
C.get_printings("Forest")
check("the whole list is cached as one entry", calls == [])

# A page that fails part way: no cut-short list, none cached.
pages = [Reply(200, [card(1)], NEXT_2), httpx.ReadTimeout("slow")]
check("a later page that fails fails the lookup instead of returning half the list", C.get_printings("Island") is None)
check("...and nothing is cached for it", f"v{C.PRINTINGS_CACHE_VERSION}:Island" not in json.loads(C.PRINTINGS_PATH.read_text()))

# A source that never stops saying there is more is cut off.
urls.clear()
pages = [Reply(200, [card(i)], NEXT_2) for i in range(C.MAX_PRINTING_PAGES + 5)]
endless = C.get_printings("Swamp")
check(f"paging stops at {C.MAX_PRINTING_PAGES} pages", len(urls) == C.MAX_PRINTING_PAGES and len(endless) == C.MAX_PRINTING_PAGES, str(len(urls)))
pages = None

print(f"\n{sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
