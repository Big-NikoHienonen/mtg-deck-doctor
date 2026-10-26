import type { WizardCommander } from "./api";
import CardImage from "./CardImage";
import { buttonStyle } from "./styles";
import { BRACKETS, type Style } from "./wizardData";

// How a commander's decks are spread across the power levels, as a bar with the
// chosen level marked, so "how many decks like mine exist" is visible at a glance.
function BracketBar({ counts, chosen }: { counts: Record<string, number>; chosen: number }) {
  const levels = ["1", "2", "3", "4", "5"];
  const total = levels.reduce((sum, l) => sum + (counts[l] ?? 0), 0) || 1;
  const names: Record<string, string> = { "1": "Exhibition", "2": "Core", "3": "Upgraded", "4": "Optimized", "5": "Competitive" };
  return (
    <div>
      <div style={{ display: "flex", height: 8, borderRadius: 4, overflow: "hidden", background: "var(--user-bubble)" }}>
        {levels.map((l) => (
          <div
            key={l}
            title={`${names[l]}: ${(counts[l] ?? 0).toLocaleString()} decks`}
            style={{
              width: `${((counts[l] ?? 0) / total) * 100}%`,
              background: String(chosen) === l ? "var(--accent)" : "var(--border)",
              borderRight: "1px solid var(--surface)",
            }}
          />
        ))}
      </div>
      <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 3 }}>Decks by power level — {names[String(chosen)]} highlighted</div>
    </div>
  );
}

export default function CommanderCard({
  commander,
  bracket,
  theme,
  reason,
  onChoose,
}: {
  commander: WizardCommander;
  bracket: number;
  theme: Style | null;
  // The Doctor's sentence on why it suits the answers, once asked for.
  reason?: string;
  onChoose: () => void;
}) {
  const level = BRACKETS.find((b) => b.n === bracket)!;
  return (
    <div
      style={{
        display: "flex",
        gap: 16,
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 14,
        padding: 16,
        boxShadow: "0 2px 10px rgba(43, 32, 24, 0.08)",
      }}
    >
      <CardImage
        cardId={commander.id}
        version="normal"
        alt={commander.name}
        loading="lazy"
        style={{ width: 150, flexShrink: 0, alignSelf: "flex-start", borderRadius: 10, boxShadow: "0 6px 16px rgba(43, 32, 24, 0.28)" }}
      />
      <div style={{ minWidth: 0, flex: 1, display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ fontSize: 20, fontWeight: 600, lineHeight: 1.25 }}>{commander.name}</div>
        <div style={{ fontSize: 14, lineHeight: 1.5 }}>
          <strong>{commander.num_decks.toLocaleString()}</strong> decks on EDHREC
          {commander.decks_at_bracket !== null && (
            <>
              , <strong>{commander.decks_at_bracket.toLocaleString()}</strong> at {level.label} power
            </>
          )}
          {theme && commander.themed_decks !== null && (
            <>
              <br />
              <strong>{commander.themed_decks.toLocaleString()}</strong> of them {theme.label.toLowerCase()} decks
            </>
          )}
        </div>
        {reason && (
          <div style={{ borderLeft: "4px solid var(--accent-gold)", paddingLeft: 12, fontSize: 14, lineHeight: 1.5 }}>
            <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.1em", color: "var(--accent-gold)", marginBottom: 2 }}>WHY IT FITS</div>
            {reason}
          </div>
        )}
        <BracketBar counts={commander.bracket_counts} chosen={bracket} />
        {commander.themes.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {commander.themes.slice(0, 4).map((t) => (
              <span key={t.slug} style={{ fontSize: 12, background: "var(--user-bubble)", borderRadius: 999, padding: "2px 10px" }}>
                {t.name}
              </span>
            ))}
          </div>
        )}
        {commander.signature.length > 0 && (
          <div style={{ fontSize: 13, color: "var(--text-muted)", lineHeight: 1.5 }}>Known for {commander.signature.join(", ")}.</div>
        )}
        <div style={{ marginTop: "auto" }}>
          <button onClick={onChoose} className="btn btn-positive" style={{ ...buttonStyle, fontWeight: 600 }}>
            Build around {commander.name.split(",")[0]}
          </button>
        </div>
      </div>
    </div>
  );
}
