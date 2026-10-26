import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getHub, type DeckDiscoveries, type Hub, type NewCommanders as CommanderPicks } from "./api";
import DeckTile from "./DeckTile";
import DoctorsOrders from "./DoctorsOrders";
import NewCards from "./NewCards";
import NewCommanders from "./NewCommanders";
import { buttonStyle, eyebrowStyle } from "./styles";

// The landing page: what's new that could work in your decks, then the decks
// themselves — and, folded away until you ask, swaps the Doctor would try.
// It opens on discovery, not on what might be wrong with the decks.
export default function HubView() {
  const [hub, setHub] = useState<Hub | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setHub(await getHub());
      setError(null);
    } catch {
      setError("Couldn't reach the Deck Doctor backend. Is it running on port 8000?");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function handleDeleted() {
    load();
  }

  // The Doctor finished looking through the new commanders.
  function handleCommanders(commanders: CommanderPicks) {
    setHub((prev) => (prev ? { ...prev, commanders } : prev));
  }

  // The Doctor finished looking through the new cards for one deck.
  function handleDiscoveries(deckId: string, discoveries: DeckDiscoveries) {
    setHub((prev) =>
      prev ? { ...prev, decks: prev.decks.map((d) => (d.id === deckId ? { ...d, discoveries } : d)) } : prev,
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 32 }}>
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          borderBottom: "1px solid var(--border)",
          paddingBottom: 16,
        }}
      >
        <div style={eyebrowStyle}>MTG DECK DOCTOR</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
          {/* The decks sit below the new cards and commanders, so this is the way to them. */}
          {hub && hub.decks.length > 0 && (
            <button
              type="button"
              className="btn"
              style={buttonStyle}
              onClick={() => document.getElementById("your-decks")?.scrollIntoView({ behavior: "smooth", block: "start" })}
            >
              Your decks ({hub.decks.length})
            </button>
          )}
          <Link
            to="/search/results?collection=1"
            className="btn"
            style={{ ...buttonStyle, textDecoration: "none", display: "inline-block" }}
          >
            My collection
          </Link>
          <Link to="/search" className="btn" style={{ ...buttonStyle, textDecoration: "none", display: "inline-block" }}>
            Search cards
          </Link>
          <Link to="/new" className="btn" style={{ ...buttonStyle, textDecoration: "none", display: "inline-block" }}>
            New deck
          </Link>
        </div>
      </header>

      {error && <div style={{ color: "var(--danger)", fontSize: 14 }}>{error}</div>}
      {hub === null && !error && <div style={{ color: "var(--text-muted)", fontSize: 14 }}>Loading…</div>}

      {hub && <NewCards hub={hub} onDiscoveries={handleDiscoveries} />}
      {hub && <NewCommanders hub={hub} onPicks={handleCommanders} />}

      {hub && (
        <section id="your-decks" style={{ scrollMarginTop: 16 }}>
          <div style={{ ...eyebrowStyle, fontSize: 12, marginBottom: 12 }}>YOUR DECKS</div>
          {hub.decks.length === 0 ? (
            <div style={{ color: "var(--text-muted)", fontSize: 14 }}>No decks yet — start one with "New deck".</div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 16 }}>
              {hub.decks.map((deck) => (
                <DeckTile key={deck.id} deck={deck} onDeleted={handleDeleted} />
              ))}
            </div>
          )}
        </section>
      )}

      {hub && hub.orders.length > 0 && (
        <details>
          <summary style={{ cursor: "pointer", fontSize: 15, color: "var(--accent)" }}>
            Ideas for your decks ({hub.orders.length + hub.more_swaps} swaps the Doctor has worked out)
          </summary>
          <div style={{ marginTop: 16 }}>
            <DoctorsOrders hub={hub} onChanged={load} />
          </div>
        </details>
      )}
    </div>
  );
}
