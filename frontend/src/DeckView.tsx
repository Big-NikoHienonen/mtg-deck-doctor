import { Fragment, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import {
  addCard,
  addManyToCollection,
  addToCollection,
  bulkAddCards,
  deleteDeck,
  duplicateDeck,
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
import { useAiProblem } from "./aiStatus";
import AiNotice, { useSecondsUntil } from "./AiNotice";
import CardModal from "./CardModal";
import CardPreview from "./CardPreview";
import CardSearchBox from "./CardSearchBox";
import ChatSuggestions from "./ChatSuggestions";
import { chatItems, type Suggestion } from "./chatMessages";
import CutSuggestions from "./CutSuggestions";
import { replacementPool } from "./cutRanking";
import DeckControls, { type ListSettings } from "./DeckControls";
import DeckFooter from "./DeckFooter";
import DeckHealthPanel from "./DeckHealthPanel";
import DeckHero from "./DeckHero";
import DeckList from "./DeckList";
import DeckSidebar from "./DeckSidebar";
import DeckStats from "./DeckStats";
import { buildRows, deckStats, groupRows } from "./deckListModel";
import { analyzeDeck } from "./deckHealth";
import { loadSettings, saveSettings } from "./listSettings";
import DeckMenu from "./DeckMenu";
import ExportDecklistModal from "./ExportDecklistModal";
import { buildDecklistText } from "./importExport";
import ImportCardsModal from "./ImportCardsModal";
import ShareDeckModal from "./ShareDeckModal";
import {
  clearSelectedPrinting,
  loadSelectedPrintings,
  priceUsdOf,
  saveSelectedPrinting,
  type SelectedPrinting,
} from "./printings";
import Recommendations from "./Recommendations";
import TopIncludes from "./TopIncludes";
import { buttonStyle, eyebrowStyle, inputStyle } from "./styles";
import "./deckview.css";

// Auto-retry schedule for Scryfall lookup failures (see the fetch effect
// in DeckView) — slow and capped on purpose, not a tight poll loop.
const RETRY_DELAYS_MS = [30_000, 90_000, 180_000];

const TAB_LABELS = { build: "Deck", insights: "Insights", chat: "Correspondence" } as const;

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
  const [settings, setSettings] = useState<ListSettings>(loadSettings);
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
  const [showShare, setShowShare] = useState(false);
  const [importBusy, setImportBusy] = useState(false);
  const [exportText, setExportText] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // The deck page is wider than the rest of the app.
  useEffect(() => {
    const page = document.querySelector(".page");
    page?.classList.add("dv-wide");
    return () => page?.classList.remove("dv-wide");
  }, []);

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

  // Cards cached before mana costs and mana values were recorded show no cost. They are asked
  // for again, fresh, once per card per visit.
  const backfilled = useRef(new Set<string>());
  useEffect(() => {
    const stale = Object.entries(cardInfo)
      .filter(([name, info]) => info.manaCost === undefined && !backfilled.current.has(name))
      .map(([name]) => name);
    if (stale.length === 0) return;
    stale.forEach((name) => backfilled.current.add(name));
    getCardInfoBatch(stale, true).then((result) => setCardInfo((prev) => ({ ...prev, ...result.info })));
  }, [cardInfo]);

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

  function handleSettings(next: ListSettings) {
    setSettings(next);
    saveSettings(next);
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

  // A change the Doctor proposed in the chat, made on the player's click. A refusal throws, and the
  // suggestion shows why.
  async function handleApplySuggestion(s: Suggestion) {
    if (!deck) return;
    if (s.action === "add") setDeck(await addCard(deck.id, s.name));
    else if (s.action === "remove") await handleRemoveOne(s.name);
    else setDeck(await setCommander(deck.id, s.name));
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
    return priceUsdOf(selectedPrintings[name], cardInfo[name]?.priceUsd);
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

  // The list as rows, grouped and sorted as the viewer chose. The card modal's previous and
  // next follow the same order, so stepping through cards goes the way they are shown.
  const rows = buildRows(deck?.cards ?? [], deck?.commander ?? null, cardInfo, priceFor);
  const groups = groupRows(rows, settings.groupBy, settings.sortBy);
  const orderedNames = groups.flatMap((g) => g.rows.filter((r) => !r.isCommander).map((r) => r.name));
  const stats = deckStats(rows, (name) => cardInfo[name]?.manaCost);
  const modalIndex = modalCard ? orderedNames.indexOf(modalCard) : -1;
  // The commander isn't one of the deck's counted cards, so its modal is a read-only view of the card.
  const modalIsCommander = !!modalCard && modalCard === deck?.commander;

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

  const visibleMessages = chatItems(deck?.messages ?? []);
  if (pendingMessage) {
    visibleMessages.push({ role: "user", text: pendingMessage, suggestions: [] });
  }

  const title = renaming ? (
    <input
      autoFocus
      className="dv-title-input"
      value={nameInput}
      onChange={(e) => setNameInput(e.target.value)}
      onFocus={(e) => e.currentTarget.select()}
      onBlur={handleRenameSave}
      onKeyDown={(e) => {
        if (e.key === "Enter") e.currentTarget.blur();
        else if (e.key === "Escape") setRenaming(false);
      }}
      placeholder="Name this deck..."
    />
  ) : (
    <h1 className={`dv-title${deck ? " dv-title-edit" : ""}`} onClick={() => deck && startRenaming()}>
      {deck ? displayTitle : "Loading…"}
      {deck && (
        <span className="dv-rename" aria-hidden="true">
          click to rename
        </span>
      )}
    </h1>
  );

  const previewName = hoveredCard ?? deck?.commander ?? null;

  return (
    <div className="dv">
      <DeckHero
        commander={deck?.commander ?? null}
        commanderId={deck?.commander ? cardInfo[deck.commander]?.id : null}
        printing={deck?.commander ? selectedPrintings[deck.commander] : undefined}
        showCommander={!!deck?.name}
        onOpenCommander={() => deck?.commander && setModalCard(deck.commander)}
        title={title}
        colorIdentity={deck?.commander_color_identity ?? []}
        cardCount={totalCardCount}
        price={totalPrice}
        costToComplete={costToComplete}
        updatedAt={deck?.updated_at}
        warning={
          unresolvedCount > 0 && (
            <span className="dv-warn">
              {unresolvedCount} card{unresolvedCount === 1 ? "" : "s"} couldn't load from Scryfall (likely rate-limited).{" "}
              {nextRetryAt !== null ? `Retrying in ${Math.max(0, Math.ceil((nextRetryAt - nowTick) / 1000))}s…` : "Reload in a few minutes."}
            </span>
          )
        }
      />

      <div className="dv-container">
        {error && <div style={{ color: "var(--accent)", fontSize: 14, paddingTop: 12 }}>{error}</div>}

        {deck && (
          <div className="dv-actions" role="tablist">
            {(["build", "insights", "chat"] as const).map((t) => (
              <button key={t} role="tab" aria-selected={tab === t} className="dv-action" onClick={() => setTab(t)}>
                {TAB_LABELS[t]}
                {t === "insights" && stapleCount > 0 && <span className="dv-count">{stapleCount}</span>}
              </button>
            ))}
            <span className="dv-sep" aria-hidden />
            <button className="dv-action" onClick={() => setShowImport(true)}>
              Import
            </button>
            <button className="dv-action" onClick={handleExport}>
              Export
            </button>
            <button className="dv-action" onClick={() => setShowShare(true)}>
              {deck.share_token ? "Shared" : "Share"}
            </button>
            <DeckMenu
              onAddToCollection={handleAddDeckToCollection}
              onRefreshCardData={handleRefreshCardData}
              onImport={() => setShowImport(true)}
              onExport={handleExport}
              onDuplicate={handleDuplicateDeck}
              onDelete={handleDeleteDeck}
            />
            <div className="dv-grow" />
            <Link to={`/search?deck=${deck.id}`} className="dv-action">
              Browse all cards →
            </Link>
          </div>
        )}

        {deck && tab === "build" && !deck.commander && (
          <section className="dv-narrow">
            <div style={eyebrowStyle}>CHOOSE A COMMANDER</div>
            <CardSearchBox
              placeholder="Search for your commander..."
              submitLabel="Set"
              onSubmit={async (name) => setDeck(await setCommander(deck.id, name))}
            />
          </section>
        )}

        {deck && tab === "build" && deck.commander && (
          <div className="dv-main">
            <DeckSidebar
              name={previewName}
              cardId={previewName ? (hoverIds[previewName] ?? cardInfo[previewName]?.id) : undefined}
              printing={previewName ? selectedPrintings[previewName] : undefined}
              priceUsd={previewName ? priceFor(previewName) : undefined}
              inDeck={!!previewName && (cardCounts.has(previewName) || previewName === deck.commander)}
              owned={!!previewName && ownedCards.has(previewName)}
              onToggleOwned={() => previewName && handleToggleOwned(previewName)}
              onOpen={() => previewName && setModalCard(previewName)}
            />
            <div className="dv-content">
              <DeckControls
                settings={settings}
                onChange={handleSettings}
                add={
                  <CardSearchBox
                    placeholder="Add a card..."
                    submitLabel="Add"
                    onSubmit={async (name) => setDeck(await addCard(deck.id, name))}
                  />
                }
              />
              <DeckList
                groups={groups}
                view={settings.view}
                options={settings}
                printings={selectedPrintings}
                owned={ownedCards}
                onHover={(name) => setHoveredCard(name)}
                onOpen={(name) => setModalCard(name)}
                onAddOne={async (name) => setDeck(await addCard(deck.id, name))}
                onRemoveOne={handleRemoveOne}
              />
              <DeckStats stats={stats} />
            </div>
          </div>
        )}

      {deck && tab === "insights" && deck.commander && (
        <div className="dv-narrow">
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
        </div>
      )}

      {deck && tab === "insights" && !deck.commander && (
        <div className="dv-narrow" style={{ color: "var(--text-muted)", fontSize: 14 }}>
          Pick a commander in the Deckbuilder tab first — insights are built around it.
        </div>
      )}

      {deck && modalCard && (modalIsCommander || cardCounts.has(modalCard)) && (
        <CardModal
          name={modalCard}
          cardId={cardInfo[modalCard]?.id}
          info={cardInfo[modalCard]}
          printing={selectedPrintings[modalCard]}
          onChangePrinting={(printing) => handleChangePrinting(modalCard, printing)}
          isCommander={modalIsCommander}
          {...(modalIsCommander
            ? {}
            : {
                count: cardCounts.get(modalCard)!,
                onAddOne: async () => setDeck(await addCard(deck.id, modalCard)),
                onAddMany: async (quantity: number) => {
                  const result = await bulkAddCards(deck.id, modalCard, quantity);
                  setDeck(result.deck);
                  return { added: result.added, failed: result.failed, error: result.error };
                },
                onRemoveOne: () => handleRemoveOne(modalCard),
                onRemoveAll: () => handleRemoveAll(modalCard, cardCounts.get(modalCard)!),
              })}
          owned={ownedCards.has(modalCard)}
          onToggleOwned={() => handleToggleOwned(modalCard)}
          onNavigate={handleNavigateModal}
          hasPrevious={modalIndex > 0}
          hasNext={modalIndex >= 0 && modalIndex < orderedNames.length - 1}
          onClose={() => setModalCard(null)}
        />
      )}

      {deck && showShare && <ShareDeckModal deck={deck} onChange={setDeck} onClose={() => setShowShare(false)} />}

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
        <div className="dv-narrow">
          <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {visibleMessages.map((m, i) => (
              <Fragment key={i}>
                {m.text.trim() && (
                  <div
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
                )}
                {deck && m.suggestions.length > 0 && <ChatSuggestions suggestions={m.suggestions} deck={deck} onApply={handleApplySuggestion} />}
              </Fragment>
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
        </div>
      )}
      </div>

      {deck && tab === "build" && deck.commander && <DeckFooter rows={rows} cardCount={totalCardCount} price={totalPrice} costToComplete={costToComplete} />}
    </div>
  );
}
