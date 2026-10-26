import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  addCard,
  addToCollection,
  bulkAddCards,
  getCardInfo,
  getCollection,
  listDecks,
  removeCard,
  removeFromCollection,
  scryfallSearchCards,
  scryfallSearchOwnedCards,
  type CardInfo,
  type Deck,
  type SearchCard,
  type SortDir,
  type SortOrder,
} from "./api";
import CardModal from "./CardModal";
import CardImage from "./CardImage";
import { loadSelectedPrintings, saveSelectedPrinting, type SelectedPrinting } from "./printings";
import { isAddableToDeck } from "./searchQuery";
import { buttonStyle, eyebrowStyle } from "./styles";

const SORT_FIELDS: { value: SortOrder; label: string }[] = [
  { value: "color", label: "Color" },
  { value: "name", label: "Name" },
  { value: "usd", label: "Price" },
];

// "Only my collection" reuses this same results page/grid/pagination, but
// paginates over the *complete* owned∩query intersection (computed up
// front by scryfallSearchOwnedCards) rather than paginating Scryfall's
// own base query and filtering each page down to owned cards — the
// latter can show an empty page even though real matches exist further
// in, which is confusing (you'd have to click "Next" blind, hoping a
// later page has something). Same page size as Scryfall's own for a
// consistent feel.
const LOCAL_PAGE_SIZE = 175;

const WUBRG = ["W", "U", "B", "R", "G"];

// Approximates Scryfall's own order=color (WUBRG, colorless first) —
// "only my collection" results are merged from several chunked queries
// and always re-sorted locally rather than trusting any one chunk's own
// order, so this is what actually determines the on-screen order. Good
// enough for browsing a personal collection, not guaranteed to break
// multicolor ties identically to Scryfall's own undocumented algorithm.
function colorSortKey(identity: string[]): string {
  if (identity.length === 0) return "0";
  if (identity.length === 1) return `1${WUBRG.indexOf(identity[0])}`;
  return `2${WUBRG.filter((c) => identity.includes(c)).join("")}`;
}

function sortLocalCards(cards: SearchCard[], order: SortOrder, dir: SortDir): SearchCard[] {
  const sorted = [...cards].sort((a, b) => {
    let cmp: number;
    if (order === "usd") cmp = (parseFloat(a.priceUsd ?? "0") || 0) - (parseFloat(b.priceUsd ?? "0") || 0);
    else if (order === "color")
      cmp = colorSortKey(a.colorIdentity).localeCompare(colorSortKey(b.colorIdentity)) || a.name.localeCompare(b.name);
    else cmp = a.name.localeCompare(b.name);
    return dir === "asc" ? cmp : -cmp;
  });
  return sorted;
}

