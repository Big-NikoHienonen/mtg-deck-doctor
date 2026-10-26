import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import type { Build } from "./api";
import { money } from "./StudioBodies";

export type RailItem = { key: string; label: string; weight: number; state: "done" | "current" | "todo" };

// The bar across the top: where this is, how far along, and the deck so far.
export function StudioBar({
  title,
  rail,
  railLabel,
  build,
  onDeck,
  onNew,
}: {
  title: string;
  rail: RailItem[];
  railLabel: string;
  build: Build | null;
  onDeck: () => void;
  onNew: () => void;
}) {
  const count = build?.deck.count ?? 0;
  return (
    <div className="studio-bar">
      <div className="studio-title">
        <Link to="/">← All decks</Link>
        <strong>{title}</strong>
      </div>
      <div className="rail" aria-label="Progress">
        <div className="rail-segs">
          {rail.map((r) => (
            <div key={r.key} className="rail-seg" data-state={r.state} title={r.label} style={{ flexGrow: r.weight, flexBasis: 0 }} />
          ))}
        </div>
        <div className="rail-label">{railLabel}</div>
      </div>
      <div className="studio-stats">
        {build && (
          <>
            <span>
              <strong>{count}</strong>/99
            </span>
            <span>
              {money(build.deck.price)}
              {build.budget ? <span style={{ color: "var(--text-muted)" }}> of {money(build.budget)}</span> : null}
            </span>
            <button onClick={onDeck} disabled={count === 0}>
              The deck
            </button>
            <button onClick={onNew}>New brief</button>
          </>
        )}
      </div>
    </div>
  );
}

// The deck so far, from the bar.
export function DeckDrawer({ build, onClose }: { build: Build; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const phases = build.plan?.phases ?? [];
  return (
    <>
      <div className="drawer-back" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="The deck so far">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 12 }}>
          <div>
            <div className="kicker">THE DECK SO FAR</div>
            <div style={{ fontSize: 22, fontWeight: 600 }}>{build.commander?.name}</div>
            <div className="station-note">
              {build.deck.count} of 99 · {money(build.deck.price)}
              {build.budget ? ` of ${money(build.budget)}` : ""}
            </div>
          </div>
          <button className="ghost" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        {phases.map((p) => {
          const cards = build.deck.cards.filter((c) => c.phase === p.id);
          if (cards.length === 0) return null;
          return (
            <div key={p.id} style={{ marginBottom: 16 }}>
              <div className="kicker" style={{ marginBottom: 4 }}>
                {p.label.toUpperCase()} · {cards.reduce((n, c) => n + c.qty, 0)}
              </div>
              <div style={{ fontSize: 14, lineHeight: 1.75 }}>
                {cards.map((c) => (
                  <div key={c.name} style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                    <span>
                      {c.qty > 1 ? `${c.qty}× ` : ""}
                      {c.name}
                    </span>
                    <span style={{ color: "var(--text-muted)" }}>{c.price >= 1 ? money(c.price) : ""}</span>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </aside>
    </>
  );
}

const STEERS = ["Cheaper options", "Lower the curve", "More synergy with my commander", "Fewer expensive cards"];

// While a phase is open: ask the Doctor for something different, or lock the phase in.
export function SteerDock({
  phaseLabel,
  note,
  onNote,
  removed,
  kept,
  acting,
  onRedo,
  onLock,
}: {
  phaseLabel: string;
  note: string;
  onNote: (text: string) => void;
  removed: number;
  kept: number;
  acting: boolean;
  onRedo: () => void;
  onLock: () => void;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 140)}px`;
  }, [note]);
  const canRedo = !acting && (removed > 0 || note.trim().length > 0);
  return (
    <div className="dock-wrap">
      <div className="dock">
        <textarea
          ref={ref}
          rows={1}
          value={note}
          maxLength={400}
          onChange={(e) => onNote(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && canRedo) {
              e.preventDefault();
              onRedo();
            }
          }}
          placeholder={removed > 0 ? "Anything for the replacements? (optional)" : `Ask the Doctor for something different in the ${phaseLabel.toLowerCase()}…`}
          aria-label="Ask the Doctor for something different"
        />
        <div className="dock-bar">
          <div className="grow">
            {!note &&
              STEERS.map((s) => (
                <button key={s} type="button" className="chip" style={{ fontSize: 12, padding: "3px 10px" }} onClick={() => onNote(s)}>
                  {s}
                </button>
              ))}
          </div>
          <button className="ghost" disabled={!canRedo} onClick={onRedo}>
            {removed > 0 ? `Replace ${removed} I took out` : "Choose again"}
          </button>
          <button className="go" disabled={acting} onClick={onLock}>
            Lock in {kept} {kept === 1 ? "card" : "cards"} →
          </button>
        </div>
      </div>
    </div>
  );
}

const REFINES = ["Less well known", "Cheaper to build", "More aggressive", "Simpler to play"];

// While the commander is being chosen: tell the Doctor more, and have it look again. What is
// staged on the cards (commanders ruled out or liked, facts taken back) goes with the words.
export function RefineDock({
  text,
  onText,
  staged,
  round,
  acting,
  onLook,
}: {
  text: string;
  onText: (text: string) => void;
  // What is staged beside the words, in words: "ruling out 1 · more like 1".
  staged: string;
  // How many rounds there have been.
  round: number;
  acting: boolean;
  onLook: () => void;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 140)}px`;
  }, [text]);
  const canLook = !acting && (text.trim().length > 0 || staged.length > 0);
  return (
    <div className="dock-wrap">
      <div className="dock">
        <textarea
          ref={ref}
          rows={1}
          value={text}
          maxLength={600}
          onChange={(e) => onText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && canLook) {
              e.preventDefault();
              onLook();
            }
          }}
          placeholder={round <= 1 ? "Tell the Doctor more: a mechanic, a feel, something you don't want…" : "What's still off, or what do you want instead?"}
          aria-label="Tell the Doctor more about the commander you want"
        />
        <div className="dock-bar">
          <div className="grow">
            {!text &&
              !staged &&
              REFINES.map((s) => (
                <button key={s} type="button" className="chip" style={{ fontSize: 12, padding: "3px 10px" }} onClick={() => onText(s)}>
                  {s}
                </button>
              ))}
            {staged && <span className="station-note">{staged}</span>}
          </div>
          <button className="go" disabled={!canLook} onClick={onLook}>
            Look again →
          </button>
        </div>
      </div>
    </div>
  );
}

// The next thing to do, when there is just one: start the phases, make the deck.
export function ActionDock({ text, label, disabled, onClick }: { text: string; label: string; disabled: boolean; onClick: () => void }) {
  return (
    <div className="dock-wrap">
      <div className="dock dock-line">
        <span style={{ fontSize: 15 }}>{text}</span>
        <button className="go" disabled={disabled} onClick={onClick}>
          {label}
        </button>
      </div>
    </div>
  );
}
