import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getUsage, type Usage, type UsageTotals } from "./api";
import "./admin.css";

const RANGES = [7, 14, 30] as const;
const REFRESH_MS = 15_000;

// What each model call is, in words. Structured calls are logged as "structured:<function>".
const FEATURE_NAMES: Record<string, string> = {
  chat: "Doctor chat",
  ping: "Status check",
  "structured:suggest_cards": "Card suggestions",
  "structured:review_cuts": "Cut review",
  "structured:discover_new_cards": "New-card discoveries",
  "structured:pick_commanders": "New commanders for you",
  "structured:explain_commanders": "Commander explanations",
  "structured:interpret_deck_request": "Reading a deck brief",
  "structured:plan_commander_search": "Commander search",
  "structured:propose_commanders": "Commander options",
  "structured:plan_phases": "Build plan",
  "structured:propose_phase": "Build phase",
};
const featureName = (key: string) => FEATURE_NAMES[key] ?? key.replace("structured:", "").replaceAll("_", " ");

const STOPS: Record<string, string> = { end_turn: "done", tool_use: "tool call", max_tokens: "cut off" };

const usd = (n: number) => (n > 0 && n < 0.01 ? `$${n.toFixed(4)}` : `$${n.toFixed(2)}`);
const tokens = (n: number) => (n >= 1_000_000 ? `${(n / 1_000_000).toFixed(2)}M` : n >= 10_000 ? `${(n / 1000).toFixed(0)}K` : n >= 1000 ? `${(n / 1000).toFixed(1)}K` : String(n));

// The share of a call's input that came from the cache.
function cacheShare(t: Pick<UsageTotals, "input" | "cache_read" | "cache_write">): string {
  const all = t.input + t.cache_read + t.cache_write;
  return all > 0 ? `${Math.round((t.cache_read / all) * 100)}%` : "—";
}

// The last `count` UTC dates, oldest first, as "2026-11-09".
function lastDays(count: number): string[] {
  const out: string[] = [];
  for (let i = count - 1; i >= 0; i--) out.push(new Date(Date.now() - i * 86_400_000).toISOString().slice(0, 10));
  return out;
}

const sum = (rows: UsageTotals[]): UsageTotals =>
  rows.reduce(
    (a, r) => ({ calls: a.calls + r.calls, usd: a.usd + r.usd, input: a.input + r.input, output: a.output + r.output, cache_read: a.cache_read + r.cache_read, cache_write: a.cache_write + r.cache_write }),
    { calls: 0, usd: 0, input: 0, output: 0, cache_read: 0, cache_write: 0 },
  );

function Stat({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="ad-stat">
      <div className="ad-label">{label}</div>
      <div className="ad-value">{value}</div>
      <div className="ad-note">{note}</div>
    </div>
  );
}

