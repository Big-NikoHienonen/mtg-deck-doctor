import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import {
  addCard,
  addManyToCollection,
  addToCollection,
  bulkAddCards,
  deleteDeck,
  duplicateDeck,
  extractText,
  getCardInfoBatch,
  getCollection,
  getCommanderIncludes,
  getDeck,
  removeCard,
  removeFromCollection,
  renameDeck,
  sendMessage,
  setCommander,
  type CardInfo,
  type CommanderIncludes,
  type Deck,
} from "./api";
import { CATEGORY_ORDER, categoryFor } from "./cardCategories";
import { useAiProblem } from "./aiStatus";
import AiNotice, { useSecondsUntil } from "./AiNotice";
import CardImage from "./CardImage";
import CardModal from "./CardModal";
import CardPreview from "./CardPreview";
import CardSearchBox from "./CardSearchBox";
import CutSuggestions from "./CutSuggestions";
import { replacementPool } from "./cutRanking";
import DeckHealthPanel from "./DeckHealthPanel";
import { analyzeDeck } from "./deckHealth";
import DeckMenu from "./DeckMenu";
import ExportDecklistModal from "./ExportDecklistModal";
import { buildDecklistText } from "./importExport";
import ImportCardsModal from "./ImportCardsModal";
import ManaPips from "./ManaPips";
import {
  clearSelectedPrinting,
  loadSelectedPrintings,
  saveSelectedPrinting,
  type SelectedPrinting,
} from "./printings";
import Recommendations from "./Recommendations";
import TopIncludes from "./TopIncludes";
import { buttonStyle, eyebrowStyle, inputStyle } from "./styles";

function CardTile({
  name,
  cardId,
  count,
  printing,
  onHover,
  onOpen,
}: {
  name: string;
  cardId: string | null | undefined;
  count: number;
  printing: SelectedPrinting | undefined;
  onHover: () => void;
  onOpen: () => void;
}) {
  return (
    <div className="card-tile" onMouseEnter={onHover} onClick={onOpen} style={{ position: "relative" }}>
      <CardImage
        cardId={cardId}
        printing={printing}
        version="normal"
        alt={name}
        title={name}
        loading="lazy"
        style={{ width: "100%", display: "block", borderRadius: 8, border: "1px solid var(--border)" }}
      />
      {count > 1 && (
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
          &times;{count}
        </div>
      )}
    </div>
  );
}

