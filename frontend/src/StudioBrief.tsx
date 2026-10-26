import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Spending } from "./api";
import CardSearchBox from "./CardSearchBox";
import { BRACKETS, BUDGETS, CREATURE_TYPES, STRATEGIES, colorComboName, type SpendMode } from "./wizardData";
import { ColorPicker, Segmented, SpendEditor, StyleChips, Switch } from "./WizardControls";

const EXAMPLES = ["a cheap zombie deck, just for fun", "lots of death triggers, nothing that destroys lands", "something my friends have never seen"];

// Grows a textarea with what's typed in it, up to a limit.
function useAutosize(value: string) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);
  return ref;
}

export type BriefProps = {
  ask: string;
  onAsk: (text: string) => void;
  letters: string[];
  colorless: boolean;
  onToggleColor: (letter: string) => void;
  onColorless: () => void;
  onClearColors: () => void;
  theme: string | null;
  onTheme: (theme: string | null) => void;
  themeCounts: Record<string, number | null> | null;
  lesserKnown: boolean;
  onLesserKnown: (on: boolean) => void;
  bracket: number | null;
  onBracket: (bracket: number | null) => void;
  budget: number | "none" | null;
  onBudget: (budget: number | "none" | null) => void;
  budgetCap: number | null;
  spendMode: Record<string, SpendMode>;
  spending: Spending;
  onSpendMode: (slug: string, mode: SpendMode) => void;
  onCap: (slug: string, cap: number) => void;
  chosen: string | null;
  onChooseCommander: (name: string) => void;
  onClearCommander: () => void;
  onBrowse: () => void;
  locked: boolean;
  starting: boolean;
  notice: ReactNode;
  onStart: () => void;
  onStarter: () => void;
  onEmpty: () => void;
};

type Panel = "commander" | "colors" | "style" | "power" | "budget" | null;

