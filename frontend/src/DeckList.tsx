import { useEffect, useState } from "react";
import CardImage from "./CardImage";
import type { DeckGroup, DeckRow, ViewMode } from "./deckListModel";
import ManaCost from "./ManaCost";
import type { SelectedPrinting } from "./printings";

export type ListOptions = { showPrices: boolean; showMana: boolean };

type Props = {
  groups: DeckGroup[];
  view: ViewMode;
  options: ListOptions;
  printings: Record<string, SelectedPrinting>;
  owned: Set<string>;
  onHover: (name: string) => void;
  onOpen: (name: string) => void;
  onAddOne: (name: string) => Promise<void>;
  onRemoveOne: (name: string) => Promise<void>;
};

type Folding = { collapsed: Set<string>; toggle: (key: string) => void };

function GroupHead({ group, collapsed, onToggle }: { group: DeckGroup; collapsed: boolean; onToggle: () => void }) {
  return (
    <li className="dv-cat-head" role="button" tabIndex={0} aria-expanded={!collapsed} onClick={onToggle} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onToggle()}>
      {group.icon && <i className={`ms ms-${group.icon}`} aria-hidden />}
      <span>{group.label}</span>
      <span className="dv-total">({group.total})</span>
      <span className="dv-caret" aria-hidden>
        ▼
      </span>
    </li>
  );
}

// The text views: a column-flowed list of groups, a line to a card.
function TextList({ groups, view, options, owned, onHover, onOpen, onAddOne, onRemoveOne, collapsed, toggle }: Props & Folding) {
  const [menuFor, setMenuFor] = useState<string | null>(null);
  useEffect(() => {
    if (menuFor === null) return;
    const close = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (!target.closest(".dv-menu") && !target.closest(".dv-act")) setMenuFor(null);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [menuFor]);

  const choose = (name: string, action: (name: string) => unknown) => () => {
    setMenuFor(null);
    void action(name);
  };

  const row = (r: DeckRow) => (
    <li key={r.name} className="dv-row" data-static={r.isCommander} onMouseEnter={() => onHover(r.name)} onClick={() => !r.isCommander && onOpen(r.name)}>
      <span className="dv-qty">{r.count}</span>
      <span className={`dv-name${r.info ? "" : " dv-unknown"}`}>{r.name}</span>
      {owned.has(r.name) && (
        <span className="dv-owned" title="In your collection">
          ✓
        </span>
      )}
      {options.showMana && <ManaCost cost={r.info?.manaCost} />}
      {options.showPrices && <span className="dv-price">{r.price !== null ? `$${(r.price * r.count).toFixed(2)}` : ""}</span>}
      {r.isCommander ? (
        <span className="dv-act-space" aria-hidden />
      ) : (
        <button
          className="dv-act"
          aria-label={`Actions for ${r.name}`}
          aria-expanded={menuFor === r.name}
          onClick={(e) => {
            e.stopPropagation();
            setMenuFor((prev) => (prev === r.name ? null : r.name));
          }}
        >
          ▼
        </button>
      )}
      {menuFor === r.name && (
        <div className="dv-menu" onClick={(e) => e.stopPropagation()}>
          <button onClick={choose(r.name, onOpen)}>Details</button>
          <button onClick={choose(r.name, onAddOne)}>Add one</button>
          <button className="dv-danger" onClick={choose(r.name, onRemoveOne)}>
            Remove one
          </button>
        </div>
      )}
    </li>
  );

  return (
    <div className={`dv-cols${view === "condensed" ? " dv-condensed" : ""}`}>
      {groups.map((g) => (
        <ul key={g.key} className="dv-cat" data-collapsed={collapsed.has(g.key)}>
          <GroupHead group={g} collapsed={collapsed.has(g.key)} onToggle={() => toggle(g.key)} />
          {!collapsed.has(g.key) && g.rows.map(row)}
        </ul>
      ))}
    </div>
  );
}

function Art({ row, printings }: { row: DeckRow; printings: Record<string, SelectedPrinting> }) {
  return <CardImage cardId={row.info?.id} printing={printings[row.name]} version="normal" alt={row.name} title={row.name} loading="lazy" />;
}

const noBullets = { margin: 0, padding: 0, listStyle: "none" } as const;

// Visual Grid: the cards themselves, a group at a time.
function Grid({ groups, printings, onHover, onOpen, collapsed, toggle }: Props & Folding) {
  return (
    <div>
      {groups.map((g) => (
        <div key={g.key} className="dv-visual-group">
          <ul style={noBullets}>
            <GroupHead group={g} collapsed={collapsed.has(g.key)} onToggle={() => toggle(g.key)} />
          </ul>
          {!collapsed.has(g.key) && (
            <div className="dv-grid">
              {g.rows.map((r) => (
                <div key={r.name} className="dv-tile" data-static={r.isCommander} onMouseEnter={() => onHover(r.name)} onClick={() => !r.isCommander && onOpen(r.name)}>
                  <Art row={r} printings={printings} />
                  {r.count > 1 && <span className="dv-qty-badge">×{r.count}</span>}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// Visual Stacks: a column per group, the cards overlapped so only each title shows until you point at one.
function Stacks({ groups, printings, onHover, onOpen, collapsed, toggle }: Props & Folding) {
  return (
    <div className="dv-stacks">
      {groups.map((g) => (
        <div key={g.key} className="dv-stack">
          <ul style={{ ...noBullets, marginBottom: 10 }}>
            <GroupHead group={g} collapsed={collapsed.has(g.key)} onToggle={() => toggle(g.key)} />
          </ul>
          {!collapsed.has(g.key) &&
            g.rows.map((r) => (
              <div key={r.name} className="dv-stack-card" data-static={r.isCommander} onMouseEnter={() => onHover(r.name)} onClick={() => !r.isCommander && onOpen(r.name)}>
                <Art row={r} printings={printings} />
                {r.count > 1 && <span className="dv-qty-badge">×{r.count}</span>}
              </div>
            ))}
        </div>
      ))}
    </div>
  );
}

export default function DeckList(props: Props) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const toggle = (key: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (!next.delete(key)) next.add(key);
      return next;
    });
  if (props.groups.length === 0) return null;
  if (props.view === "grid") return <Grid {...props} collapsed={collapsed} toggle={toggle} />;
  if (props.view === "stacks") return <Stacks {...props} collapsed={collapsed} toggle={toggle} />;
  return <TextList {...props} collapsed={collapsed} toggle={toggle} />;
}
