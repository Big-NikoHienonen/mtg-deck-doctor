import CardImage from "./CardImage";
import FoilSheen from "./FoilSheen";
import type { SelectedPrinting } from "./printings";

// Beside the list: the card last pointed at (the commander until something is), its price,
// and what you can do with it.
export default function DeckSidebar({
  name,
  cardId,
  printing,
  priceUsd,
  inDeck,
  owned,
  onToggleOwned,
  onOpen,
}: {
  name: string | null;
  cardId: string | null | undefined;
  printing: SelectedPrinting | undefined;
  priceUsd: string | null | undefined;
  inDeck: boolean;
  owned: boolean;
  // Left off where the collection isn't the viewer's to change (a deck seen signed out).
  onToggleOwned?: () => void;
  onOpen: () => void;
}) {
  const price = priceUsd ? parseFloat(priceUsd).toFixed(2) : null;
  return (
    <aside className="dv-side" aria-label="Card preview">
      {name ? (
        <div key={name} style={{ position: "relative" }}>
          <CardImage cardId={cardId} printing={printing} version="normal" alt={name} />
          {printing?.foil && <FoilSheen />}
        </div>
      ) : (
        <div className="dv-blank">Point at a card to see it here</div>
      )}
      {name && (
        <>
          <div className="dv-price-line">
            {price ? <strong>${price}</strong> : <span className="dv-muted">No price</span>}
            {printing && (
              <span className="dv-muted">
                {printing.setName}
                {printing.foil && " · foil"}
              </span>
            )}
          </div>
          <a
            className="dv-buy"
            data-primary="true"
            href={`https://www.tcgplayer.com/search/magic/product?productLineName=magic&q=${encodeURIComponent(name)}&view=grid`}
            target="_blank"
            rel="noreferrer"
          >
            <span>Buy @ TCGplayer</span>
            {price && <strong>${price}</strong>}
          </a>
          {inDeck && onToggleOwned && (
            <button className="dv-buy" onClick={onToggleOwned}>
              <span>{owned ? "✓ In your collection" : "Mark as owned"}</span>
            </button>
          )}
          {inDeck && (
            <button className="dv-buy" onClick={onOpen}>
              <span>Card details</span>
            </button>
          )}
        </>
      )}
    </aside>
  );
}
