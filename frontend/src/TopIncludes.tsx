import { useState } from "react";
import type { CommanderIncludes } from "./api";
import { buttonStyle, eyebrowStyle } from "./styles";

const PAGE_SIZE = 15;

// EDHREC's most-played cards for this commander that the deck doesn't have
// yet. The diff against the deck (and the ownership flag) happens here at
// render time rather than on the backend, so adding a card or toggling
// ownership updates the list instantly with no refetch.
export default function TopIncludes({
  includes,
  deckNames,
  ownedCards,
  onAdd,
  onHoverCard,
}: {
  includes: CommanderIncludes | null;
  deckNames: Set<string>;
  ownedCards: Set<string>;
  onAdd: (name: string) => Promise<void>;
  onHoverCard: (name: string, id?: string | null) => void;
}) {
  const [onlyOwned, setOnlyOwned] = useState(false);
  const [shown, setShown] = useState(PAGE_SIZE);
  const [adding, setAdding] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  async function handleAdd(name: string) {
    setAdding(name);
    setErrors((prev) => ({ ...prev, [name]: "" }));
    try {
      await onAdd(name);
    } catch (err) {
      setErrors((prev) => ({ ...prev, [name]: err instanceof Error ? err.message : "Couldn't add it." }));
    } finally {
      setAdding(null);
    }
  }

  if (includes === null) {
    return (
      <section>
        <div style={eyebrowStyle}>POPULAR CARDS YOUR DECK IS MISSING</div>
        <div style={{ fontSize: 14, color: "var(--text-muted)" }}>Loading EDHREC data…</div>
      </section>
    );
  }

  if (!includes.available) {
    return (
      <section>
        <div style={eyebrowStyle}>POPULAR CARDS YOUR DECK IS MISSING</div>
        <div style={{ fontSize: 14, color: "var(--text-muted)" }}>{includes.reason}</div>
      </section>
    );
  }

  const missing = includes.cards.filter((c) => !deckNames.has(c.name));
  const ownedMissing = missing.filter((c) => ownedCards.has(c.name));
  const visible = (onlyOwned ? ownedMissing : missing).slice(0, shown);
  const total = onlyOwned ? ownedMissing.length : missing.length;

  return (
    <section>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12 }}>
        <div style={eyebrowStyle}>POPULAR CARDS YOUR DECK IS MISSING</div>
        <button
          onClick={() => {
            setOnlyOwned((v) => !v);
            setShown(PAGE_SIZE);
          }}
          className="btn"
          style={
            onlyOwned
              ? { ...buttonStyle, fontSize: 12, padding: "3px 10px", borderColor: "var(--accent)", color: "var(--accent)" }
              : { ...buttonStyle, fontSize: 12, padding: "3px 10px" }
          }
        >
          Only cards I own ({ownedMissing.length})
        </button>
      </div>
      <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 8 }}>
        The cards most {includes.num_decks.toLocaleString()} EDHREC decks for this commander run that yours doesn't.
        The percentage is how many of those decks play the card.
      </div>

      {total === 0 && (
        <div style={{ fontSize: 14, color: "var(--text-muted)" }}>
          {onlyOwned
            ? "You don't own any of EDHREC's suggested cards that this deck is missing."
            : "Your deck already has everything EDHREC lists for this commander."}
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column" }}>
        {visible.map((card) => {
          const pct = Math.round(card.inclusion * 100);
          const owned = ownedCards.has(card.name);
          return (
            <div
              key={card.name}
              className="card-row"
              onMouseEnter={() => onHoverCard(card.name, card.id)}
              style={{ padding: "7px 4px", borderBottom: "1px solid var(--border)" }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: 600, display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
                    {card.name}
                    {owned && <span style={{ fontSize: 11, color: "var(--accent)", fontWeight: 600 }}>✓ OWNED</span>}
                    {card.game_changer && (
                      <span style={{ fontSize: 11, color: "var(--accent-gold)", fontWeight: 600 }}>GAME CHANGER</span>
                    )}
                    {card.is_new && <span style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 600 }}>NEW</span>}
                  </div>
                  <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                    {card.category}
                    {card.synergy >= 0.1 && ` · +${Math.round(card.synergy * 100)}% synergy`}
                  </div>
                </div>
                <div
                  title={`${card.num_decks.toLocaleString()} of ${card.potential_decks.toLocaleString()} decks`}
                  style={{ width: 120 }}
                >
                  <div style={{ fontSize: 12, textAlign: "right" }}>{pct}% of decks</div>
                  <div style={{ height: 4, background: "var(--user-bubble)", borderRadius: 2, marginTop: 2 }}>
                    <div style={{ width: `${pct}%`, height: "100%", background: "var(--accent-gold)", borderRadius: 2 }} />
                  </div>
                </div>
                <button
                  onClick={() => handleAdd(card.name)}
                  disabled={adding === card.name}
                  className="btn"
                  style={{ ...buttonStyle, fontSize: 12, padding: "4px 10px" }}
                >
                  {adding === card.name ? "Adding…" : "Add"}
                </button>
              </div>
              {errors[card.name] && (
                <div style={{ fontSize: 12, color: "var(--danger)", marginTop: 4 }}>{errors[card.name]}</div>
              )}
            </div>
          );
        })}
      </div>

      {total > shown && (
        <button onClick={() => setShown((n) => n + PAGE_SIZE)} className="btn" style={{ ...buttonStyle, marginTop: 10 }}>
          Show {Math.min(PAGE_SIZE, total - shown)} more
        </button>
      )}
    </section>
  );
}
