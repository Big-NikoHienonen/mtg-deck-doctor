import { useEffect, useState } from "react";
import { shareDeck, unshareDeck, type Deck } from "./api";
import { buttonStyle } from "./styles";

// Whether this address can be reached from another computer: a link to localhost can't.
const onThisComputerOnly = ["localhost", "127.0.0.1", "[::1]"].includes(window.location.hostname);

// "Share": turns the deck's link on or off. The link opens a view of the cards, with no way to change
// the deck or use the Doctor, and nothing else about the deck.
export default function ShareDeckModal({ deck, onChange, onClose }: { deck: Deck; onChange: (deck: Deck) => void; onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const link = deck.share_token ? `${window.location.origin}/s/${deck.share_token}` : null;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function change(turnOn: boolean) {
    setBusy(true);
    setError(null);
    setCopied(false);
    try {
      onChange(await (turnOn ? shareDeck(deck.id) : unshareDeck(deck.id)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "That didn't work.");
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access can fail (permissions, an insecure page): the link is selectable by hand.
    }
  }

  return (
    <div
      onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(20, 14, 8, 0.55)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24, zIndex: 100 }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Share this deck"
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: 10,
          width: "100%",
          maxWidth: 520,
          padding: 24,
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontSize: 18, fontWeight: 600 }}>Share this deck</div>
          <button onClick={onClose} aria-label="Close" className="btn" style={{ ...buttonStyle, padding: "4px 10px" }}>
            &times;
          </button>
        </div>
        <div style={{ fontSize: 14, lineHeight: 1.5 }}>
          Anyone with the link can look at this deck's cards. They can't change it, and they can't use the Doctor. Your chat with the Doctor, what you own, and the printings you picked stay private.
        </div>

        {link ? (
          <>
            <input
              readOnly
              value={link}
              aria-label="Share link"
              onFocus={(e) => e.currentTarget.select()}
              style={{ width: "100%", fontFamily: "monospace", fontSize: 13, padding: 10, background: "var(--bg)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 4 }}
            />
            {onThisComputerOnly && (
              <div style={{ fontSize: 13, color: "var(--text-muted)", lineHeight: 1.5 }}>
                This address only works on this computer. A link opens for other people once the app is online.
              </div>
            )}
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button onClick={copy} className="btn" style={buttonStyle}>
                {copied ? "Copied!" : "Copy link"}
              </button>
              <button onClick={() => change(false)} disabled={busy} className="btn btn-danger" style={buttonStyle}>
                {busy ? "…" : "Stop sharing"}
              </button>
            </div>
            <div style={{ fontSize: 13, color: "var(--text-muted)", lineHeight: 1.5 }}>
              Stopping ends this link for good: it opens nothing, even if you share the deck again. Sharing again makes a new link.
            </div>
          </>
        ) : (
          <button onClick={() => change(true)} disabled={busy} className="btn" style={{ ...buttonStyle, alignSelf: "flex-start" }}>
            {busy ? "…" : "Create link"}
          </button>
        )}
        {error && <div style={{ fontSize: 14, color: "var(--danger)" }}>{error}</div>}
      </div>
    </div>
  );
}
