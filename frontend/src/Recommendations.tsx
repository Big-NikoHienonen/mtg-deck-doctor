import { useEffect, useRef, useState } from "react";
import { aiBlocked } from "./aiStatus";
import { addCard, getSuggestions, refreshSuggestions, type Deck, type Suggestions } from "./api";
import CardImage from "./CardImage";
import { relativeTime } from "./relativeTime";
import { buttonStyle, eyebrowStyle } from "./styles";

// Below this the model has little to go on and mostly guesses — the EDHREC
// list is the better answer for a near-empty deck, so generation waits for
// an explicit click instead of happening on its own.
const AUTO_SUGGEST_MIN_CARDS = 10;

// Generation takes ~10s and costs tokens, so one request per deck at a
// time, shared by whoever asks: React's dev-mode double mount (or leaving
// the page and coming back mid-generation) would otherwise fire it twice.
const inFlight = new Map<string, Promise<Suggestions>>();

function requestSuggestions(deckId: string): Promise<Suggestions> {
  let request = inFlight.get(deckId);
  if (!request) {
    request = refreshSuggestions(deckId).finally(() => inFlight.delete(deckId));
    inFlight.set(deckId, request);
  }
  return request;
}

export default function Recommendations({
  deck,
  onDeckChange,
  onHoverCard,
  ownedCards,
  paused,
}: {
  deck: Deck;
  onDeckChange: (deck: Deck) => void;
  onHoverCard: (name: string, id?: string | null) => void;
  ownedCards: Set<string>;
  // True while an import is running. Generating suggestions makes its own
  // Scryfall lookups, so it holds off until the import is done — and the
  // import finishing is what starts it, if the deck now qualifies.
  paused: boolean;
}) {
  // undefined while the stored set is loading, null once we know there is none.
  const [suggestions, setSuggestions] = useState<Suggestions | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Set when suggestions should be generated on their own; acted on once
  // nothing is paused.
  const [autoPending, setAutoPending] = useState(false);

  async function generate() {
    setBusy(true);
    setError(null);
    try {
      setSuggestions(await requestSuggestions(deck.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't get suggestions. Try again.");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    setSuggestions(undefined);
    setError(null);
    getSuggestions(deck.id)
      .then((stored) => {
        if (cancelled) return;
        setSuggestions(stored);
        if (inFlight.has(deck.id) || (stored === null && deck.cards.length >= AUTO_SUGGEST_MIN_CARDS)) {
          setAutoPending(true);
        }
      })
      .catch(() => {
        if (cancelled) return;
        setSuggestions(null);
        setError("Couldn't load suggestions.");
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deck.id]);

  useEffect(() => {
    if (!autoPending || paused) return;
    setAutoPending(false);
    // Not while the Doctor is known to be unavailable; the button is still there.
    if (aiBlocked()) return;
    generate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoPending, paused]);

  // An import that just finished: the deck may now be big enough to have
  // suggestions written for it, and none have been.
  const wasPaused = useRef(paused);
  useEffect(() => {
    if (wasPaused.current && !paused && suggestions === null && !busy && deck.cards.length >= AUTO_SUGGEST_MIN_CARDS) {
      setAutoPending(true);
    }
    wasPaused.current = paused;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paused]);

  async function handleAdd(name: string) {
    try {
      onDeckChange(await addCard(deck.id, name));
      setSuggestions((prev) =>
        prev ? { ...prev, recommendations: prev.recommendations.filter((r) => r.name !== name) } : prev,
      );
    } catch {
      setError(`Couldn't add ${name}. Try adding it manually.`);
    }
  }

  const recommendations = suggestions?.recommendations ?? [];
  const tooSmall = deck.cards.length < AUTO_SUGGEST_MIN_CARDS;

  return (
    <section>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12 }}>
        <div style={eyebrowStyle}>MORE CARDS THE DOCTOR WOULD ADD</div>
        <button
          className="btn"
          style={{ ...buttonStyle, fontSize: 12, padding: "3px 10px" }}
          onClick={generate}
          disabled={busy || suggestions === undefined}
        >
          {busy ? "Thinking…" : suggestions ? "Refresh suggestions" : "Get suggestions"}
        </button>
      </div>

      {suggestions && (
        <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 8 }}>
          Written {relativeTime(suggestions.generated_at)}, grounded in Scryfall and EDHREC data.
          {suggestions.deck_changed && " Your deck has changed since — refresh for suggestions that fit it as it is now."}
        </div>
      )}

      {busy && (
        <div style={{ color: "var(--text-muted)", fontSize: 14 }}>The Doctor is thinking… this takes about ten seconds.</div>
      )}

      {error && <div style={{ color: "var(--danger)", fontSize: 13, marginTop: 6 }}>{error}</div>}

      {!busy && suggestions === null && !error && (
        <div style={{ color: "var(--text-muted)", fontSize: 14 }}>
          {tooSmall
            ? "Add a few more cards and the Doctor will have something to go on — or ask for suggestions now."
            : "No suggestions yet."}
        </div>
      )}

      {!busy && suggestions && recommendations.length === 0 && (
        <div style={{ color: "var(--text-muted)", fontSize: 14 }}>
          Everything suggested is already in your deck — refresh for new ideas.
        </div>
      )}

      {recommendations.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 8 }}>
          {recommendations.map((rec) => (
            <div
              key={rec.name}
              style={{
                display: "flex",
                gap: 12,
                background: "var(--surface)",
                border: "1px solid var(--border)",
                borderRadius: 6,
                padding: 12,
              }}
            >
              <CardImage
                cardId={rec.id}
                version="small"
                alt={rec.name}
                title={rec.name}
                onMouseEnter={() => onHoverCard(rec.name, rec.id)}
                style={{ width: 90, flexShrink: 0, display: "block", borderRadius: 6, border: "1px solid var(--border)" }}
              />
              <div style={{ display: "flex", flexDirection: "column", gap: 6, flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
                  <div style={{ fontWeight: 600 }}>{rec.name}</div>
                  {rec.price_usd && (
                    <div style={{ fontSize: 12, color: "var(--text-muted)", whiteSpace: "nowrap" }}>${rec.price_usd}</div>
                  )}
                </div>
                {ownedCards.has(rec.name) && (
                  <div style={{ fontSize: 12, color: "var(--accent)" }}>✓ Already in your collection</div>
                )}
                <div style={{ fontSize: 14, lineHeight: 1.4 }}>{rec.reason}</div>
                <button
                  className="btn"
                  style={{ ...buttonStyle, alignSelf: "flex-start" }}
                  onClick={() => handleAdd(rec.name)}
                >
                  Add to deck
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
