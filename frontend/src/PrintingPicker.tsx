import { useEffect, useState } from "react";
import { getPrintings, scryfallImageUrlById, type Printing } from "./api";
import type { SelectedPrinting } from "./printings";
import { buttonStyle } from "./styles";

export default function PrintingPicker({
  name,
  onSelect,
  onClose,
}: {
  name: string;
  onSelect: (printing: SelectedPrinting) => void;
  onClose: () => void;
}) {
  // undefined while loading, null if the lookup failed, [] if there are none.
  const [printings, setPrintings] = useState<Printing[] | null | undefined>(undefined);

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

        <div style={{ overflow: "auto", display: "flex", flexDirection: "column", gap: 8 }}>
          {printings === undefined && (
            <div style={{ fontSize: 13, color: "var(--text-muted)" }}>Loading printings…</div>
          )}
          {printings === null && (
            <div style={{ fontSize: 13, color: "var(--text-muted)" }}>
              Couldn't load printings right now — close this and try again in a moment.
            </div>
          )}
          {printings?.length === 0 && (
            <div style={{ fontSize: 13, color: "var(--text-muted)" }}>No printings found.</div>
          )}
          {printings?.map((p) => (
            <button
              key={p.id}
              onClick={() => onSelect({ id: p.id, setName: p.setName, priceUsd: p.priceUsd })}
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
                  {p.releasedAt ? p.releasedAt.slice(0, 4) : "Unknown year"}
                  {p.priceUsd && ` · $${p.priceUsd}`}
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
