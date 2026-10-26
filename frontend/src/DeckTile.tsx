import { useState, type MouseEvent } from "react";
import { Link } from "react-router-dom";
import { deleteDeck, scryfallImageUrlById, type HubDeck } from "./api";
import ManaPips from "./ManaPips";
import { relativeTime } from "./relativeTime";
import { buttonStyle } from "./styles";

const tileStyle = {
  display: "block",
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: 12,
  overflow: "hidden",
  textDecoration: "none",
  color: "inherit",
  boxShadow: "0 2px 10px rgba(43, 32, 24, 0.08)",
} as const;

// One deck on the shelf: the commander's art and what the deck is. Nothing
// about what might be wrong with it — that is for the deck's own page.
export default function DeckTile({ deck, onDeleted }: { deck: HubDeck; onDeleted: (id: string) => void }) {
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleDelete(e: MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setDeleting(true);
    setError(null);
    try {
      await deleteDeck(deck.id);
      onDeleted(deck.id);
    } catch {
      setError("Couldn't delete that deck. Try again.");
      setDeleting(false);
    }
  }

  if (confirming) {
    return (
      <div style={{ ...tileStyle, padding: 16 }}>
        <div style={{ fontSize: 15 }}>
          Delete <strong>{deck.title}</strong>? This can't be undone.
        </div>
        {error && <div style={{ color: "var(--danger)", fontSize: 13, marginTop: 6 }}>{error}</div>}
        <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
          <button onClick={handleDelete} disabled={deleting} className="btn btn-danger" style={buttonStyle}>
            {deleting ? "Deleting…" : "Delete"}
          </button>
          <button onClick={() => setConfirming(false)} className="btn" style={buttonStyle}>
            Cancel
          </button>
        </div>
      </div>
    );
  }

  return (
    <Link to={`/decks/${deck.id}`} style={tileStyle}>
      <div style={{ position: "relative", height: 150, background: "var(--user-bubble)" }}>
        {deck.commander_id && (
          <img
            src={scryfallImageUrlById(deck.commander_id, "art_crop")}
            alt=""
            loading="lazy"
            style={{ width: "100%", height: "100%", objectFit: "cover", objectPosition: "center 30%", display: "block" }}
          />
        )}
        <button
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            setConfirming(true);
          }}
          aria-label={`Delete ${deck.title}`}
          title="Delete deck"
          className="btn btn-danger"
          style={{ position: "absolute", top: 8, right: 8, width: 24, height: 24, borderRadius: "50%", padding: 0, lineHeight: "22px", cursor: "pointer" }}
        >
          &times;
        </button>
      </div>
      <div style={{ padding: "12px 14px 14px" }}>
        <div style={{ fontSize: 18, fontWeight: 600, lineHeight: 1.25 }}>{deck.title}</div>
        {deck.commander && deck.commander !== deck.title && (
          <div style={{ fontSize: 13, fontStyle: "italic", color: "var(--text-muted)" }}>{deck.commander}</div>
        )}
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--text-muted)", marginTop: 6 }}>
          <ManaPips colors={deck.color_identity} size={14} />
          <span>
            {deck.card_count}/100 · ${Math.round(deck.price_usd)}
          </span>
        </div>
        <div style={{ marginTop: 10, fontSize: 13, color: "var(--text-muted)" }}>
          Edited {relativeTime(deck.updated_at)}
        </div>
      </div>
    </Link>
  );
}
