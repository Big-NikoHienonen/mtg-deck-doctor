import { useEffect, useState } from "react";
import { getRulings, type CardInfo, type Ruling } from "./api";
import PrintingPicker from "./PrintingPicker";
import CardImage from "./CardImage";
import type { SelectedPrinting } from "./printings";
import { buttonStyle, eyebrowStyle, inputStyle } from "./styles";

const LEGALITY_LABEL: Record<string, string> = {
  legal: "Legal in Commander",
  banned: "Banned in Commander",
  restricted: "Restricted in Commander",
  not_legal: "Not legal in Commander",
};

// `count`/the deck-mutation callbacks are all optional together: undefined
// means there's no deck context at all (e.g. browsing search results with
// no target deck picked yet) — a pure read-only info/rulings/printing
// view. When `count` is a number (0 included), the deck-scoped controls
// render, and "Remove one/all" only ever show once count is actually > 0.
export default function CardModal({
  name,
  cardId,
  count,
  info,
  printing,
  onChangePrinting,
  onAddOne,
  onAddMany,
  onRemoveOne,
  onRemoveAll,
  onClose,
  deckOptions,
  selectedDeckId,
  onSelectDeckId,
  owned,
  onToggleOwned,
  onNavigate,
  hasPrevious,
  hasNext,
}: {
  name: string;
  // The card's Scryfall id, for its art. Passed by the caller since it
  // usually knows it before `info` (a lazy fetch) has loaded.
  cardId?: string | null;
  count?: number;
  info: CardInfo | undefined;
  printing: SelectedPrinting | undefined;
  onChangePrinting?: (printing: SelectedPrinting) => void;
  onAddOne?: () => void;
  onAddMany?: (quantity: number) => Promise<{ added: number; failed: number; error: string | null }>;
  onRemoveOne?: () => void;
  onRemoveAll?: () => void;
  onClose: () => void;
  // Moves to the adjacent card in whatever list this modal was opened
  // from (the ledger's categorized order, or the search grid's current
  // page) — optional since not every caller has a meaningful "next card"
  // (none currently omit it, but a future bare single-card view could).
  onNavigate?: (direction: "prev" | "next") => void;
  hasPrevious?: boolean;
  hasNext?: boolean;
  // Only passed from a context with no single fixed deck (the card-search
  // page) — lets the viewer pick which deck this card should go into right
  // here, instead of the modal being scoped to whatever deck the page
  // itself is targeting. DeckView's own usage never passes these, since
  // there the deck is already fixed and unambiguous.
  deckOptions?: { id: string; label: string }[];
  selectedDeckId?: string;
  onSelectDeckId?: (id: string) => void;
  // Collection ownership isn't deck-scoped at all — shown whenever the
  // caller passes it (both DeckView and the search page do), independent
  // of `hasDeckContext`.
  owned?: boolean;
  onToggleOwned?: () => Promise<void>;
}) {
  const [showPrintingPicker, setShowPrintingPicker] = useState(false);
  const [quantity, setQuantity] = useState(1);
  const [addingOne, setAddingOne] = useState(false);
  const [addingMany, setAddingMany] = useState(false);
  const [addMessage, setAddMessage] = useState<string | null>(null);
  const [togglingOwned, setTogglingOwned] = useState(false);

  async function handleToggleOwned() {
    if (!onToggleOwned) return;
    setTogglingOwned(true);
    try {
      await onToggleOwned();
    } finally {
      setTogglingOwned(false);
    }
  }

  const hasDeckContext = count !== undefined;

  // Every card gets the same add controls — no client-side guess at which
  // cards allow more than one copy. The backend's singleton rule (basic
  // lands exempt) is the real gate; a rejected add just surfaces here as a
  // message, same as any other validation error.
  async function handleAddOne() {
    if (!onAddOne) return;
    setAddingOne(true);
    setAddMessage(null);
    try {
      await onAddOne();
    } catch (err) {
      setAddMessage(err instanceof Error ? err.message : "Couldn't add another.");
    } finally {
      setAddingOne(false);
    }
  }

  async function handleAddMany() {
    if (!onAddMany) return;
    setAddingMany(true);
    setAddMessage(null);
    try {
      const result = await onAddMany(quantity);
      if (result.failed > 0) {
        setAddMessage(
          result.added > 0
            ? `Added ${result.added} of ${quantity} — ${result.error}`
            : `Couldn't add any: ${result.error}`,
        );
      }
    } catch (err) {
      setAddMessage(err instanceof Error ? err.message : "Couldn't add those.");
    } finally {
      setAddingMany(false);
    }
  }

  // Left/Right only navigate when focus isn't in a text/number field —
  // otherwise this would hijack ordinary cursor movement inside the "Add
  // more" quantity input.
  useEffect(() => {
    if (!onNavigate) return;
    function handleKeyDown(e: KeyboardEvent) {
      const target = e.target as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA") return;
      if (e.key === "ArrowLeft" && hasPrevious) onNavigate!("prev");
      else if (e.key === "ArrowRight" && hasNext) onNavigate!("next");
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onNavigate, hasPrevious, hasNext]);

  // undefined while loading, null if the lookup failed, [] if the card
  // genuinely has no rulings.
  const [rulings, setRulings] = useState<Ruling[] | null | undefined>(undefined);
  useEffect(() => {
    setRulings(undefined);
    if (!info?.id) return;
    const id = info.id;
    let cancelled = false;
    // Debounced: arrowing through cards fires this once per card, and every
    // uncached one costs a throttled Scryfall request — waiting a beat
    // means cards you only pass through never trigger one.
    const timer = setTimeout(() => {
      getRulings(id).then((result) => {
        if (!cancelled) setRulings(result);
      });
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [info?.id]);

  const priceUsd = printing?.priceUsd ?? info?.priceUsd;

  return (
    <>
      <div
        onClick={onClose}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(20, 14, 8, 0.55)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: 24,
          zIndex: 100,
        }}
      >
        <div
          onClick={(e) => e.stopPropagation()}
          style={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 10,
            width: "100%",
            maxWidth: 920,
            maxHeight: "90vh",
            overflow: "auto",
            display: "flex",
            gap: 24,
            padding: 24,
          }}
        >
          <CardImage
            cardId={cardId ?? info?.id}
            printing={printing}
            version="normal"
            alt={name}
            style={{
              width: 320,
              aspectRatio: "488 / 680",
              flexShrink: 0,
              alignSelf: "flex-start",
              display: "block",
              borderRadius: 8,
              border: "1px solid var(--border)",
            }}
          />
          <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 10 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
              <div style={{ fontSize: 20, fontWeight: 600 }}>{name}</div>
              <button
                onClick={onClose}
                aria-label="Close"
                title="Close"
                className="btn"
                style={{ ...buttonStyle, padding: "4px 10px" }}
              >
                &times;
              </button>
            </div>

            {info?.typeLine && (
              <div style={{ fontSize: 14, fontStyle: "italic", color: "var(--text-muted)" }}>{info.typeLine}</div>
            )}

            <div style={{ fontSize: 13, color: "var(--text-muted)" }}>Printing: {printing?.setName ?? "default"}</div>

            {priceUsd && (
              <div style={{ fontSize: 14 }}>
                ${priceUsd} each
                {!!count && count > 1 && ` · $${(parseFloat(priceUsd) * count).toFixed(2)} total`}
              </div>
            )}

            {info?.legality && (
              <div style={{ fontSize: 13, color: info.legality === "legal" ? "var(--text-muted)" : "var(--accent)" }}>
                {LEGALITY_LABEL[info.legality] ?? info.legality}
              </div>
            )}

            {onToggleOwned && (
              <button
                onClick={handleToggleOwned}
                disabled={togglingOwned}
                className="btn"
                style={
                  owned
                    ? { ...buttonStyle, alignSelf: "flex-start", borderColor: "var(--accent)", color: "var(--accent)" }
                    : { ...buttonStyle, alignSelf: "flex-start" }
                }
              >
                {togglingOwned ? "…" : owned ? "✓ In my collection" : "+ Add to my collection"}
              </button>
            )}

            {deckOptions && (
              <div>
                <div style={eyebrowStyle}>ADD TO DECK</div>
                <select
                  value={selectedDeckId ?? ""}
                  onChange={(e) => onSelectDeckId?.(e.target.value)}
                  style={{ ...inputStyle, width: "100%" }}
                >
                  <option value="">Choose a deck…</option>
                  {deckOptions.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.label}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {hasDeckContext && (
              <div style={{ fontSize: 14, fontWeight: 600 }}>
                {count} {count === 1 ? "copy" : "copies"} in this deck
              </div>
            )}

            {hasDeckContext && (
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "flex-start",
                  gap: 8,
                  paddingTop: 4,
                  paddingBottom: 4,
                }}
              >
                {onAddOne && (
                  <button onClick={handleAddOne} disabled={addingOne} className="btn" style={buttonStyle}>
                    {addingOne ? "Adding…" : "+ Add one"}
                  </button>
                )}
                {onAddMany && (
                  <div style={{ display: "flex", gap: 8 }}>
                    <input
                      type="number"
                      min={1}
                      max={40}
                      value={quantity}
                      onChange={(e) => setQuantity(Math.max(1, parseInt(e.target.value, 10) || 1))}
                      style={{ ...inputStyle, width: 64, textAlign: "center" }}
                    />
                    <button onClick={handleAddMany} disabled={addingMany} className="btn" style={buttonStyle}>
                      {addingMany ? "Adding…" : "Add more"}
                    </button>
                  </div>
                )}
                {onRemoveOne && !!count && count > 0 && (
                  <button onClick={onRemoveOne} className="btn btn-danger" style={buttonStyle}>
                    Remove one{count > 1 ? ` (${count} in deck)` : ""}
                  </button>
                )}
                {onRemoveAll && !!count && count > 1 && (
                  <button onClick={onRemoveAll} className="btn btn-danger" style={buttonStyle}>
                    Remove all {count}
                  </button>
                )}
                {onChangePrinting && (
                  <button onClick={() => setShowPrintingPicker(true)} className="btn" style={buttonStyle}>
                    Change printing
                  </button>
                )}
              </div>
            )}

            {addMessage && <div style={{ fontSize: 13, color: "var(--danger)" }}>{addMessage}</div>}

            {info?.oracleText && (
              <div style={{ fontSize: 14, lineHeight: 1.5, whiteSpace: "pre-wrap" }}>{info.oracleText}</div>
            )}

            {info?.id && (
              <div>
                <div style={eyebrowStyle}>RULINGS</div>
                {rulings === undefined ? (
                  <div style={{ fontSize: 13, color: "var(--text-muted)" }}>Loading rulings…</div>
                ) : rulings === null ? (
                  <div style={{ fontSize: 13, color: "var(--text-muted)" }}>
                    Couldn't load rulings right now — close and reopen this card to try again.
                  </div>
                ) : rulings.length === 0 ? (
                  <div style={{ fontSize: 13, color: "var(--text-muted)" }}>No rulings for this card.</div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {rulings.map((ruling, i) => (
                      <div key={i} style={{ fontSize: 13, lineHeight: 1.5 }}>
                        <span style={{ color: "var(--text-muted)" }}>{ruling.publishedAt}</span> — {ruling.comment}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {onNavigate && hasPrevious && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onNavigate("prev");
          }}
          aria-label="Previous card"
          title="Previous card"
          className="btn"
          style={{
            position: "fixed",
            left: 24,
            top: "50%",
            transform: "translateY(-50%)",
            zIndex: 101,
            fontSize: 22,
            lineHeight: 1,
            padding: "10px 16px",
            borderRadius: 999,
          }}
        >
          &lsaquo;
        </button>
      )}

      {onNavigate && hasNext && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onNavigate("next");
          }}
          aria-label="Next card"
          title="Next card"
          className="btn"
          style={{
            position: "fixed",
            right: 24,
            top: "50%",
            transform: "translateY(-50%)",
            zIndex: 101,
            fontSize: 22,
            lineHeight: 1,
            padding: "10px 16px",
            borderRadius: 999,
          }}
        >
          &rsaquo;
        </button>
      )}

      {showPrintingPicker && onChangePrinting && (
        <PrintingPicker
          name={name}
          onSelect={(selected) => {
            onChangePrinting(selected);
            setShowPrintingPicker(false);
          }}
          onClose={() => setShowPrintingPicker(false)}
        />
      )}
    </>
  );
}