// Step one: say what you want, and set whatever you already know. Everything is optional;
// what's left open, the Doctor decides.
export default function BriefCard(p: BriefProps) {
  const [open, setOpen] = useState<Panel>(null);
  const ref = useAutosize(p.ask);
  const hasColors = p.colorless || p.letters.length > 0;
  const style = [...STRATEGIES, ...CREATURE_TYPES].find((s) => s.slug === p.theme);
  const level = p.bracket === null ? null : BRACKETS.find((b) => b.n === p.bracket)!;
  const anything = p.ask.trim().length > 0 || p.chosen !== null || hasColors || p.theme !== null || p.bracket !== null || p.budget !== null;

  const toggle = (panel: Exclude<Panel, null>) => setOpen((o) => (o === panel ? null : panel));
  const pref = (panel: Exclude<Panel, null>, label: string, value: string | null) => (
    <button key={panel} type="button" className="pref" aria-expanded={open === panel} data-set={value !== null} onClick={() => toggle(panel)}>
      {value ?? label}
    </button>
  );

  return (
    <div className="stagger" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div className="brief-card">
        <textarea
          ref={ref}
          value={p.ask}
          onChange={(e) => p.onAsk(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !p.locked && anything) {
              e.preventDefault();
              p.onStart();
            }
          }}
          rows={3}
          maxLength={1000}
          placeholder="What deck do you want to build? Say it however you like."
          aria-label="What deck do you want to build?"
        />
        {!p.ask && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
            {EXAMPLES.map((e) => (
              <button key={e} type="button" className="chip" style={{ fontSize: 12, padding: "3px 10px" }} onClick={() => p.onAsk(e)}>
                {e}
              </button>
            ))}
          </div>
        )}

        <div className="picks-row">
          <span className="station-note" style={{ marginRight: 2 }}>
            Already know?
          </span>
          {pref("commander", "Commander", p.chosen ? p.chosen.split(",")[0] : null)}
          {!p.chosen && pref("colors", "Colors", hasColors ? (p.colorless ? "Colorless" : colorComboName(p.letters)) : null)}
          {!p.chosen && pref("style", "Style", style ? style.label : null)}
          {pref("power", "Power level", level ? level.label : null)}
          {pref("budget", "Budget", p.budget === null ? null : p.budget === "none" ? "No limit" : `Up to $${p.budget}`)}
        </div>

        {open === "commander" && (
          <div className="inline-panel">
            {p.chosen ? (
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
                <div>
                  <div style={{ fontSize: 18, fontWeight: 600 }}>{p.chosen}</div>
                  <div className="station-note">Its colors are the deck's colors.</div>
                </div>
                <button className="ghost" onClick={p.onClearCommander}>
                  Change
                </button>
              </div>
            ) : (
              <>
                <CardSearchBox placeholder="Search for a commander…" submitLabel="Use this one" onSubmit={async (name) => { p.onChooseCommander(name); setOpen(null); }} />
                <div style={{ marginTop: 10 }}>
                  <button type="button" className="text-link" disabled={!hasColors} onClick={p.onBrowse}>
                    Browse commanders that fit
                  </button>
                  {!hasColors && <span className="station-note"> — pick colors first</span>}
                </div>
              </>
            )}
          </div>
        )}
        {open === "colors" && (
          <div className="inline-panel">
            <ColorPicker letters={p.letters} colorless={p.colorless} onToggle={p.onToggleColor} onColorless={p.onColorless} />
            {hasColors && (
              <div style={{ marginTop: 10 }}>
                <button type="button" className="text-link" onClick={p.onClearColors}>
                  Clear
                </button>
              </div>
            )}
          </div>
        )}
        {open === "style" && (
          <div className="inline-panel">
            <StyleChips strategies={STRATEGIES} creatureTypes={CREATURE_TYPES} theme={p.theme} counts={p.themeCounts} onChange={p.onTheme} />
            <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
              <Switch on={p.lesserKnown} onChange={p.onLesserKnown} label="Lesser-known commanders" hint="Skip the 5 most-built in these colors." />
            </div>
          </div>
        )}
        {open === "power" && (
          <div className="inline-panel">
            <Segmented<number | null>
              label="Power level"
              value={p.bracket}
              onChange={p.onBracket}
              options={[{ value: null, label: "No preference" }, ...BRACKETS.map((b) => ({ value: b.n as number | null, label: b.label, title: b.blurb }))]}
            />
            <div className="station-note" style={{ marginTop: 10 }}>
              {level ? level.blurb : "The Doctor decides, and uses Core when it has nothing to go on."}
            </div>
          </div>
        )}
        {open === "budget" && (
          <div className="inline-panel">
            <Segmented<number | "none" | null> label="Budget" value={p.budget} onChange={p.onBudget} options={BUDGETS.map((b) => ({ value: b.cap, label: b.label.replace("Up to ", "") }))} />
            <div className="station-note" style={{ marginTop: 8 }}>For the whole deck, commander included.</div>
            <details className="wiz-details" style={{ marginTop: 12 }}>
              <summary>Where should the money go?</summary>
              <div className="station-note" style={{ marginTop: 8 }}>
                Cap what you'd rather not pay for, like lands, and the money it frees goes to the rest of the deck. "Spend more" needs a budget.
              </div>
              <SpendEditor mode={p.spendMode} caps={p.spending.caps} budgetCap={p.budgetCap} onMode={p.onSpendMode} onCap={p.onCap} />
            </details>
          </div>
        )}

        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 14, flexWrap: "wrap", marginTop: 14 }}>
          <span className="station-note">Everything is optional. What you leave open, the Doctor decides.</span>
          <button className="go" disabled={p.locked || !anything} onClick={p.onStart}>
            {p.starting ? "Starting…" : "Start building →"}
          </button>
        </div>
      </div>

      {p.notice}

      <div className="station-note">
        Prefer to skip the AI?{" "}
        <button type="button" className="text-link" disabled={!p.chosen || p.starting} onClick={p.onStarter} title={p.chosen ? undefined : "Choose a commander first"}>
          Get a plain starting list
        </button>{" "}
        for the commander you chose, or{" "}
        <button type="button" className="text-link" onClick={p.onEmpty}>
          start with an empty deck
        </button>
        .
      </div>
    </div>
  );
}
