import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import ManaPips from "./ManaPips";
import { cardImageUrl, type SelectedPrinting } from "./printings";
import { relativeTime } from "./relativeTime";

// The top of the deck page: the commander's art behind the deck's name, and what the deck comes to.
export default function DeckHero({
  commander,
  commanderId,
  printing,
  showCommander,
  onOpenCommander,
  showBack = true,
  title,
  colorIdentity,
  cardCount,
  price,
  costToComplete,
  updatedAt,
  warning,
}: {
  commander: string | null;
  commanderId: string | null | undefined;
  printing: SelectedPrinting | undefined;
  // Whether to name the commander above the title (when the deck has a name of its own).
  showCommander: boolean;
  // Opens the commander's card details.
  onOpenCommander: () => void;
  // The way back to the owner's decks. Left off for someone who isn't signed in.
  showBack?: boolean;
  // The name, as a heading; the page decides how it is renamed.
  title: ReactNode;
  colorIdentity: string[];
  cardCount: number;
  price: number;
  costToComplete: number;
  updatedAt: string | undefined;
  warning: ReactNode;
}) {
  const art = cardImageUrl(commanderId, printing, "art_crop");
  return (
    <header className="dv-hero">
      {art && <div className="dv-hero-art" style={{ backgroundImage: `url(${art})` }} />}
      <div className="dv-container dv-hero-body">
        {showBack ? (
          <Link to="/decks" className="dv-back">
            ← ALL DECKS
          </Link>
        ) : null}
        <div className="dv-spacer" />
        {showCommander && commander && (
          <button type="button" className="dv-owner" onClick={onOpenCommander}>
            {art && <span className="dv-avatar" style={{ backgroundImage: `url(${art})` }} />}
            {commander}
          </button>
        )}
        {title}
        <div className="dv-badges">
          <span className="dv-badge">Commander</span>
          {colorIdentity.length > 0 && (
            <span className="dv-badge">
              <ManaPips colors={colorIdentity} size={14} />
            </span>
          )}
        </div>
        <div className="dv-meta">
          <span>{cardCount}/100 cards</span>
          <span>${price.toFixed(2)}</span>
          {costToComplete > 0 && costToComplete < price && <span>${costToComplete.toFixed(2)} to complete</span>}
          {updatedAt && <span>Last updated {relativeTime(updatedAt)}</span>}
          {warning}
        </div>
      </div>
    </header>
  );
}
