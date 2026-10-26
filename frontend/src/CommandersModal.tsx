import { useEffect } from "react";
import type { WizardCandidates } from "./api";
import CommanderCard from "./CommanderCard";
import { buttonStyle } from "./styles";
import type { Style } from "./wizardData";

const pulse = { animation: "pulse 1.6s ease-in-out infinite" };

// The commanders that fit the answers so far, to pick one from yourself instead of
// leaving it to the Doctor. Over the page, so the form stays short.
export default function CommandersModal({
  heading,
  lesserKnown,
  candidates,
  level,
  themeStyle,
  reasons,
  explaining,
  explainError,
  onExplain,
  onChoose,
  onClose,
}: {
  heading: string;
  lesserKnown: boolean;
  candidates: WizardCandidates | null;
  level: number;
  themeStyle: Style | null;
  reasons: Record<string, string> | null;
  explaining: boolean;
  explainError: string | null;
  onExplain: () => void;
  onChoose: (name: string) => void;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [onClose]);

  const found = candidates && !candidates.unavailable ? candidates.commanders : [];
  const note = { fontSize: 14, color: "var(--accent-gold)", marginBottom: 12 } as const;
  return (
    <div
      onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(20, 14, 8, 0.6)", display: "flex", alignItems: "flex-start", justifyContent: "center", padding: "4vh 16px", zIndex: 100, overflowY: "auto" }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Commanders that fit"
        onClick={(e) => e.stopPropagation()}
        style={{ background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 16, width: "100%", maxWidth: 860, padding: "22px 24px 28px" }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, marginBottom: 16 }}>
          <div>
            <h2 style={{ fontSize: 24, fontWeight: 600, margin: 0 }}>Commanders that fit</h2>
            <div className="wiz-hint" style={{ fontSize: 14, marginTop: 2 }}>
              {heading} — {lesserKnown ? "from the well known to the obscure." : "most-built first."}
            </div>
          </div>
          <button onClick={onClose} aria-label="Close" className="btn" style={{ ...buttonStyle, padding: "4px 12px", fontSize: 18 }}>
            &times;
          </button>
        </div>

        {candidates?.niche_fallback && <div style={note}>There aren't enough lesser-known commanders for these answers, so here are the most-built ones instead.</div>}
        {candidates?.fell_back_from && (
          <div style={note}>There's no commander we can offer for {candidates.fell_back_from.replace(/-/g, " ")} in these colors, so here are the most-built ones instead.</div>
        )}
        {found.length > 0 && candidates?.relaxed && <div style={note}>Few decks exist at this power level for these answers, so these are the closest matches.</div>}

        {found.length > 0 && !reasons && (
          <div style={{ marginBottom: 14 }}>
            <button onClick={onExplain} disabled={explaining} className="btn" style={buttonStyle}>
              {explaining ? "Explaining…" : "Have the Doctor explain why these fit"}
            </button>
            {explainError && <span style={{ fontSize: 14, color: "var(--danger)", marginLeft: 12 }}>{explainError}</span>}
          </div>
        )}

        {candidates === null && (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {[0, 1, 2].map((i) => (
              <div key={i} style={{ height: 180, border: "2px dashed var(--border)", borderRadius: 14, ...pulse }} />
            ))}
          </div>
        )}
        {candidates?.unavailable && <div style={{ fontSize: 15, color: "var(--danger)" }}>Couldn't reach EDHREC just now. Close this and open it again in a moment.</div>}
        {candidates && !candidates.unavailable && found.length === 0 && (
          <div style={{ fontSize: 15, color: "var(--text-muted)" }}>No commanders match those answers. Try another style, or no preference.</div>
        )}
        {found.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {found.map((c) => (
              <CommanderCard key={c.name} commander={c} bracket={level} theme={themeStyle} reason={reasons?.[c.name]} onChoose={() => onChoose(c.name)} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
