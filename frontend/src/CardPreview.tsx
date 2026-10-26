import CardImage from "./CardImage";
import type { SelectedPrinting } from "./printings";
import { eyebrowStyle } from "./styles";

// Moxfield-style hover preview: a single sticky panel that always shows
// whichever card was most recently hovered, instead of each card zooming
// in place. Replaces an earlier per-card hover-zoom + floating button panel
// that fought the DOM (the zoomed card and its buttons lived in different
// hit-test regions, so reaching one from the other was unreliable) — a
// single fixed-position panel has no such gap to cross.
export default function CardPreview({
  name,
  cardId,
  printing,
  priceUsd,
}: {
  name: string | null;
  cardId: string | null | undefined;
  printing: SelectedPrinting | undefined;
  // One copy's price, as Scryfall gives it. Nothing is shown without one.
  priceUsd?: string | null;
}) {
  return (
    <div style={{ position: "sticky", top: 16, width: 240, flexShrink: 0, alignSelf: "flex-start" }}>
      <div style={eyebrowStyle}>PREVIEW</div>
      {name ? (
        <>
          <CardImage
            key={name}
            cardId={cardId}
            printing={printing}
            version="normal"
            alt={name}
            style={{
              width: "100%",
              display: "block",
              borderRadius: 10,
              border: "1px solid var(--border)",
              boxShadow: "0 10px 26px rgba(0, 0, 0, 0.3)",
            }}
          />
          {priceUsd && (
            <div style={{ marginTop: 10, textAlign: "center", fontSize: 18, fontWeight: 600 }}>
              ${parseFloat(priceUsd).toFixed(2)}
              {printing && <div style={{ fontSize: 12, fontWeight: 400, color: "var(--text-muted)" }}>{printing.setName}</div>}
            </div>
          )}
        </>
      ) : (
        <div
          style={{
            width: "100%",
            aspectRatio: "488 / 680",
            border: "1px dashed var(--border)",
            borderRadius: 10,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 16,
            color: "var(--text-muted)",
            fontSize: 13,
            textAlign: "center",
          }}
        >
          Hover a card to preview it here
        </div>
      )}
    </div>
  );
}
