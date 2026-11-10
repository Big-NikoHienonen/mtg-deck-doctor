# Backlog

Work that's agreed but not started. Each ticket has an ID, a status, and enough context to pick it up cold. Newest at the top. Move a ticket to "Done" with the date and commit when it ships.

Statuses: `todo`, `in progress`, `blocked`.

## Open

### MDD-1: Browse all new cards from the latest sets

Status: `todo`  
Added: 2026-11-10  
Area: front page (`frontend/src/HubView.tsx`, `NewCards.tsx`), `src/mtg_deck_doctor/new_cards.py`

**Problem.** The front page shows the Doctor's picks from the newest sets, per deck. The picks are good, but they're a short curated list. There's no way to go and see every new card from a set, which is what you want to do when a set releases.

**What exists today.**

- `latest_sets()` in `new_cards.py` finds the newest releases (set codes, titles, release dates) and returns them in `/hub` as `latest_sets`.
- `new_card_pool(set_codes, color_identity)` and `new_commander_pool(set_codes)` fetch every non-reprint, Commander-legal card from those sets, cached for `CACHE_TTL_SECONDS`. The Doctor picks from these pools, but nothing shows the pools themselves.
- `/search/results?q=<Scryfall query>` already renders a paged, sortable card grid. It reads `q` from the URL, so a link with the right query works with no new page.
- `frontend/src/releases.ts` gives each release a display name.

**Options.**

1. **Link to the existing results page (smallest).** Add a "See all new cards" link on the front page for each release, pointing at `/search/results?q=(set:abc or set:def) -is:reprint legal:commander`. No backend work. The grid has no "why it fits your decks" context.
2. **A dedicated "New cards" page.** A route such as `/new-cards` with one tab or section per release (main set and its Commander set together), a filter by color identity, type, and a toggle for reprints, and a marker on each card the Doctor picked for one of your decks. Reuses `new_card_pool` plus the results grid.
3. **Option 2, plus per-deck fit.** A "fits your decks" filter, so you can look at the whole set and narrow it to cards legal in a chosen deck's color identity. Builds on `new_card_pool`'s `color_identity` argument.

Start with option 1 to see if it's enough, and move to 2 if it isn't.

**Open questions.**

- Do you want the Commander set's cards (precon-only cards) mixed in with the main set, or on their own?
- Should reprints show? `new_card_pool` excludes them today; the "all cards from the set" reading of this ticket may include them.
- How many releases back should the page cover? `latest_sets()` currently returns a handful.

**Done when.** From the front page you reach a list of every new card in the latest set in one click, can sort and filter it, and can open any card from it.

## Done

Nothing yet.