// Where the Doctor's spending goes: today and lately, by day and by feature, and the calls themselves.
export default function AdminPage() {
  const [days, setDays] = useState<(typeof RANGES)[number]>(14);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updated, setUpdated] = useState<Date | null>(null);

  const load = useCallback(async () => {
    try {
      setUsage(await getUsage(days, 60));
      setError(null);
      setUpdated(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't load the usage.");
    }
  }, [days]);

  useEffect(() => {
    load();
    const timer = window.setInterval(() => document.visibilityState === "visible" && load(), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  const dates = lastDays(days);
  const perDay = dates.map((d) => ({ date: d, ...(usage?.by_day[d] ?? sum([])) }));
  const total = sum(perDay);
  const tallest = Math.max(...perDay.map((d) => d.usd), 0.0001);
  const today = new Date().toISOString().slice(0, 10);
  const features = Object.entries(usage?.by_feature ?? {});

  return (
    <div className="ad">
      <header className="ad-head">
        <div>
          <Link to="/decks" className="ad-back">
            ← ALL DECKS
          </Link>
          <h1>AI usage</h1>
          <p className="ad-sub">What the Doctor's model calls have used. Costs are estimates from token counts and published rates, not the invoice.</p>
        </div>
        <div className="ad-controls">
          <div className="ad-range" role="group" aria-label="Range">
            {RANGES.map((r) => (
              <button key={r} aria-pressed={days === r} onClick={() => setDays(r)}>
                {r} days
              </button>
            ))}
          </div>
          <button className="ad-refresh" onClick={load}>
            Refresh
          </button>
          <span className="ad-updated">{updated ? `Updated ${updated.toLocaleTimeString()}` : "Loading…"}</span>
        </div>
      </header>

      {error && <div className="ad-error">{error}</div>}

      {usage && (
        <>
          <section className="ad-stats">
            <Stat label="TODAY" value={usd(usage.today_usd)} note={`${usage.today.calls} calls · ${tokens(usage.today.input + usage.today.cache_read + usage.today.cache_write)} in · ${tokens(usage.today.output)} out`} />
            <Stat label={`LAST ${days} DAYS`} value={usd(total.usd)} note={`${total.calls} calls · ${tokens(total.output)} tokens out`} />
            <Stat label="PER DAY, ON AVERAGE" value={usd(total.usd / days)} note={`over ${days} days, quiet ones included`} />
            <Stat label="SERVED FROM CACHE" value={cacheShare(total)} note="of the input tokens, at a tenth of the price" />
          </section>

          <p className="ad-budget">
            {usage.daily_budget_usd === null ? (
              <>No daily limit is set, so nothing is ever held back. To add one, set <code>AI_DAILY_BUDGET_USD</code> in the backend's environment.</>
            ) : (
              <>
                Daily limit {usd(usage.daily_budget_usd)}: {usd(usage.today_usd)} used ({Math.round((usage.today_usd / usage.daily_budget_usd) * 100)}%), resets in about {Math.max(1, Math.round(usage.resets_in_seconds / 3600))} h.
              </>
            )}
          </p>

          <section>
            <h2>Cost per day</h2>
            <div className="ad-chart" role="img" aria-label={`Cost per day over the last ${days} days`}>
              {perDay.map((d) => (
                <div key={d.date} className="ad-bar" data-today={d.date === today} title={`${d.date}: ${usd(d.usd)}, ${d.calls} calls, ${tokens(d.input + d.cache_read + d.cache_write)} in, ${tokens(d.output)} out`}>
                  <div className="ad-bar-top">{d.usd > 0 ? usd(d.usd) : ""}</div>
                  <div className="ad-bar-fill" style={{ height: `${Math.max(d.usd > 0 ? 3 : 0, (d.usd / tallest) * 100)}%` }} />
                  <div className="ad-bar-day">{d.date.slice(8)}</div>
                </div>
              ))}
            </div>
          </section>

          <section>
            <h2>By feature</h2>
            {features.length === 0 ? (
              <p className="ad-empty">No calls in this range.</p>
            ) : (
              <table className="ad-table">
                <thead>
                  <tr>
                    <th>Feature</th>
                    <th className="num">Calls</th>
                    <th className="num">Cost</th>
                    <th className="num">Share</th>
                    <th className="num">Per call</th>
                    <th className="num">Input</th>
                    <th className="num">Output</th>
                    <th className="num">Cached</th>
                  </tr>
                </thead>
                <tbody>
                  {features.map(([key, f]) => (
                    <tr key={key}>
                      <td>{featureName(key)}</td>
                      <td className="num">{f.calls}</td>
                      <td className="num">{usd(f.usd)}</td>
                      <td className="num">
                        <span className="ad-share">
                          <i style={{ width: `${total.usd > 0 ? (f.usd / total.usd) * 100 : 0}%` }} />
                        </span>
                        {total.usd > 0 ? `${Math.round((f.usd / total.usd) * 100)}%` : "—"}
                      </td>
                      <td className="num">{usd(f.usd / f.calls)}</td>
                      <td className="num">{tokens(f.input + f.cache_read + f.cache_write)}</td>
                      <td className="num">{tokens(f.output)}</td>
                      <td className="num">{cacheShare(f)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section>
            <h2>Latest calls</h2>
            {usage.recent.length === 0 ? (
              <p className="ad-empty">No calls yet.</p>
            ) : (
              <div className="ad-scroll">
                <table className="ad-table">
                  <thead>
                    <tr>
                      <th>When</th>
                      <th>Feature</th>
                      <th className="num">New input</th>
                      <th className="num">Cached</th>
                      <th className="num">Output</th>
                      <th className="num">Cost</th>
                      <th className="num">Took</th>
                      <th>Ended</th>
                    </tr>
                  </thead>
                  <tbody>
                    {usage.recent.map((c, i) => {
                      const at = new Date(c.at);
                      return (
                        <tr key={`${c.at}-${i}`}>
                          <td title={at.toLocaleString()}>{c.at.slice(0, 10) === today ? at.toLocaleTimeString() : at.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</td>
                          <td>{featureName(c.feature)}</td>
                          <td className="num">{tokens(c.input + c.cache_write)}</td>
                          <td className="num">{tokens(c.cache_read)}</td>
                          <td className="num">{tokens(c.output)}</td>
                          <td className="num">{usd(c.usd)}</td>
                          <td className="num">{c.seconds !== null ? `${c.seconds.toFixed(1)}s` : "—"}</td>
                          <td>{c.stop ? (STOPS[c.stop] ?? c.stop) : "—"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <p className="ad-settings">
            Model <code>{usage.settings.model}</code> · chat effort <code>{usage.settings.chat_effort}</code> · up to {usage.settings.max_tool_rounds} model calls per chat message · prices in the estimate are the published per-token rates; days are UTC.
          </p>
        </>
      )}
    </div>
  );
}
