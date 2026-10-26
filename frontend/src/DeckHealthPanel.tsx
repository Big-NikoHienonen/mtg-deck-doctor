import { useState } from "react";
import type { DeckHealth, HealthMetric } from "./deckHealth";
import { eyebrowStyle } from "./styles";

const STATUS: Record<HealthMetric["status"], { label: string; color: string }> = {
  low: { label: "▼ below target", color: "var(--danger)" },
  ok: { label: "✓ on target", color: "var(--text-muted)" },
  high: { label: "▲ above target", color: "var(--accent-gold)" },
};

export default function DeckHealthPanel({ health }: { health: DeckHealth }) {
  const [expanded, setExpanded] = useState<HealthMetric["key"] | null>(null);
  const incomplete = health.coveredCards < health.totalCards;

  return (
    <section>
      <div style={eyebrowStyle}>HOW BALANCED IS THE DECK?</div>
      <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 8 }}>
        Estimated from card text against the standard Commander mix, so treat it as a guide, not a verdict.
        {incomplete && ` Based on ${health.coveredCards} of ${health.totalCards} cards so far — the rest are still loading.`}
      </div>
      <div style={{ display: "flex", flexDirection: "column" }}>
        {health.metrics.map((m) => {
          const status = STATUS[m.status];
          const open = expanded === m.key;
          return (
            <div key={m.key} style={{ borderBottom: "1px solid var(--border)", padding: "8px 0" }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
                <div style={{ flex: 1, fontSize: 14, fontWeight: 600 }}>{m.label}</div>
                <div style={{ fontSize: 14 }}>
                  {m.count}
                  <span style={{ color: "var(--text-muted)", fontSize: 12 }}>
                    {" "}
                    / {m.target[0]}–{m.target[1]}
                  </span>
                </div>
                <div style={{ fontSize: 12, color: status.color, minWidth: 110, textAlign: "right" }}>{status.label}</div>
                {m.key !== "lands" && (
                  <button
                    onClick={() => setExpanded(open ? null : m.key)}
                    className="menu-item"
                    style={{ width: "auto", fontSize: 12, padding: "2px 8px", cursor: "pointer", fontFamily: "inherit" }}
                  >
                    {open ? "Hide" : "Show"} cards
                  </button>
                )}
              </div>
              {open && (
                <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 6, lineHeight: 1.6 }}>
                  {m.cards.length > 0 ? m.cards.join(" · ") : "No cards matched."}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
