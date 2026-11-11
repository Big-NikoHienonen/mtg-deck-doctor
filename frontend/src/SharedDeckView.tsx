import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { getCardInfoBatch, getSharedDeck, type CardInfo, type SharedDeck } from "./api";
import CardModal from "./CardModal";
import DeckControls, { type ListSettings } from "./DeckControls";
import DeckFooter from "./DeckFooter";
import DeckHero from "./DeckHero";
import DeckList from "./DeckList";
import DeckSidebar from "./DeckSidebar";
import DeckStats from "./DeckStats";
import { buildRows, deckStats, groupRows } from "./deckListModel";
import ExportDecklistModal from "./ExportDecklistModal";
import { buildDecklistText } from "./importExport";
import { loadSettings, saveSettings } from "./listSettings";
import "./deckview.css";

// A card lookup that comes back short (Scryfall rate-limited) is tried again a few times, slowly.
const RETRY_DELAYS_MS = [30_000, 90_000, 180_000];

// What a share link opens: the deck as its owner built it, to look at. It is the deck page with
// nothing that changes the deck, and no Doctor. It only ever asks the backend for the shared list
// and for card data, which is the same for everyone; the deck's id never reaches this page.
export default function SharedDeckView() {
  const { token } = useParams<{ token: string }>();
  const [deck, setDeck] = useState<SharedDeck | null>(null);
  const [status, setStatus] = useState<"loading" | "missing" | "error" | "ready">("loading");
  const [cardInfo, setCardInfo] = useState<Record<string, CardInfo>>({});
  const [unresolved, setUnresolved] = useState(0);
  const [retryAttempt, setRetryAttempt] = useState(0);
  const [settings, setSettings] = useState<ListSettings>(loadSettings);
  const [hoveredCard, setHoveredCard] = useState<string | null>(null);
  const [modalCard, setModalCard] = useState<string | null>(null);
  const [exportText, setExportText] = useState<string | null>(null);

  // The deck page is wider than the rest of the app.
  useEffect(() => {
    const page = document.querySelector(".page");
    page?.classList.add("dv-wide");
    return () => page?.classList.remove("dv-wide");
  }, []);

  useEffect(() => {
    if (!token) return;
    setStatus("loading");
    getSharedDeck(token)
      .then((found) => {
        setDeck(found);
        setStatus(found ? "ready" : "missing");
      })
      .catch(() => setStatus("error"));
  }, [token]);

  // Card data for the list, from the backend's cache. A retry re-runs this, and only asks for what is still missing.
  useEffect(() => {
    if (!deck) return;
    const names = deck.commander ? [...deck.cards, deck.commander] : deck.cards;
    const missing = Array.from(new Set(names)).filter((name) => !(name in cardInfo));
    if (missing.length === 0) {
      setUnresolved(0);
      return;
    }
    let cancelled = false;
    getCardInfoBatch(missing).then((result) => {
      if (cancelled) return;
      setCardInfo((prev) => ({ ...prev, ...result.info }));
      const stillMissing = missing.length - Object.keys(result.info).length;
      setUnresolved(stillMissing);
      if (stillMissing > 0 && retryAttempt < RETRY_DELAYS_MS.length) {
        setTimeout(() => !cancelled && setRetryAttempt((n) => n + 1), RETRY_DELAYS_MS[retryAttempt]);
      }
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deck, retryAttempt]);

  function handleSettings(next: ListSettings) {
    setSettings(next);
    saveSettings(next);
  }

  if (status === "loading") return <div style={{ padding: 24, color: "var(--text-muted)", fontSize: 14 }}>Loading…</div>;
  if (status !== "ready" || !deck) {
    return (
      <div style={{ padding: 24 }}>
        <p style={{ fontSize: 18, fontWeight: 600, margin: "0 0 8px" }}>
          {status === "missing" ? "This deck isn't shared" : "Couldn't load this deck"}
        </p>
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          {status === "missing"
            ? "The link may be mistyped, or its owner turned it off. Ask them for a new one."
            : "Reload the page in a moment."}
        </p>
      </div>
    );
  }

  const priceFor = (name: string) => cardInfo[name]?.priceUsd ?? null;
  const allCards = deck.commander ? [...deck.cards, deck.commander] : deck.cards;
  const totalPrice = allCards.reduce((sum, name) => sum + (parseFloat(priceFor(name) ?? "") || 0), 0);
  const cardCounts = new Map<string, number>();
  deck.cards.forEach((name) => cardCounts.set(name, (cardCounts.get(name) ?? 0) + 1));

  const rows = buildRows(deck.cards, deck.commander, cardInfo, priceFor);
  const groups = groupRows(rows, settings.groupBy, settings.sortBy);
  const orderedNames = groups.flatMap((g) => g.rows.filter((r) => !r.isCommander).map((r) => r.name));
  const stats = deckStats(rows, (name) => cardInfo[name]?.manaCost);
  const modalIndex = modalCard ? orderedNames.indexOf(modalCard) : -1;
  const modalIsCommander = !!modalCard && modalCard === deck.commander;
  const previewName = hoveredCard ?? deck.commander ?? null;
  const title = deck.name ?? deck.commander ?? "Untitled deck";

  function navigateModal(direction: "prev" | "next") {
    const next = orderedNames[direction === "prev" ? modalIndex - 1 : modalIndex + 1];
    if (next) setModalCard(next);
  }

  return (
    <div className="dv">
      <DeckHero
        commander={deck.commander}
        commanderId={deck.commander ? cardInfo[deck.commander]?.id : null}
        printing={undefined}
        showCommander={!!deck.name}
        onOpenCommander={() => deck.commander && setModalCard(deck.commander)}
        showBack={false}
        title={<h1 className="dv-title">{title}</h1>}
        colorIdentity={deck.commander_color_identity}
        cardCount={allCards.length}
        price={totalPrice}
        costToComplete={0}
        updatedAt={deck.updated_at}
        warning={unresolved > 0 && <span className="dv-warn">{unresolved} card{unresolved === 1 ? "" : "s"} couldn't load from Scryfall (likely rate-limited). Reload in a few minutes.</span>}
      />

      <div className="dv-container">
        <div className="dv-actions">
          <button className="dv-action" onClick={() => setExportText(buildDecklistText(deck, cardCounts, cardInfo))}>
            Export
          </button>
          <div className="dv-grow" />
          <span style={{ fontSize: 13, color: "var(--text-muted)" }}>A shared deck, to look at</span>
        </div>

        <div className="dv-main">
          <DeckSidebar
            name={previewName}
            cardId={previewName ? cardInfo[previewName]?.id : undefined}
            printing={undefined}
            priceUsd={previewName ? priceFor(previewName) : undefined}
            inDeck={!!previewName && (cardCounts.has(previewName) || previewName === deck.commander)}
            owned={false}
            onOpen={() => previewName && setModalCard(previewName)}
          />
          <div className="dv-content">
            <DeckControls settings={settings} onChange={handleSettings} />
            <DeckList
              groups={groups}
              view={settings.view}
              options={settings}
              printings={{}}
              owned={new Set()}
              onHover={(name) => setHoveredCard(name)}
              onOpen={(name) => setModalCard(name)}
            />
            <DeckStats stats={stats} />
          </div>
        </div>
      </div>

      {modalCard && (modalIsCommander || cardCounts.has(modalCard)) && (
        <CardModal
          name={modalCard}
          cardId={cardInfo[modalCard]?.id}
          info={cardInfo[modalCard]}
          printing={undefined}
          isCommander={modalIsCommander}
          onNavigate={navigateModal}
          hasPrevious={modalIndex > 0}
          hasNext={modalIndex >= 0 && modalIndex < orderedNames.length - 1}
          onClose={() => setModalCard(null)}
        />
      )}

      {exportText !== null && <ExportDecklistModal text={exportText} onClose={() => setExportText(null)} />}

      <DeckFooter rows={rows} cardCount={allCards.length} price={totalPrice} costToComplete={0} />
    </div>
  );
}
