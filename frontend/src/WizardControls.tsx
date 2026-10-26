import { useEffect, useState } from "react";
import { scryfallManaSymbolUrl } from "./api";
import { inputStyle } from "./styles";
import {
  COLOR_INFO,
  COLOR_LETTERS,
  SPEND_AREAS,
  colorComboName,
  colorWords,
  defaultCap,
  type SpendMode,
  type Style,
} from "./wizardData";

// The controls of the new-deck page. Each says what it is in a word or two and
// keeps the explaining for a tooltip, so the page stays short.

export function Segmented<T extends string | number | null>({
  options,
  value,
  onChange,
  label,
  small,
}: {
  options: { value: T; label: string; disabled?: boolean; title?: string }[];
  value: T;
  onChange: (value: T) => void;
  label: string;
  small?: boolean;
}) {
  return (
    <div className={small ? "seg seg-sm" : "seg"} role="group" aria-label={label}>
      {options.map((o) => (
        <button key={String(o.value)} type="button" aria-pressed={o.value === value} disabled={o.disabled} title={o.title} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Switch({ on, onChange, label, hint }: { on: boolean; onChange: (on: boolean) => void; label: string; hint: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} className="switch" onClick={() => onChange(!on)}>
      <span className="switch-track" />
      <span>
        <span style={{ fontSize: 14, fontWeight: 600 }}>{label}</span>
        <span className="wiz-hint" style={{ display: "block" }}>
          {hint}
        </span>
      </span>
    </button>
  );
}

export function ColorPicker({
  letters,
  colorless,
  onToggle,
  onColorless,
}: {
  letters: string[];
  colorless: boolean;
  onToggle: (letter: string) => void;
  onColorless: () => void;
}) {
  const any = colorless || letters.length > 0;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
        {COLOR_LETTERS.map((c) => (
          <button key={c} type="button" className="mana" aria-pressed={letters.includes(c)} aria-label={COLOR_INFO[c].name} title={`${COLOR_INFO[c].name} — ${COLOR_INFO[c].blurb}`} onClick={() => onToggle(c)}>
            <img src={scryfallManaSymbolUrl(c)} alt="" />
          </button>
        ))}
        <button type="button" className="mana mana-c" aria-pressed={colorless} aria-label="Colorless" title="Colorless — no colors at all" onClick={onColorless}>
          C
        </button>
      </div>
      <div style={{ fontSize: 14, minWidth: 0 }}>
        {any ? (
          <>
            <strong>{colorless ? "Colorless" : colorComboName(letters)}</strong>
            <span style={{ color: "var(--text-muted)" }}> · {colorless ? "no colors" : colorWords(letters)}</span>
          </>
        ) : (
          <span style={{ color: "var(--text-muted)" }}>Any colors</span>
        )}
      </div>
    </div>
  );
}

export function StyleChips({
  strategies,
  creatureTypes,
  theme,
  counts,
  onChange,
}: {
  strategies: Style[];
  creatureTypes: Style[];
  theme: string | null;
  counts: Record<string, number | null> | null;
  onChange: (theme: string | null) => void;
}) {
  const chip = (s: Style) => {
    const n = counts?.[s.slug];
    const unavailable = counts !== null && n === 0;
    return (
      <button
        key={s.slug}
        type="button"
        className="chip"
        aria-pressed={theme === s.slug}
        disabled={unavailable}
        title={unavailable ? `No ${s.label.toLowerCase()} commanders in these colors` : s.blurb}
        onClick={() => onChange(theme === s.slug ? null : s.slug)}
      >
        {s.label}
        {n ? <small>{n}</small> : null}
      </button>
    );
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>{strategies.map(chip)}</div>
      <details className="wiz-details" open={creatureTypes.some((t) => t.slug === theme)}>
        <summary>Or build around a creature type</summary>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 10 }}>{creatureTypes.map(chip)}</div>
      </details>
    </div>
  );
}

// A dollar amount that is only committed when the player leaves the field or
// presses Enter, so typing "35" doesn't rebuild anything for "3" first.
function CapInput({ value, onCommit }: { value: number; onCommit: (n: number) => void }) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => setDraft(String(value)), [value]);
  function commit() {
    const n = Math.round(Number(draft));
    if (Number.isFinite(n) && n >= 0 && n <= 10000) onCommit(n);
    else setDraft(String(value));
  }
  return (
    <label style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13 }}>
      at most $
      <input
        inputMode="numeric"
        value={draft}
        onChange={(e) => setDraft(e.target.value.replace(/[^0-9]/g, ""))}
        onBlur={commit}
        onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
        aria-label="Spending limit in dollars"
        style={{ ...inputStyle, flexGrow: 0, width: 70, padding: "4px 8px", fontSize: 14 }}
      />
    </label>
  );
}

// Where the money goes: for each part of the deck, keep it cheap (with a
// dollar limit), spend more there, or no preference.
export function SpendEditor({
  mode,
  caps,
  budgetCap,
  onMode,
  onCap,
}: {
  mode: Record<string, SpendMode>;
  caps: Record<string, number>;
  budgetCap: number | null;
  onMode: (slug: string, mode: SpendMode) => void;
  onCap: (slug: string, cap: number) => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 12 }}>
      {SPEND_AREAS.map((a) => {
        const m = mode[a.slug] ?? "normal";
        return (
          <div key={a.slug} style={{ display: "flex", alignItems: "center", gap: "6px 12px", flexWrap: "wrap" }}>
            <div style={{ width: 96, fontSize: 14, fontWeight: 600 }} title={a.blurb}>
              {a.label}
            </div>
            <Segmented<SpendMode>
              small
              label={`How to spend on ${a.label.toLowerCase()}`}
              value={m}
              onChange={(next) => onMode(a.slug, next)}
              options={[
                { value: "cheap", label: "Keep cheap" },
                { value: "normal", label: "No preference" },
                { value: "invest", label: "Spend more", disabled: budgetCap === null, title: budgetCap === null ? "Pick a budget first" : undefined },
              ]}
            />
            {m === "cheap" && <CapInput value={caps[a.slug] ?? defaultCap(a.slug, budgetCap)} onCommit={(n) => onCap(a.slug, n)} />}
          </div>
        );
      })}
    </div>
  );
}
