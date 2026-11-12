import DeckTile from "./DeckTile";
import DoctorsOrders from "./DoctorsOrders";
import { eyebrowStyle } from "./styles";
import { useHub } from "./useHub";

// Your decks: the shelf, and, folded away until you ask, the swaps the Doctor would try.
export default function DecksPage() {
  const { hub, error, load } = useHub();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 32 }}>
      {error && <div style={{ color: "var(--danger)", fontSize: 14 }}>{error}</div>}
      {hub === null && !error && <div style={{ color: "var(--text-muted)", fontSize: 14 }}>Loading…</div>}

      {hub && (
        <section>
          <div style={{ ...eyebrowStyle, fontSize: 12, marginBottom: 12 }}>YOUR DECKS</div>
          {hub.decks.length === 0 ? (
            <div style={{ color: "var(--text-muted)", fontSize: 14 }}>No decks yet — start one with "New deck".</div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 16 }}>
              {hub.decks.map((deck) => (
                <DeckTile key={deck.id} deck={deck} onDeleted={load} />
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
