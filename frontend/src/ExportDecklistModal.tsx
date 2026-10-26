import { useState } from "react";
import { buttonStyle } from "./styles";

export default function ExportDecklistModal({ text, onClose }: { text: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access can fail (permissions, insecure context) — the
      // text is still selectable by hand from the textarea below.
    }
  }

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(20, 14, 8, 0.55)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
        zIndex: 100,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: 10,
          width: "100%",
          maxWidth: 560,
          maxHeight: "85vh",
          overflow: "auto",
          padding: 24,
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontSize: 18, fontWeight: 600 }}>Export decklist</div>
          <button onClick={onClose} aria-label="Close" className="btn" style={{ ...buttonStyle, padding: "4px 10px" }}>
            &times;
          </button>
        </div>
        <div style={{ fontSize: 13, color: "var(--text-muted)" }}>
          Paste this into Moxfield, Archidekt, TappedOut, or any other deckbuilder's import box.
        </div>
        <textarea
          readOnly
          value={text}
          rows={16}
          onFocus={(e) => e.currentTarget.select()}
          style={{
            width: "100%",
            fontFamily: "monospace",
            fontSize: 13,
            padding: 10,
            background: "var(--bg)",
            color: "var(--text)",
            border: "1px solid var(--border)",
            borderRadius: 4,
            resize: "vertical",
          }}
        />
        <button onClick={handleCopy} className="btn" style={buttonStyle}>
          {copied ? "Copied!" : "Copy to clipboard"}
        </button>
      </div>
    </div>
  );
}
