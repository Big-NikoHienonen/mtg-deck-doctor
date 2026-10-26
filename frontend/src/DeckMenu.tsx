import { useEffect, useRef, useState } from "react";
import { buttonStyle } from "./styles";

const menuItemStyle = { ...buttonStyle, textAlign: "left" as const, width: "100%" };

// A "⋮" dropdown for deck-level actions that don't need to live in the main
// header — same in-page-confirm pattern HubView's own delete button uses
// (no window.confirm(), which is unreliable to test and poor UX), just
// nested inside a menu instead of swapped into a list row.
export default function DeckMenu({
  onAddToCollection,
  onRefreshCardData,
  onImport,
  onExport,
  onDuplicate,
  onDelete,
}: {
  onAddToCollection: () => Promise<string>;
  onRefreshCardData: () => Promise<string>;
  onImport: () => void;
  onExport: () => void;
  onDuplicate: () => Promise<void>;
  onDelete: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
        setConfirmingDelete(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  function toggle() {
    setOpen((prev) => !prev);
    setConfirmingDelete(false);
    setStatus(null);
  }

  async function handleAddToCollection() {
    setBusy(true);
    try {
      setStatus(await onAddToCollection());
    } finally {
      setBusy(false);
    }
  }

  async function handleRefreshCardData() {
    setBusy(true);
    try {
      setStatus(await onRefreshCardData());
    } finally {
      setBusy(false);
    }
  }

  async function handleDuplicate() {
    setBusy(true);
    try {
      await onDuplicate();
    } finally {
      setBusy(false);
      setOpen(false);
    }
  }

  async function handleConfirmDelete() {
    setBusy(true);
    try {
      await onDelete();
    } finally {
      setBusy(false);
    }
  }

  function handleImport() {
    setOpen(false);
    onImport();
  }

  function handleExport() {
    setOpen(false);
    onExport();
  }

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button onClick={toggle} aria-label="Deck menu" title="Deck menu" className="btn" style={{ ...buttonStyle, padding: "4px 10px" }}>
        &#8942;
      </button>
      {open && (
        <div
          style={{
            position: "absolute",
            top: "100%",
            right: 0,
            marginTop: 4,
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 6,
            minWidth: 220,
            padding: 6,
            zIndex: 20,
            display: "flex",
            flexDirection: "column",
            gap: 2,
          }}
        >
          {confirmingDelete ? (
            <>
              <div style={{ fontSize: 13, padding: "6px 8px" }}>Delete this deck? This can't be undone.</div>
              <button
                onClick={handleConfirmDelete}
                disabled={busy}
                className="menu-item menu-item-danger"
                style={menuItemStyle}
              >
                {busy ? "Deleting…" : "Confirm delete"}
              </button>
              <button onClick={() => setConfirmingDelete(false)} className="menu-item" style={menuItemStyle}>
                Cancel
              </button>
            </>
          ) : (
            <>
              <button onClick={handleAddToCollection} disabled={busy} className="menu-item" style={menuItemStyle}>
                Add whole deck to collection
              </button>
              <button onClick={handleRefreshCardData} disabled={busy} className="menu-item" style={menuItemStyle}>
                Refresh card data
              </button>
              <button onClick={handleImport} disabled={busy} className="menu-item" style={menuItemStyle}>
                Import cards
              </button>
              <button onClick={handleExport} disabled={busy} className="menu-item" style={menuItemStyle}>
                Export decklist
              </button>
              <button onClick={handleDuplicate} disabled={busy} className="menu-item" style={menuItemStyle}>
                {busy ? "Duplicating…" : "Duplicate deck"}
              </button>
              <button
                onClick={() => setConfirmingDelete(true)}
                className="menu-item menu-item-danger"
                style={menuItemStyle}
              >
                Delete deck
              </button>
              {status && <div style={{ fontSize: 12, color: "var(--text-muted)", padding: "4px 8px" }}>{status}</div>}
            </>
          )}
        </div>
      )}
    </div>
  );
}
