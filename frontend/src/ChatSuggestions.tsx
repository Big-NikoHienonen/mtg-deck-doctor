import { useState } from "react";
import type { Deck } from "./api";
import { BASIC_LAND_NAMES } from "./basicLands";
import type { Suggestion } from "./chatMessages";
import { buttonStyle } from "./styles";

const BUTTON = { add: "Add", remove: "Remove", commander: "Make commander" } as const;
const DONE = { add: "✓ Added", remove: "✓ Removed", commander: "✓ Commander" } as const;
// Removals go first, then the commander, then additions, the order the Doctor's proposals were checked in:
// a swap on a full deck only works that way round.
const ORDER = { remove: 0, commander: 1, add: 2 } as const;

const keyOf = (s: Suggestion) => `${s.action}:${s.name}`;

// What the Doctor proposed under one of its replies, a button to a change. The Doctor never changes the deck;
// each change happens here, through the same rules as editing by hand, and shows as done once the deck has it.
export default function ChatSuggestions({
  suggestions,
  deck,
  onApply,
}: {
  suggestions: Suggestion[];
  deck: Deck;
  onApply: (s: Suggestion) => Promise<void>;
}) {
  // What is being applied now: one suggestion's key, or "all".
  const [busy, setBusy] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  // Basic lands can be added again and again, so the deck can't say whether this one was: this does.
  const [applied, setApplied] = useState<Set<string>>(new Set());

  function isDone(s: Suggestion): boolean {
    if (s.action === "add") return BASIC_LAND_NAMES.has(s.name) ? applied.has(keyOf(s)) : deck.cards.includes(s.name) || deck.commander === s.name;
    if (s.action === "remove") return !deck.cards.includes(s.name);
    return deck.commander === s.name;
  }

  async function apply(s: Suggestion): Promise<boolean> {
    setErrors((prev) => ({ ...prev, [keyOf(s)]: "" }));
    try {
      await onApply(s);
      setApplied((prev) => new Set(prev).add(keyOf(s)));
      return true;
    } catch (err) {
      setErrors((prev) => ({ ...prev, [keyOf(s)]: err instanceof Error ? err.message : "That didn't work." }));
      return false;
    }
  }

  async function applyOne(s: Suggestion) {
    setBusy(keyOf(s));
    await apply(s);
    setBusy(null);
  }

  // One at a time, each finished before the next starts (the backend has no per-deck locking), and stopping
  // at the first that is refused so the reason is the last thing shown.
  async function applyAll(pending: Suggestion[]) {
    setBusy("all");
    for (const s of [...pending].sort((a, b) => ORDER[a.action] - ORDER[b.action])) {
      if (!(await apply(s))) break;
    }
    setBusy(null);
  }

  const pending = suggestions.filter((s) => !isDone(s));
  return (
    <div style={{ alignSelf: "flex-start", width: "85%", display: "flex", flexDirection: "column", gap: 6 }}>
      {suggestions.map((s) => {
        const done = isDone(s);
        const error = errors[keyOf(s)];
        return (
          <div
            key={keyOf(s)}
            style={{
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: 4,
              padding: "8px 12px",
              display: "flex",
              alignItems: "center",
              gap: 12,
              opacity: done ? 0.65 : 1,
            }}
          >
            <div style={{ flex: 1, minWidth: 0, fontSize: 14, lineHeight: 1.4 }}>
              <strong>{s.name}</strong>
              {s.why && <div style={{ color: "var(--text-muted)", fontSize: 13 }}>{s.why}</div>}
              {error && <div style={{ color: "var(--danger)", fontSize: 13 }}>{error}</div>}
            </div>
            {done ? (
              <span style={{ fontSize: 13, color: "var(--text-muted)", whiteSpace: "nowrap" }}>{DONE[s.action]}</span>
            ) : (
              <button
                type="button"
                className={`btn${s.action === "remove" ? " btn-danger" : ""}`}
                style={{ ...buttonStyle, fontSize: 13, padding: "4px 12px", whiteSpace: "nowrap" }}
                disabled={busy !== null}
                onClick={() => applyOne(s)}
              >
                {busy === keyOf(s) ? "…" : BUTTON[s.action]}
              </button>
            )}
          </div>
        );
      })}
      {pending.length > 1 && (
        <button
          type="button"
          className="btn"
          style={{ ...buttonStyle, fontSize: 13, padding: "4px 12px", alignSelf: "flex-start" }}
          disabled={busy !== null}
          onClick={() => applyAll(pending)}
        >
          {busy === "all" ? "Applying…" : `Apply all ${pending.length}`}
        </button>
      )}
    </div>
  );
}