function CardListRow({
  name,
  cardId,
  count,
  priceUsd,
  printing,
  onHover,
  onOpen,
}: {
  name: string;
  cardId: string | null | undefined;
  count: number;
  priceUsd: string | null | undefined;
  printing: SelectedPrinting | undefined;
  onHover: () => void;
  onOpen: () => void;
}) {
  return (
    <div
      className="card-row"
      onMouseEnter={onHover}
      onClick={onOpen}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "5px 4px",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <CardImage
        cardId={cardId}
        printing={printing}
        version="small"
        alt=""
        style={{ width: 28, height: 39, objectFit: "cover", borderRadius: 3, flexShrink: 0, background: "var(--surface)" }}
      />
      <div
        style={{
          flex: 1,
          minWidth: 0,
          fontSize: 14,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {name}
        {count > 1 && (
          <span style={{ color: "var(--text-muted)", fontWeight: 600, marginLeft: 6 }}>&times;{count}</span>
        )}
      </div>
      {priceUsd && (
        <div style={{ fontSize: 12, color: "var(--text-muted)", flexShrink: 0 }}>
          ${(parseFloat(priceUsd) * count).toFixed(2)}
        </div>
      )}
    </div>
  );
}

// Auto-retry schedule for Scryfall lookup failures (see the fetch effect
// in DeckView) — slow and capped on purpose, not a tight poll loop.
const RETRY_DELAYS_MS = [30_000, 90_000, 180_000];

const TAB_LABELS = { build: "DECKBUILDER", insights: "INSIGHTS", chat: "CORRESPONDENCE" } as const;

// An EDHREC include at or above this rate counts as a "staple" for the
// Insights tab's attention badge — played in at least half the decks that
// could play it, so missing one is a real signal rather than noise.
const STAPLE_INCLUSION = 0.5;

export default function DeckView() {
  const { deckId } = useParams<{ deckId: string }>();
  const navigate = useNavigate();

  const [deck, setDeck] = useState<Deck | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [pendingMessage, setPendingMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Why the last message failed when the model isn't to blame (the backend is
  // down, say), and when sending is allowed again. A failure while the Doctor
  // itself is unavailable is recorded page-wide instead; see aiStatus.ts.
  const [chatError, setChatError] = useState<string | null>(null);
  const [chatWaitUntil, setChatWaitUntil] = useState<number | null>(null);
  const chatFailures = useRef(0);
  // The same wait, readable before the next render, so a send that comes in
  // right behind a failure can't slip through on a stale `chatLocked`.
  const chatWaitRef = useRef(0);
  const sendingRef = useRef(false);
  const aiProblem = useAiProblem();
  const aiWait = useSecondsUntil(aiProblem?.until ?? null);
  const chatWait = useSecondsUntil(chatWaitUntil);
  // Only a person can clear this kind of problem; waiting won't.
  const aiNeedsFixing = aiProblem !== null && aiProblem.until === null;
  const chatLocked = aiNeedsFixing || aiWait > 0 || chatWait > 0;
  const [cardInfo, setCardInfo] = useState<Record<string, CardInfo>>({});
  const [tab, setTab] = useState<"build" | "insights" | "chat">("build");
  const [commanderIncludes, setCommanderIncludes] = useState<CommanderIncludes | null>(null);
  const [replacementsReady, setReplacementsReady] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [nameInput, setNameInput] = useState("");
  const [viewMode, setViewMode] = useState<"images" | "list">(() => {
    try {
      return localStorage.getItem("mtg-deck-doctor:viewMode") === "list" ? "list" : "images";
    } catch {
      return "images";
    }
  });
  const [hoveredCard, setHoveredCard] = useState<string | null>(null);
  // Scryfall ids learned from hovering cards that aren't in the deck (EDHREC
  // rows, AI suggestions), which carry their own ids — so the preview can
  // show their art without a lookup. Deck cards' ids come from cardInfo.
  const [hoverIds, setHoverIds] = useState<Record<string, string>>({});
  const [modalCard, setModalCard] = useState<string | null>(null);
  const [selectedPrintings, setSelectedPrintings] = useState<Record<string, SelectedPrinting>>({});
  const [ownedCards, setOwnedCards] = useState<Set<string>>(new Set());
  const [unresolvedCount, setUnresolvedCount] = useState(0);
  // Scheduled auto-retry state for Scryfall lookup failures — see the
  // fetch effect below. No manual "Retry" button: a button here invites
  // exactly the failure mode that makes this worse (clicking it
  // repeatedly piles more requests onto an already-active rate limit —
  // confirmed live that this doesn't help and may extend the lockout).
  // A bounded, slow, automatic schedule can't be spammed by an impatient
  // click.
  const [retryAttempt, setRetryAttempt] = useState(0);
  const [nextRetryAt, setNextRetryAt] = useState<number | null>(null);
  const [nowTick, setNowTick] = useState(() => Date.now());
  const [showImport, setShowImport] = useState(false);
  const [importBusy, setImportBusy] = useState(false);
  const [exportText, setExportText] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!deckId) return;
    setDeck(null);
    setNotFound(false);
    setSelectedPrintings(loadSelectedPrintings(deckId));
    setRetryAttempt(0);
    setNextRetryAt(null);
    getDeck(deckId)
      .then((found) => {
        if (found) setDeck(found);
        else setNotFound(true);
      })
      .catch(() => setError("Couldn't reach the Deck Doctor backend. Is it running on port 8000?"));
  }, [deckId]);

  // Ownership isn't deck-scoped, so it's fetched once per page visit, not
  // per deck.
  useEffect(() => {
    getCollection()
      .then((cards) => setOwnedCards(new Set(cards)))
      .catch(() => {
        // Non-critical — the "owned" toggle/badges just won't reflect
        // reality if this fails; not worth blocking the whole page over.
      });
  }, []);

  // getCardInfoBatch is backed by the backend's own cache (card_cache.py)
  // now, so this almost always resolves instantly from the cache rather
  // than hitting Scryfall at all — only a name that's genuinely never
  // been cached before, fetched while Scryfall's rate limit happens to be
  // active, can come back missing. That's now rare, but still possible,
  // and still worth surfacing rather than leaving silently uncategorized
  // ("Other") with no indication why. retryAttempt (advanced by the
  // scheduled-retry effect below) re-runs this same effect, which
  // naturally only re-fetches whatever's still missing from cardInfo.
  useEffect(() => {
    if (!deck) return;
    const names = deck.commander ? [...deck.cards, deck.commander] : deck.cards;
    const missing = Array.from(new Set(names)).filter((name) => !(name in cardInfo));
    if (missing.length === 0) {
      setUnresolvedCount(0);
      setNextRetryAt(null);
      return;
    }
    getCardInfoBatch(missing).then((result) => {
      setCardInfo((prev) => ({ ...prev, ...result.info }));
      const stillMissing = missing.length - Object.keys(result.info).length;
      setUnresolvedCount(stillMissing);
      setNextRetryAt(
        stillMissing > 0 && retryAttempt < RETRY_DELAYS_MS.length ? Date.now() + RETRY_DELAYS_MS[retryAttempt] : null,
      );
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deck?.cards, deck?.commander, retryAttempt]);

  // EDHREC data is per commander, not per deck state — fetched when the
  // commander is set/changes, and diffed against the live deck at render
  // time, so adding cards never triggers a refetch.
  useEffect(() => {
    setCommanderIncludes(null);
    setReplacementsReady(false);
    const commander = deck?.commander;
    if (!commander) return;
    let cancelled = false;
    getCommanderIncludes(commander).then((result) => {
      if (!cancelled) setCommanderIncludes(result);
    });
    return () => {
      cancelled = true;
    };
  }, [deck?.commander]);

  // Cut suggestions pair each cut with one of EDHREC's most-played missing
  // cards, and need those cards' text to know what role each fills. Fetched
  // through the backend cache (one batched Scryfall request the first time
  // for a commander, none after) and topped up as swaps move the pool along.
  // Marked ready once the attempt finishes, whether or not every lookup
  // landed — a card that failed is simply not a candidate yet.
  //
  // Only while the Insights tab is showing, and never while an import is
  // running: the import is the task the user is waiting on, and this is
  // what it would otherwise queue behind (or in front of) at Scryfall.
  // Finishing the import changes the deck, which is what runs this next —
  // so insights follow the import rather than being part of it.
  useEffect(() => {
    if (!deck || !commanderIncludes?.available || tab !== "insights" || importBusy) return;
    const wanted = replacementPool(commanderIncludes, new Set(deck.cards))
      .map((c) => c.name)
      .filter((name) => !(name in cardInfo));
    if (wanted.length === 0) {
      setReplacementsReady(true);
      return;
    }
    let cancelled = false;
    getCardInfoBatch(wanted).then((result) => {
      if (cancelled) return;
      setCardInfo((prev) => ({ ...prev, ...result.info }));
      setReplacementsReady(true);
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [commanderIncludes, deck?.cards, tab, importBusy]);

  // Fires the one scheduled retry, then clears itself — bounded to
  // RETRY_DELAYS_MS.length total extra attempts (enforced above, since
  // nextRetryAt only ever gets set while retryAttempt is still under that
  // length). A deliberately slow, capped schedule: fast enough to recover
  // within a few minutes, slow enough it can't meaningfully add to real
  // rate-limit pressure the way a click-driven retry can.
  useEffect(() => {
    if (nextRetryAt === null) return;
    const timer = setTimeout(() => setRetryAttempt((n) => n + 1), Math.max(0, nextRetryAt - Date.now()));
    return () => clearTimeout(timer);
  }, [nextRetryAt]);

  // Ticks only while a retry is actually scheduled, purely so the status
  // line's countdown stays accurate — not a polling mechanism itself.
  useEffect(() => {
    if (nextRetryAt === null) return;
    const interval = setInterval(() => setNowTick(Date.now()), 1000);
    return () => clearInterval(interval);
  }, [nextRetryAt]);

  // A card that's fully removed shouldn't linger as the sticky preview or
  // re-open its own modal the next time it's re-added (the modal's own
  // render guard closes it once its count hits zero, but the `modalCard`/
  // `hoveredCard` state itself stays set to that name — so if the same
  // card comes back later, the guard passes again and the modal pops back
  // open on its own, unasked).
  function clearSelectionIfGone(name: string, updatedDeck: Deck) {
    if (!updatedDeck.cards.includes(name)) {
      setHoveredCard((prev) => (prev === name ? null : prev));
      setModalCard((prev) => (prev === name ? null : prev));
      if (deckId) setSelectedPrintings(clearSelectedPrinting(deckId, name));
    }
  }

  // Which printing's art to show is a per-viewer display preference (see
  // printings.ts) — persisted in localStorage, never sent to the backend.
  function handleChangePrinting(name: string, printing: SelectedPrinting) {
    if (!deckId) return;
    setSelectedPrintings(saveSelectedPrinting(deckId, name, printing));
  }

  // Ownership toggle — a real backend-persisted fact (unlike printing
  // choice), since it's genuinely shared data about the collection, not a
  // per-viewer display preference.
  async function handleToggleOwned(name: string) {
    const cards = ownedCards.has(name) ? await removeFromCollection(name) : await addToCollection(name);
    setOwnedCards(new Set(cards));
  }

  // Every unique card in the deck (plus the commander) gets added to the
  // collection in one bulk call — not one addToCollection per card, which
  // would fire dozens of overlapping writes at a JSON file with no
  // per-write locking.
  async function handleAddDeckToCollection(): Promise<string> {
    if (!deck) return "";
    const names = Array.from(new Set(deck.commander ? [...deck.cards, deck.commander] : deck.cards));
    const newCount = names.filter((name) => !ownedCards.has(name)).length;
    const updated = await addManyToCollection(names);
    setOwnedCards(new Set(updated));
    return newCount > 0 ? `Added ${newCount} card${newCount === 1 ? "" : "s"}.` : "Already all in your collection.";
  }

  async function handleDuplicateDeck() {
    if (!deck) return;
    const copy = await duplicateDeck(deck.id);
    navigate(`/decks/${copy.id}`);
  }

  async function handleDeleteDeck() {
    if (!deck) return;
    await deleteDeck(deck.id);
    navigate("/");
  }

  function handleHover(name: string, id?: string | null) {
    if (id) setHoverIds((prev) => (prev[name] === id ? prev : { ...prev, [name]: id }));
    setHoveredCard(name);
  }

  // The import hands over the card data it fetched to check the names, so
  // the page doesn't ask for those cards a second time.
  function handleImported(imported: Deck, info: Record<string, CardInfo>) {
    setCardInfo((prev) => ({ ...prev, ...info }));
    setDeck(imported);
  }

  async function handleAddFromInsights(name: string) {
    if (!deck) return;
    setDeck(await addCard(deck.id, name));
  }

  // Builds from the same cardCounts/cardInfo the ledger itself renders
  // from, so the export matches what's on screen exactly, categories and
  // all.
  function handleExport() {
    if (!deck) return;
    setExportText(buildDecklistText(deck, cardCounts, cardInfo));
  }

  // Deliberately bypasses the backend's cache (refresh=true) — for when
  // the viewer wants this deck's prices/type lines re-pulled from
  // Scryfall right now, e.g. after a price has clearly moved. Not
  // subject to the same "don't let this be spammed" concern as the old
  // rate-limit retry: this is an occasional, deliberate action, not a
  // reaction to a failure, and every *normal* page load already prefers
  // the cache — only an explicit refresh ever asks Scryfall for
  // everything again.
  async function handleRefreshCardData(): Promise<string> {
    if (!deck) return "";
    const names = Array.from(new Set(deck.commander ? [...deck.cards, deck.commander] : deck.cards));
    const result = await getCardInfoBatch(names, true);
    setCardInfo((prev) => ({ ...prev, ...result.info }));
    const refreshedCount = Object.keys(result.info).length;
    return refreshedCount === names.length
      ? `Refreshed all ${refreshedCount} cards.`
      : `Refreshed ${refreshedCount} of ${names.length} cards — the rest couldn't load right now.`;
  }

  async function handleRemoveOne(name: string) {
    if (!deck) return;
    const result = await removeCard(deck.id, name);
    setDeck(result);
    clearSelectionIfGone(name, result);
  }

  // Removes every copy of a stack one at a time — sequential awaits, not
  // Promise.all, so each request completes before the next starts (this
  // backend has no per-deck locking; see the concurrency note in project
  // memory) rather than firing `count` overlapping writes at once.
  async function handleRemoveAll(name: string, count: number) {
    if (!deck) return;
    let result = deck;
    for (let i = 0; i < count; i++) {
      result = await removeCard(deck.id, name);
    }
    setDeck(result);
    clearSelectionIfGone(name, result);
  }

  // Scrolled explicitly at the two moments real chat activity happens
  // (sending, and the reply landing) rather than reactively off message
  // count — that value also changes when a deck's history first loads,
  // which would jump the page to the bottom every time a deck is opened.
  function scrollToBottomSoon() {
    requestAnimationFrame(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }));
  }

  // After a failure the next send waits: a few seconds, then longer if it keeps
  // failing — so a problem can't be hammered by pressing Send again.
  const CHAT_WAITS = [3, 10, 30];

  async function handleSend() {
    if (!deck || !input.trim() || sendingRef.current || chatLocked || Date.now() < chatWaitRef.current) return;
    sendingRef.current = true;
    const message = input.trim();
    setInput("");
    setPendingMessage(message);
    setSending(true);
    setError(null);
    setChatError(null);
    scrollToBottomSoon();
    try {
      const result = await sendMessage(deck.id, message);
      setDeck(result.deck);
      setPendingMessage(null);
      chatFailures.current = 0;
      scrollToBottomSoon();
    } catch (err) {
      // The message stays in the box, so nothing typed is lost.
      setPendingMessage(null);
      setInput(message);
      chatFailures.current += 1;
      setChatError(err instanceof Error ? err.message : "That message didn't go through.");
      chatWaitRef.current = Date.now() + CHAT_WAITS[Math.min(chatFailures.current, CHAT_WAITS.length) - 1] * 1000;
      setChatWaitUntil(chatWaitRef.current);
    } finally {
      sendingRef.current = false;
      setSending(false);
    }
  }

  if (notFound) {
    return (
      <div>
        <p>No deck found with that id.</p>
        <button className="btn" style={buttonStyle} onClick={() => navigate("/")}>
          Back to all decks
        </button>
      </div>
    );
  }

  function startRenaming() {
    setNameInput(deck?.name ?? deck?.commander ?? "");
    setRenaming(true);
  }

  async function handleRenameSave() {
    if (!deck) return;
    setDeck(await renameDeck(deck.id, nameInput));
    setRenaming(false);
  }

  const displayTitle = deck ? (deck.name ?? deck.commander ?? "Untitled deck") : "No commander yet";

  // Prefers the printing the viewer actually picked for this card over the
  // generic default-printing lookup — a $2 old-border Forest shouldn't
  // price like whatever printing Scryfall's plain name search resolves to.
  function priceFor(name: string): string | null {
    return selectedPrintings[name]?.priceUsd ?? cardInfo[name]?.priceUsd ?? null;
  }

  const totalCardCount = deck ? deck.cards.length + (deck.commander ? 1 : 0) : 0;
  const totalPrice = deck
    ? [...deck.cards, ...(deck.commander ? [deck.commander] : [])].reduce((sum, name) => {
        const price = priceFor(name);
        return price ? sum + parseFloat(price) : sum;
      }, 0)
    : 0;
  // Ownership is a plain "do I have any at all" flag (no quantity), which
  // is enough for Commander decks: everything but basics is singleton, so
  // a deck never needs more than one copy of a non-basic anyway.
  const costToComplete = deck
    ? [...deck.cards, ...(deck.commander ? [deck.commander] : [])].reduce((sum, name) => {
        if (ownedCards.has(name)) return sum;
        const price = priceFor(name);
        return price ? sum + parseFloat(price) : sum;
      }, 0)
    : 0;

  const cardCounts = new Map<string, number>();
  deck?.cards.forEach((name) => cardCounts.set(name, (cardCounts.get(name) ?? 0) + 1));

  // Built once and shared by both the categorized ledger render below and
  // the card modal's prev/next navigation, so stepping through cards
  // follows the exact same order they're shown on screen.
  const byCategory = new Map<string, { name: string; count: number }[]>();
  cardCounts.forEach((count, name) => {
    const category = categoryFor(cardInfo[name]?.typeLine ?? undefined);
    if (!byCategory.has(category)) byCategory.set(category, []);
    byCategory.get(category)!.push({ name, count });
  });
  byCategory.forEach((entries) => entries.sort((a, b) => a.name.localeCompare(b.name)));
  const orderedNames = CATEGORY_ORDER.flatMap((category) => (byCategory.get(category) ?? []).map((e) => e.name));
  const modalIndex = modalCard ? orderedNames.indexOf(modalCard) : -1;

  const deckNames = new Set(deck?.commander ? [...(deck?.cards ?? []), deck.commander] : (deck?.cards ?? []));
  const stapleCount =
    commanderIncludes?.available
      ? commanderIncludes.cards.filter((c) => c.inclusion >= STAPLE_INCLUSION && !deckNames.has(c.name)).length
      : 0;
  const deckHealth = analyzeDeck(cardCounts, cardInfo);

  function handleNavigateModal(direction: "prev" | "next") {
    if (modalIndex < 0) return;
    const nextName = orderedNames[direction === "prev" ? modalIndex - 1 : modalIndex + 1];
    if (nextName) setModalCard(nextName);
  }

  const visibleMessages = (deck?.messages ?? [])
    .map((m) => ({ role: m.role, text: extractText(m.content) }))
    .filter((m) => m.text.trim().length > 0);
  if (pendingMessage) {
    visibleMessages.push({ role: "user", text: pendingMessage });
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <header
        style={{
          display: "flex",
          alignItems: "flex-start",
          gap: 16,
          borderBottom: "1px solid var(--border)",
          paddingBottom: 16,
        }}
      >
        {deck?.commander && (
          <CardImage
            cardId={cardInfo[deck.commander]?.id}
            printing={selectedPrintings[deck.commander]}
            version="normal"
            alt={deck.commander}
            title={deck.commander}
            onMouseEnter={() => setHoveredCard(deck.commander)}
            style={{ width: 110, flexShrink: 0, display: "block", borderRadius: 8, border: "1px solid var(--border)" }}
          />
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <Link to="/" style={{ ...eyebrowStyle, textDecoration: "none", display: "inline-block" }}>
            &larr; ALL DECKS
          </Link>

          {renaming ? (
            <input
              autoFocus
              value={nameInput}
              onChange={(e) => setNameInput(e.target.value)}
              onFocus={(e) => e.currentTarget.select()}
              onBlur={handleRenameSave}
              onKeyDown={(e) => {
                if (e.key === "Enter") e.currentTarget.blur();
                else if (e.key === "Escape") setRenaming(false);
              }}
              placeholder="Name this deck..."
              style={{
                display: "block",
                fontSize: 26,
                fontWeight: 600,
                fontFamily: "inherit",
                color: "var(--text)",
                background: "none",
                border: "none",
                borderBottom: "2px solid var(--accent)",
                padding: 0,
                marginTop: 4,
                width: "100%",
              }}
            />
          ) : (
            <div
              onClick={() => deck && startRenaming()}
              className={deck ? "deck-title" : undefined}
              style={{
                fontSize: 26,
                fontWeight: 600,
                marginTop: 4,
                cursor: deck ? "pointer" : "default",
              }}
            >
              {displayTitle}
              {deck && (
                <span className="rename-hint" aria-hidden="true">
                  click to rename
                </span>
              )}
            </div>
          )}

          {deck?.name && deck.commander && (
            <div style={{ fontSize: 13, fontStyle: "italic", color: "var(--text-muted)", marginTop: 2 }}>
              Commander: {deck.commander}
            </div>
          )}
          {deck && deck.commander_color_identity.length > 0 && (
            <div style={{ marginTop: 4 }}>
              <ManaPips colors={deck.commander_color_identity} />
            </div>
          )}
          {deck && (
            <div style={{ fontSize: 13, fontStyle: "italic", color: "var(--text-muted)", marginTop: 4 }}>
              {totalCardCount}/100 cards · ${totalPrice.toFixed(2)}
              {costToComplete > 0 && costToComplete < totalPrice && ` · $${costToComplete.toFixed(2)} to complete`}
            </div>
          )}
          {unresolvedCount > 0 && (
            <div style={{ fontSize: 13, color: "var(--danger)", marginTop: 4 }}>
              {unresolvedCount} card{unresolvedCount === 1 ? "" : "s"} couldn't load from Scryfall (likely
              rate-limited) — type, price, and category are missing for {unresolvedCount === 1 ? "it" : "them"}.{" "}
              {nextRetryAt !== null
                ? `Retrying automatically in ${Math.max(0, Math.ceil((nextRetryAt - nowTick) / 1000))}s…`
                : "Reload this page in a few minutes to try again."}
            </div>
          )}
        </div>

        {deck && (
          <DeckMenu
            onAddToCollection={handleAddDeckToCollection}
            onRefreshCardData={handleRefreshCardData}
            onImport={() => setShowImport(true)}
            onExport={handleExport}
            onDuplicate={handleDuplicateDeck}
            onDelete={handleDeleteDeck}
          />
        )}
      </header>

      {error && <div style={{ color: "var(--accent)", fontSize: 14 }}>{error}</div>}

      {deck && (
        <nav style={{ display: "flex", gap: 20, borderBottom: "1px solid var(--border)" }}>
          {(["build", "insights", "chat"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              style={{
                background: "none",
                border: "none",
                borderBottom: tab === t ? "2px solid var(--accent)" : "2px solid transparent",
                color: tab === t ? "var(--accent)" : "var(--text-muted)",
                fontFamily: "inherit",
                fontSize: 13,
                fontWeight: 600,
                letterSpacing: "0.08em",
                padding: "0 0 10px",
                cursor: "pointer",
              }}
            >
              {TAB_LABELS[t]}
              {t === "insights" && stapleCount > 0 && (
                <span style={{ marginLeft: 6, color: "var(--accent-gold)" }}>· {stapleCount}</span>
              )}
            </button>
          ))}
        </nav>
      )}

      {deck && tab === "build" && !deck.commander && (
        <section>
          <div style={eyebrowStyle}>CHOOSE A COMMANDER</div>
          <CardSearchBox
            placeholder="Search for your commander..."
            submitLabel="Set"
            onSubmit={async (name) => setDeck(await setCommander(deck.id, name))}
          />
        </section>
      )}

      {deck && tab === "build" && deck.commander && (
        <section style={{ display: "flex", gap: 24, alignItems: "flex-start" }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div
              style={{
                position: "sticky",
                top: 0,
                zIndex: 5,
                background: "var(--bg)",
                paddingTop: 4,
                paddingBottom: 10,
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <div style={eyebrowStyle}>ADD A CARD</div>
                <Link to={`/search?deck=${deck.id}`} style={{ fontSize: 12, color: "var(--accent)" }}>
                  Browse all cards →
                </Link>
              </div>
              <CardSearchBox
                placeholder="Search for a card to add..."
                submitLabel="Add"
                onSubmit={async (name) => setDeck(await addCard(deck.id, name))}
              />
            </div>

            {deck.cards.length > 0 && (
              <div style={{ marginTop: 10 }}>
                <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
                  {(["images", "list"] as const).map((mode) => (
                    <button
                      key={mode}
                      onClick={() => {
                        setViewMode(mode);
                        try {
                          localStorage.setItem("mtg-deck-doctor:viewMode", mode);
                        } catch {
                          // per-viewer convenience only — fine if it's unavailable
                        }
                      }}
                      className="btn"
                      style={
                        viewMode === mode
                          ? { ...buttonStyle, borderColor: "var(--accent)", color: "var(--accent)" }
                          : buttonStyle
                      }
                    >
                      {mode === "images" ? "Images" : "List"}
                    </button>
                  ))}
                </div>

                {(() => {
                  return CATEGORY_ORDER.filter((category) => byCategory.get(category)?.length).map((category) => {
                    const entries = byCategory.get(category)!;
                    const total = entries.reduce((sum, e) => sum + e.count, 0);
                    return (
                      <div key={category} style={{ marginBottom: 18 }}>
                        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-muted)", marginBottom: 8 }}>
                          {category.toUpperCase()} ({total})
                        </div>
                        {viewMode === "images" ? (
                          <div
                            style={{
                              display: "grid",
                              gridTemplateColumns: "repeat(auto-fill, minmax(110px, 1fr))",
                              gap: 12,
                            }}
                          >
                            {entries.map(({ name, count }) => (
                              <CardTile
                                key={name}
                                name={name}
                                cardId={cardInfo[name]?.id}
                                count={count}
                                printing={selectedPrintings[name]}
                                onHover={() => setHoveredCard(name)}
                                onOpen={() => setModalCard(name)}
                              />
                            ))}
                          </div>
                        ) : (
                          <div>
                            {entries.map(({ name, count }) => (
                              <CardListRow
                                key={name}
                                name={name}
                                cardId={cardInfo[name]?.id}
                                count={count}
                                priceUsd={priceFor(name)}
                                printing={selectedPrintings[name]}
                                onHover={() => setHoveredCard(name)}
                                onOpen={() => setModalCard(name)}
                              />
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  });
                })()}
              </div>
            )}

          </div>

          <CardPreview
            name={hoveredCard}
            cardId={hoveredCard ? (hoverIds[hoveredCard] ?? cardInfo[hoveredCard]?.id) : undefined}
            printing={hoveredCard ? selectedPrintings[hoveredCard] : undefined}
            priceUsd={hoveredCard ? priceFor(hoveredCard) : undefined}
          />
        </section>
      )}

      {deck && tab === "insights" && deck.commander && (
        <>
          {/* The point of the page, full width and first: the swaps the Doctor
              recommends, each with its reasons. */}
          <CutSuggestions
            deck={deck}
            cardInfo={cardInfo}
            includes={commanderIncludes}
            replacementsReady={replacementsReady}
            ownedCards={ownedCards}
            paused={importBusy}
            onDeckChange={setDeck}
            onHoverCard={handleHover}
          />

          {/* Then the supporting detail, with the hover preview beside it. */}
          <div style={{ borderTop: "1px solid var(--border)", margin: "8px 0 28px" }} />
          <section style={{ display: "flex", gap: 24, alignItems: "flex-start" }}>
            <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 28 }}>
              <DeckHealthPanel health={deckHealth} />
              <TopIncludes
                includes={commanderIncludes}
                deckNames={deckNames}
                ownedCards={ownedCards}
                onAdd={handleAddFromInsights}
                onHoverCard={handleHover}
              />
              <Recommendations
                deck={deck}
                onDeckChange={setDeck}
                onHoverCard={handleHover}
                ownedCards={ownedCards}
                paused={importBusy}
              />
            </div>

            <CardPreview
              name={hoveredCard}
              cardId={hoveredCard ? (hoverIds[hoveredCard] ?? cardInfo[hoveredCard]?.id) : undefined}
              printing={hoveredCard ? selectedPrintings[hoveredCard] : undefined}
            priceUsd={hoveredCard ? priceFor(hoveredCard) : undefined}
            />
          </section>
        </>
      )}

      {deck && tab === "insights" && !deck.commander && (
        <div style={{ color: "var(--text-muted)", fontSize: 14 }}>
          Pick a commander in the Deckbuilder tab first — insights are built around it.
        </div>
      )}

      {deck && modalCard && cardCounts.has(modalCard) && (
        <CardModal
          name={modalCard}
          cardId={cardInfo[modalCard]?.id}
          count={cardCounts.get(modalCard)!}
          info={cardInfo[modalCard]}
          printing={selectedPrintings[modalCard]}
          onChangePrinting={(printing) => handleChangePrinting(modalCard, printing)}
          onAddOne={async () => setDeck(await addCard(deck.id, modalCard))}
          onAddMany={async (quantity) => {
            const result = await bulkAddCards(deck.id, modalCard, quantity);
            setDeck(result.deck);
            return { added: result.added, failed: result.failed, error: result.error };
          }}
          onRemoveOne={() => handleRemoveOne(modalCard)}
          onRemoveAll={() => handleRemoveAll(modalCard, cardCounts.get(modalCard)!)}
          owned={ownedCards.has(modalCard)}
          onToggleOwned={() => handleToggleOwned(modalCard)}
          onNavigate={handleNavigateModal}
          hasPrevious={modalIndex > 0}
          hasNext={modalIndex >= 0 && modalIndex < orderedNames.length - 1}
          onClose={() => setModalCard(null)}
        />
      )}

      {deck && showImport && (
        <ImportCardsModal
          deckId={deck.id}
          existingNames={new Set(deck.commander ? [...deck.cards, deck.commander] : deck.cards)}
          onImported={handleImported}
          onBusyChange={setImportBusy}
          onClose={() => setShowImport(false)}
        />
      )}

      {exportText !== null && <ExportDecklistModal text={exportText} onClose={() => setExportText(null)} />}

      {deck && tab === "chat" && (
        <>
          <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {visibleMessages.map((m, i) => (
              <div
                key={i}
                style={{
                  alignSelf: m.role === "user" ? "flex-end" : "flex-start",
                  maxWidth: "85%",
                  background: m.role === "user" ? "var(--user-bubble)" : "var(--surface)",
                  border: m.role === "user" ? "none" : "1px solid var(--border)",
                  fontStyle: m.role === "user" ? "italic" : "normal",
                  padding: "10px 14px",
                  borderRadius: 4,
                  fontSize: 15,
                  lineHeight: 1.5,
                  whiteSpace: m.role === "user" ? "pre-wrap" : "normal",
                }}
              >
                {m.role === "user" ? m.text : <ReactMarkdown>{m.text}</ReactMarkdown>}
              </div>
            ))}
            {sending && <div style={{ color: "var(--text-muted)", fontSize: 14 }}>The Doctor is thinking…</div>}
            <div ref={bottomRef} />
          </section>

          {/* Beside the box the player is typing in, not at the top of the page. */}
          {chatLocked && (aiProblem || chatError) && (
            <AiNotice
              message={aiProblem ? aiProblem.message : chatError!}
              secondsLeft={aiProblem ? aiWait : chatWait}
              canCheck={aiNeedsFixing}
            />
          )}

          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSend();
            }}
            style={{ display: "flex", gap: 8 }}
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask the Doctor..."
              style={inputStyle}
              disabled={!deck || sending}
            />
            <button type="submit" className="btn" style={buttonStyle} disabled={!deck || sending || chatLocked}>
              Send
            </button>
          </form>
        </>
      )}
    </div>
  );
}