export default function CardSearchResultsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const query = searchParams.get("q") ?? "";
  const deckId = searchParams.get("deck") ?? "";
  const showIllegal = searchParams.get("showIllegal") === "1";
  const onlyCollection = searchParams.get("collection") === "1";
  const page = parseInt(searchParams.get("page") ?? "1", 10) || 1;
  const order = (searchParams.get("order") as SortOrder | null) ?? "color";
  const dir = (searchParams.get("dir") as SortDir | null) ?? "asc";

  const [decks, setDecks] = useState<Deck[]>([]);
  const [modalDeckId, setModalDeckId] = useState(deckId);
  const [selectedPrintings, setSelectedPrintings] = useState<Record<string, SelectedPrinting>>({});
  const [ownedCards, setOwnedCards] = useState<Set<string>>(new Set());
  const [collectionLoaded, setCollectionLoaded] = useState(false);
  const [cards, setCards] = useState<SearchCard[] | null>(null);
  const [totalCards, setTotalCards] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [openCard, setOpenCard] = useState<SearchCard | null>(null);
  const [openInfo, setOpenInfo] = useState<CardInfo | undefined>(undefined);

  useEffect(() => {
    listDecks().then(setDecks);
    getCollection()
      .then((names) => setOwnedCards(new Set(names)))
      .catch(() => {
        // Non-critical — badges just won't reflect reality if this fails.
      })
      .finally(() => setCollectionLoaded(true));
  }, []);

  // Which deck's saved printing choices apply to the currently-open modal
  // — follows modalDeckId (the modal's own deck-picker), not the page's
  // fixed `deckId`, so switching decks inside an open modal picks up that
  // deck's real choices instead of stale ones.
  useEffect(() => {
    setSelectedPrintings(modalDeckId ? loadSelectedPrintings(modalDeckId) : {});
  }, [modalDeckId]);

  const deck = decks.find((d) => d.id === deckId) ?? null;
  const modalDeck = decks.find((d) => d.id === modalDeckId) ?? null;

  // "Only my collection": fetch the complete owned∩query intersection up
  // front (one Scryfall request per chunk of the collection — see
  // scryfallSearchOwnedCards), then sort/paginate it locally, so every
  // page shown is guaranteed to have real matches when any exist at all.
  const ownedKey = Array.from(ownedCards).sort().join("\u0000");
  useEffect(() => {
    if (!onlyCollection || !collectionLoaded) return;
    setLoading(true);
    setError(null);
    scryfallSearchOwnedCards(query, Array.from(ownedCards))
      .then((matches) => {
        const sorted = sortLocalCards(matches, order, dir);
        const start = (page - 1) * LOCAL_PAGE_SIZE;
        setCards(sorted.slice(start, start + LOCAL_PAGE_SIZE));
        setTotalCards(sorted.length);
        setHasMore(start + LOCAL_PAGE_SIZE < sorted.length);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Search failed."))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onlyCollection, collectionLoaded, ownedKey, query, order, dir, page]);

  // Plain Scryfall search — the normal, non-collection path.
  useEffect(() => {
    if (onlyCollection || !query) return;
    setLoading(true);
    setError(null);
    scryfallSearchCards(query, page, order, dir)
      .then((result) => {
        setCards(result.cards);
        setTotalCards(result.totalCards);
        setHasMore(result.hasMore);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Search failed."))
      .finally(() => setLoading(false));
  }, [onlyCollection, query, page, order, dir]);

  // Lazily fetched per opened card, same pattern as CardModal's own rulings
  // fetch — the search result already has id/typeLine/price, but legality
  // and oracle text aren't part of a search hit and need their own call.
  useEffect(() => {
    setOpenInfo(undefined);
    if (!openCard) return;
    let cancelled = false;
    getCardInfo(openCard.name).then((info) => {
      if (!cancelled && info) setOpenInfo(info);
    });
    return () => {
      cancelled = true;
    };
  }, [openCard]);

  const visibleCards = useMemo(() => {
    if (!cards) return null;
    let result = cards;
    if (deck && !showIllegal) result = result.filter((c) => isAddableToDeck(c, deck));
    // A no-op when onlyCollection is on — scryfallSearchOwnedCards already
    // returned only owned cards — but harmless, and cheap insurance.
    if (onlyCollection) result = result.filter((c) => ownedCards.has(c.name));
    return result;
  }, [cards, deck, showIllegal, onlyCollection, ownedCards]);

  function goToPage(next: number) {
    const params = new URLSearchParams(searchParams);
    params.set("page", String(next));
    setSearchParams(params);
    window.scrollTo({ top: 0 });
  }

  function setSort(nextOrder: SortOrder, nextDir: SortDir) {
    const params = new URLSearchParams(searchParams);
    params.set("order", nextOrder);
    params.set("dir", nextDir);
    params.set("page", "1");
    setSearchParams(params);
    window.scrollTo({ top: 0 });
  }

  function toggleOnlyCollection() {
    const params = new URLSearchParams(searchParams);
    if (onlyCollection) params.delete("collection");
    else params.set("collection", "1");
    params.set("page", "1");
    setSearchParams(params);
    window.scrollTo({ top: 0 });
  }

  function updateDeck(updated: Deck) {
    setDecks((prev) => prev.map((d) => (d.id === updated.id ? updated : d)));
  }

  async function handleAddOne() {
    if (!modalDeck || !openCard) return;
    updateDeck(await addCard(modalDeck.id, openCard.name));
  }

  async function handleAddMany(quantity: number) {
    if (!modalDeck || !openCard) throw new Error("Pick a deck first.");
    const result = await bulkAddCards(modalDeck.id, openCard.name, quantity);
    updateDeck(result.deck);
    return { added: result.added, failed: result.failed, error: result.error };
  }

  async function handleRemoveOne() {
    if (!modalDeck || !openCard) return;
    updateDeck(await removeCard(modalDeck.id, openCard.name));
  }

  async function handleRemoveAll() {
    if (!modalDeck || !openCard) return;
    const currentCount = modalDeck.cards.filter((n) => n === openCard.name).length;
    let updated = modalDeck;
    for (let i = 0; i < currentCount; i++) {
      updated = await removeCard(modalDeck.id, openCard.name);
    }
    updateDeck(updated);
  }

  function handleChangePrinting(printing: SelectedPrinting) {
    if (!modalDeckId || !openCard) return;
    setSelectedPrintings(saveSelectedPrinting(modalDeckId, openCard.name, printing));
  }

  async function handleToggleOwned() {
    if (!openCard) return;
    const cards = ownedCards.has(openCard.name)
      ? await removeFromCollection(openCard.name)
      : await addToCollection(openCard.name);
    setOwnedCards(new Set(cards));
  }

  function openCardModal(card: SearchCard) {
    setOpenCard(card);
    setModalDeckId(deckId);
  }

  const openCardIndex = openCard ? (visibleCards?.findIndex((c) => c.id === openCard.id) ?? -1) : -1;

  // Bounded by the current page's visible cards — doesn't auto-advance to
  // the next search-results page at the boundary, same reasoning as the
  // deck ledger not needing to handle a "page" concept at all.
  function handleNavigateModal(direction: "prev" | "next") {
    if (!visibleCards || openCardIndex < 0) return;
    const next = visibleCards[direction === "prev" ? openCardIndex - 1 : openCardIndex + 1];
    if (next) openCardModal(next);
  }

  const totalPages = Math.max(1, Math.ceil(totalCards / 175));
  const openCount = modalDeck && openCard ? modalDeck.cards.filter((n) => n === openCard.name).length : undefined;
  const deckOptions = decks.map((d) => ({ id: d.id, label: d.name ?? d.commander ?? "Untitled deck" }));

  // onlyCollection's own count is always the true total now (the full
  // intersection is fetched up front), so it doesn't need a "this page"
  // qualifier — only the deck-legality filter still needs one, since
  // that's still a per-page client-side narrowing on top of a real
  // Scryfall page.
  const activeFilterLabels: string[] = [];
  if (deck && !showIllegal) activeFilterLabels.push("fit this deck");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <header>
        <Link
          to={`/search${deckId ? `?deck=${deckId}` : ""}`}
          style={{ ...eyebrowStyle, textDecoration: "none", display: "inline-block" }}
        >
          &larr; REFINE SEARCH
        </Link>
        <div style={{ fontSize: 22, fontWeight: 600, marginTop: 4 }}>
          {loading
            ? "Searching…"
            : activeFilterLabels.length > 0
              ? `${visibleCards?.length ?? 0} of ${cards?.length ?? 0} on this page ${activeFilterLabels.join(" and ")}`
              : onlyCollection
                ? `${totalCards} card${totalCards === 1 ? "" : "s"} in your collection`
                : `${totalCards} card${totalCards === 1 ? "" : "s"} found`}
        </div>
      </header>

      <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={eyebrowStyle}>SORT BY</div>
          <div style={{ display: "flex", gap: 6 }}>
            {SORT_FIELDS.map((f) => (
              <button
                key={f.value}
                onClick={() => setSort(f.value, dir)}
                className="btn"
                style={
                  order === f.value
                    ? { ...buttonStyle, borderColor: "var(--accent)", color: "var(--accent)" }
                    : buttonStyle
                }
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <button
            onClick={() => setSort(order, "asc")}
            className="btn"
            style={dir === "asc" ? { ...buttonStyle, borderColor: "var(--accent)", color: "var(--accent)" } : buttonStyle}
          >
            Ascending
          </button>
          <button
            onClick={() => setSort(order, "desc")}
            className="btn"
            style={dir === "desc" ? { ...buttonStyle, borderColor: "var(--accent)", color: "var(--accent)" } : buttonStyle}
          >
            Descending
          </button>
        </div>
        <button
          onClick={toggleOnlyCollection}
          className="btn"
          style={onlyCollection ? { ...buttonStyle, borderColor: "var(--accent)", color: "var(--accent)" } : buttonStyle}
        >
          Only my collection
        </button>
      </div>

      {error && <div style={{ color: "var(--danger)", fontSize: 14 }}>{error}</div>}

      {visibleCards && visibleCards.length === 0 && !loading && (
        <div style={{ color: "var(--text-muted)", fontSize: 14 }}>
          {onlyCollection && collectionLoaded && ownedCards.size === 0
            ? "No cards in your collection yet — open a card's details and mark it \"In my collection\" to add it here."
            : "No matching cards."}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 18 }}>
        {visibleCards?.map((card) => (
          <div
            key={card.id}
            className="card-tile"
            onClick={() => openCardModal(card)}
            style={{ cursor: "pointer", position: "relative" }}
          >
            <CardImage
              cardId={card.id}
              printing={selectedPrintings[card.name]}
              version="normal"
              alt={card.name}
              title={card.name}
              loading="lazy"
              style={{ width: "100%", display: "block", borderRadius: 10, border: "1px solid var(--border)" }}
            />
            {!onlyCollection && ownedCards.has(card.name) && (
              <div
                style={{
                  position: "absolute",
                  bottom: 6,
                  left: 6,
                  padding: "1px 7px",
                  borderRadius: 10,
                  background: "rgba(0, 0, 0, 0.65)",
                  color: "#fff",
                  fontSize: 12,
                  fontWeight: 600,
                }}
              >
                ✓ Owned
              </div>
            )}
          </div>
        ))}
      </div>

      {cards && (
        <div style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: 16, marginTop: 8 }}>
          <button
            onClick={() => goToPage(page - 1)}
            disabled={page <= 1 || loading}
            className="btn"
            style={buttonStyle}
          >
            ‹ Prev
          </button>
          <div style={{ fontSize: 13, color: "var(--text-muted)" }}>
            Page {page} of {totalPages}
          </div>
          <button onClick={() => goToPage(page + 1)} disabled={!hasMore || loading} className="btn" style={buttonStyle}>
            Next ›
          </button>
        </div>
      )}

      {openCard && (
        <CardModal
          name={openCard.name}
          cardId={openCard.id}
          count={openCount}
          info={openInfo}
          printing={modalDeckId ? selectedPrintings[openCard.name] : undefined}
          onChangePrinting={modalDeckId ? handleChangePrinting : undefined}
          onAddOne={modalDeck ? handleAddOne : undefined}
          onAddMany={modalDeck ? handleAddMany : undefined}
          onRemoveOne={modalDeck ? handleRemoveOne : undefined}
          onRemoveAll={modalDeck ? handleRemoveAll : undefined}
          deckOptions={deckOptions}
          selectedDeckId={modalDeckId}
          onSelectDeckId={setModalDeckId}
          owned={ownedCards.has(openCard.name)}
          onToggleOwned={handleToggleOwned}
          onNavigate={handleNavigateModal}
          hasPrevious={openCardIndex > 0}
          hasNext={openCardIndex >= 0 && !!visibleCards && openCardIndex < visibleCards.length - 1}
          onClose={() => setOpenCard(null)}
        />
      )}
    </div>
  );
}
