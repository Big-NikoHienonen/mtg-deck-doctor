import { Link } from "react-router-dom";
import { type DeckDiscoveries, type NewCommanders as CommanderPicks } from "./api";
import NewCards from "./NewCards";
import NewCommanders from "./NewCommanders";
import NewSetLinks from "./NewSetLinks";
import { buttonStyle } from "./styles";
import { useHub } from "./useHub";

// The landing page: what's new that could work in your decks. The decks themselves, and the swaps the
// Doctor would try, are on their own page (DecksPage.tsx). It opens on discovery, not on what might be
// wrong with the decks.
export default function LandingView() {
  const { hub, setHub, error } = useHub();

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
      {error && <div style={{ color: "var(--danger)", fontSize: 14 }}>{error}</div>}
      {hub === null && !error && <div style={{ color: "var(--text-muted)", fontSize: 14 }}>Loading…</div>}

      {hub && ((hub.latest_sets?.releases.length ?? 0) > 0 || hub.decks.length > 0) && (
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
          <NewSetLinks hub={hub} />
          {hub.decks.length > 0 && (
            <Link to="/decks" className="btn" style={{ ...buttonStyle, textDecoration: "none", display: "inline-block" }}>
              Your decks ({hub.decks.length}) →
            </Link>
          )}
        </div>
      )}
      {hub && <NewCards hub={hub} onDiscoveries={handleDiscoveries} />}
      {hub && <NewCommanders hub={hub} onPicks={handleCommanders} />}
    </div>
  );
}
