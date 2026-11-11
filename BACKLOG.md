# Backlog

Work that's agreed but not started. Each ticket has an ID, a status, and enough context to pick it up cold. Newest at the top. Move a ticket to "Done" with the date and commit when it ships.

Statuses: `todo`, `in progress`, `blocked`.

## Open

Nothing open.

## Done

### MDD-1: Browse all new cards from the latest sets

Done: 2026-11-11 (option 1, plus a query box), in `3d86674`

**What shipped.**

- The front page has an "All new cards from" row with one link per release, to `/search/results?q=(set:abc or set:def) -is:reprint legal:commander`. It shows whenever the releases are known, whether or not the Doctor has picks.
- The results page has an editable Scryfall query box, so you can narrow the list ("c:b", "t:creature", "cmc<=3") or widen it (take out `-is:reprint`). A query Scryfall can't read shows its reason instead of a generic failure, and the results of the search before no longer stay on screen.
- Sorting, "Only my collection", paging, and the card details modal come from the existing results page.

**Answers to the open questions.** The Commander set is mixed in with the main set, because a release is one link; add `set:abc` in the box to see one set. Reprints are hidden, to match "new"; on Reality Fracture that is 286 cards, and 372 with reprints. The page covers the two releases `latest_sets()` returns.

**Not built.** Option 2 (a dedicated page with a section per release, a marker on the Doctor's picks) and option 3 (a per-deck "fits your decks" filter). Open a new ticket if the grid isn't enough.
