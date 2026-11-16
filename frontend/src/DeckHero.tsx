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
  backTo = { to: "/decks", label: "← ALL DECKS" },
  byline,
  isPrivate = false,
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
  // Where the way back goes, and what it says.
  backTo?: { to: string; label: string };
  // Who built the deck, as a username, when it is known and other people are looking.
  byline?: string | null;
  // Shows a Private badge, for the owner looking at a deck only they can see.
  isPrivate?: boolean;
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
          <Link to={backTo.to} className="dv-back">
            {backTo.label}
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
          {isPrivate && (
            <span className="dv-badge" title="Only you can see this deck">
              Private
            </span>
          )}
          {colorIdentity.length > 0 && (
            <span className="dv-badge">
              <ManaPips colors={colorIdentity} size={14} />
            </span>
          )}
        </div>
        <div className="dv-meta">
          {byline && (
            <span>
              by <strong>{byline}</strong>
            </span>
          )}
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
