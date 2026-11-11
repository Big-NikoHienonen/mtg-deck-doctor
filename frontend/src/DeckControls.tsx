import { useState, type ReactNode } from "react";
import type { ListOptions } from "./DeckList";
import { GROUP_LABELS, SORT_LABELS, VIEW_LABELS, type GroupBy, type SortBy, type ViewMode } from "./deckListModel";

export type ListSettings = ListOptions & { view: ViewMode; groupBy: GroupBy; sortBy: SortBy };

function Select<T extends string>({ label, value, labels, onChange }: { label: string; value: T; labels: Record<T, string>; onChange: (value: T) => void }) {
  return (
    <label className="dv-field">
      {label}
      <select className="dv-select" value={value} onChange={(e) => onChange(e.target.value as T)}>
        {(Object.keys(labels) as T[]).map((key) => (
          <option key={key} value={key}>
            {labels[key]}
          </option>
        ))}
      </select>
    </label>
  );
}

// Above the list: a way to add a card, and how the list is shown — view, group, sort, and a few extras.
export default function DeckControls({ settings, onChange, add }: { settings: ListSettings; onChange: (next: ListSettings) => void; add?: ReactNode }) {
  const [advanced, setAdvanced] = useState(false);
  const set = <K extends keyof ListSettings>(key: K, value: ListSettings[K]) => onChange({ ...settings, [key]: value });
  return (
    <>
      <div className="dv-controls">
        <div className="dv-add">{add}</div>
        <Select label="View" value={settings.view} labels={VIEW_LABELS} onChange={(v) => set("view", v)} />
        <Select label="Group" value={settings.groupBy} labels={GROUP_LABELS} onChange={(v) => set("groupBy", v)} />
        <Select label="Sort" value={settings.sortBy} labels={SORT_LABELS} onChange={(v) => set("sortBy", v)} />
        <button className="dv-action" aria-expanded={advanced} onClick={() => setAdvanced((v) => !v)}>
          Advanced
        </button>
      </div>
      {advanced && (
        <div className="dv-advanced">
          <label>
            <input type="checkbox" checked={settings.showMana} onChange={(e) => set("showMana", e.target.checked)} />
            Show mana costs
          </label>
          <label>
            <input type="checkbox" checked={settings.showPrices} onChange={(e) => set("showPrices", e.target.checked)} />
            Show prices
          </label>
        </div>
      )}
    </>
  );
}
