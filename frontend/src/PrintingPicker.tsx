import { useEffect, useMemo, useState } from "react";
import { getPrintings, scryfallImageUrlById, type Printing } from "./api";
import { matchesPrinting, selectPrinting, type SelectedPrinting } from "./printings";
import { buttonStyle, inputStyle } from "./styles";

const mutedStyle = { fontSize: 13, color: "var(--text-muted)" };

export default function PrintingPicker({
  name,
  foil = false,
  onSelect,
  onClose,
}: {
  name: string;
  // Whether the card is used as a foil now: it stays one on a printing that has a foil.
  foil?: boolean;
  onSelect: (printing: SelectedPrinting) => void;
  onClose: () => void;
}) {
  // undefined while loading, null if the lookup failed, [] if there are none.
  const [printings, setPrintings] = useState<Printing[] | null | undefined>(undefined);
  const [query, setQuery] = useState("");

  useEffect(() => {
    let cancelled = false;
    setPrintings(undefined);
    getPrintings(name).then((result) => {
      if (!cancelled) setPrintings(result);
    });
    return () => {
      cancelled = true;
    };
  }, [name]);

  // Escape closes the picker and leaves the card open behind it. The card
  // closes on Escape too, so this listens first (capture phase) and stops it there.
  useEffect(() => {
    function handleEscape(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      onClose();
    }
    window.addEventListener("keydown", handleEscape, true);
    return () => window.removeEventListener("keydown", handleEscape, true);
  }, [onClose]);

  const shown = useMemo(() => printings?.filter((p) => matchesPrinting(p, query)), [printings, query]);
  const searching = query.trim() !== "";

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
        zIndex: 110,
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Change printing of ${name}`}
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: 10,
          width: "100%",
          maxWidth: 640,
          maxHeight: "85vh",
          display: "flex",
          flexDirection: "column",
          padding: 20,
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            gap: 12,
            marginBottom: 14,
          }}
        >
          <div style={{ fontSize: 18, fontWeight: 600 }}>Change printing</div>
          <button
            onClick={onClose}
            aria-label="Close"
            title="Close"
            className="btn"
            style={{ ...buttonStyle, padding: "4px 10px" }}
          >
            &times;
          </button>
        </div>

        {printings && printings.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by set, code, year, #number, or look (borderless, foil…)"
              aria-label="Search printings"
              autoComplete="off"
              autoFocus
              style={{ ...inputStyle, width: "100%", boxSizing: "border-box", fontSize: 14, padding: "8px 12px" }}
            />
            <div style={{ ...mutedStyle, fontSize: 12, marginTop: 6 }} aria-live="polite">
              {searching
                ? `${shown?.length ?? 0} of ${printings.length} printings`
                : `${printings.length} ${printings.length === 1 ? "printing" : "printings"}, newest first`}
            </div>
          </div>
        )}

        <div style={{ overflow: "auto", display: "flex", flexDirection: "column", gap: 8 }}>
          {printings === undefined && <div style={mutedStyle}>Loading printings…</div>}
          {printings === null && (
            <div style={mutedStyle}>Couldn't load printings right now — close this and try again in a moment.</div>
          )}
          {printings?.length === 0 && <div style={mutedStyle}>No printings found.</div>}
          {printings && printings.length > 0 && shown?.length === 0 && (
            <div style={mutedStyle}>
              No printing matches “{query.trim()}”.{" "}
              <button
                onClick={() => setQuery("")}
                style={{ all: "unset", cursor: "pointer", color: "var(--accent)", textDecoration: "underline" }}
              >
                Clear the search
              </button>
            </div>
          )}
          {shown?.map((p) => (
            <button
              key={p.id}
              onClick={() => onSelect(selectPrinting(p, foil))}
              className="btn"
              style={{
                ...buttonStyle,
                display: "flex",
                alignItems: "center",
                gap: 12,
                textAlign: "left",
                padding: 8,
              }}
            >
              <img
                src={scryfallImageUrlById(p.id, "normal")}
                alt={p.setName}
                loading="lazy"
                style={{
                  width: 90,
                  height: 125,
                  objectFit: "cover",
                  borderRadius: 6,
                  flexShrink: 0,
                  border: "1px solid var(--border)",
                }}
              />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600, fontSize: 14 }}>{p.setName}</div>
                <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                  {[
                    p.releasedAt ? p.releasedAt.slice(0, 4) : "Unknown year",
                    p.set && `${p.set.toUpperCase()}${p.collectorNumber ? ` #${p.collectorNumber}` : ""}`,
                    p.priceUsd && `$${p.priceUsd}`,
                    p.priceUsdFoil && `$${p.priceUsdFoil} foil`,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </div>
                {p.treatments.length > 0 && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 6 }}>
                    {p.treatments.map((t) => (
                      <span
                        key={t}
                        style={{ fontSize: 11, background: "var(--user-bubble)", borderRadius: 999, padding: "1px 8px" }}
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
