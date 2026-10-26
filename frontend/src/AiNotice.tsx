import { useEffect, useState } from "react";
import { checkAi } from "./api";
import { buttonStyle } from "./styles";

// Whole seconds left until `until` (ms since epoch), counting down; 0 when it
// has passed or there is none.
export function useSecondsUntil(until: number | null): number {
  const left = () => (until === null ? 0 : Math.max(0, Math.ceil((until - Date.now()) / 1000)));
  const [seconds, setSeconds] = useState(left);
  useEffect(() => {
    setSeconds(left());
    if (until === null || Date.now() >= until) return;
    const timer = setInterval(() => {
      const next = left();
      setSeconds(next);
      if (next === 0) clearInterval(timer);
    }, 500);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [until]);
  return seconds;
}

// Says why the Doctor can't be asked right now and what to do about it, in the
// place the player is looking. While a wait is running it counts down; when only
// a person can fix the cause (no credits, a rejected key) there is one button
// that checks, rather than a send button that fails again.
export default function AiNotice({ message, secondsLeft, canCheck }: { message: string; secondsLeft: number; canCheck: boolean }) {
  const [checking, setChecking] = useState(false);
  const [stillDown, setStillDown] = useState<string | null>(null);

  async function check() {
    setChecking(true);
    setStillDown(await checkAi());
    setChecking(false);
  }

  return (
    <div role="alert" style={{ borderLeft: "4px solid var(--accent-gold)", background: "var(--surface)", padding: "10px 14px", fontSize: 14, lineHeight: 1.5 }}>
      <div>{message}</div>
      {secondsLeft > 0 && <div style={{ color: "var(--text-muted)", marginTop: 4 }}>You can try again in {secondsLeft}s.</div>}
      {canCheck && (
        <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <button type="button" className="btn" style={buttonStyle} onClick={check} disabled={checking}>
            {checking ? "Checking…" : "Check again"}
          </button>
          {stillDown && !checking && (
            <span style={{ color: "var(--text-muted)" }}>Still not working{stillDown === message ? "." : `: ${stillDown}`}</span>
          )}
        </div>
      )}
    </div>
  );
}
