import { useEffect, useState, type ReactNode } from "react";

// The pieces the studio's timeline is made of.

export function Avatar({ busy }: { busy?: boolean }) {
  return (
    <span className="avatar" data-busy={busy ? "true" : "false"} aria-hidden>
      <svg viewBox="0 0 24 24" fill="currentColor">
        <path d="M9.5 3h5v6.5H21v5h-6.5V21h-5v-6.5H3v-5h6.5z" />
      </svg>
    </span>
  );
}

// Text that is typed out as it arrives — only when it is new this visit, never when a build
// is opened again. The room it will fill is held from the start, so nothing below jumps.
export function Typed({ text, animate }: { text: string; animate: boolean }) {
  const quiet = !animate || (typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
  const [shown, setShown] = useState(quiet ? text.length : 0);
  useEffect(() => {
    if (quiet) {
      setShown(text.length);
      return;
    }
    setShown(0);
    let n = 0;
    let timer: number;
    const tick = () => {
      n = Math.min(text.length, n + 3);
      setShown(n);
      if (n < text.length) timer = window.setTimeout(tick, 16);
    };
    timer = window.setTimeout(tick, 120);
    return () => window.clearTimeout(timer);
  }, [text, quiet]);
  return (
    <>
      {text.slice(0, shown)}
      <span style={{ visibility: "hidden" }}>{text.slice(shown)}</span>
    </>
  );
}

// The Doctor speaking, at the head of a station.
export function Says({ children, busy }: { children: ReactNode; busy?: boolean }) {
  return (
    <div className="says">
      <Avatar busy={busy} />
      <div className="says-text">{children}</div>
    </div>
  );
}

// What the Doctor has done so far and what it is doing now: the last line is the live one.
export function Thinking({ steps }: { steps: string[] }) {
  return (
    <Says busy>
      <div className="thinking" role="status">
        {steps.map((s, i) => (
          <div key={s + i} data-now={i === steps.length - 1}>
            {s}
            {i === steps.length - 1 && <span className="dots" aria-hidden />}
          </div>
        ))}
      </div>
    </Says>
  );
}

export function Group({ label }: { label: string }) {
  return <div className="group-label">{label}</div>;
}

// One stop on the way. Done: folded to a line (open it for the detail). Current: open, with
// everything it needs. Still to come: just its name and what it is for.
export function Station({
  id,
  state,
  node,
  kicker,
  title,
  note,
  children,
}: {
  id: string;
  state: "done" | "current" | "todo";
  node: ReactNode;
  kicker?: string;
  title: string;
  // Beside the title in every state: what it is for, or what came of it.
  note?: ReactNode;
  children?: ReactNode;
}) {
  const head = (
    <>
      {kicker && <span className="kicker">{kicker}</span>}
      <h2 className="station-title">{title}</h2>
      {note && <span className="station-note">{note}</span>}
    </>
  );
  return (
    <section className="station" data-state={state} data-station={id} aria-current={state === "current" ? "step" : undefined}>
      <div className="gutter">
        <span className="node">{state === "done" ? "✓" : node}</span>
        <span className="line" />
      </div>
      <div className="station-main">
        {state === "done" && children ? (
          <details className="fold">
            <summary>{head}</summary>
            <div className="station-body">{children}</div>
          </details>
        ) : (
          <>
            <div className="station-head">{head}</div>
            {state === "current" && children && <div className="station-body">{children}</div>}
          </>
        )}
      </div>
    </section>
  );
}
