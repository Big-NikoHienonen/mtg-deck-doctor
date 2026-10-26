import { useMemo, type ReactNode } from "react";
import type { Build, BuildPhase, BuildPick } from "./api";
import AiNotice, { useSecondsUntil } from "./AiNotice";
import CardImage from "./CardImage";
import CardSearchBox from "./CardSearchBox";
import { Says, Thinking, Typed } from "./StudioStation";
import { colorComboName } from "./wizardData";

export const money = (n: number) => `$${n.toLocaleString("en", { maximumFractionDigits: 0 })}`;

// What the player has staged for the next round, kept by the page and changed from the cards.
export type CommanderSteer = {
  // Commanders to rule out, with the reason typed so far.
  rejecting: Record<string, string>;
  // Commanders to find more like.
  liking: Set<string>;
  // Facts to take back.
  dropping: Set<string>;
  onReject: (name: string) => void;
  onReason: (name: string, reason: string) => void;
  onLike: (name: string) => void;
  onDrop: (fact: string) => void;
};

// How a round went, in a line: how many were looked at, and what was added when the searches found few.
function roundNote(build: Build): string {
  const round = build.rounds[build.rounds.length - 1];
  if (!round) return "";
  const parts = [`Round ${build.rounds.length}`, `looked at ${round.considered} commanders`];
  if (round.topped_up) parts.push(`only ${round.matched} matched exactly, so I added the best-known in ${round.topped_up}`);
  return parts.join(" · ");
}

// What each earlier round was asked and came to, folded under the current one.
function EarlierRounds({ rounds }: { rounds: Build["rounds"] }) {
  const before = rounds.slice(0, -1);
  if (before.length === 0) return null;
  return (
    <details className="rounds">
      <summary>
        Earlier rounds <span className="station-note">({before.length})</span>
      </summary>
      <ol>
        {before.map((r, i) => (
          <li key={i}>
            <span className="rounds-said">{r.said ? `“${r.said}”` : i === 0 ? "Your brief" : "Changes only"}</span>
            {(r.rejected.length > 0 || r.liked.length > 0) && (
              <span className="station-note">
                {" "}
                {r.rejected.length > 0 ? `ruled out ${r.rejected.join(", ")}` : ""}
                {r.rejected.length > 0 && r.liked.length > 0 ? "; " : ""}
                {r.liked.length > 0 ? `more like ${r.liked.join(", ")}` : ""}
              </span>
            )}
            <span className="station-note"> → {r.options.join(" · ")}</span>
          </li>
        ))}
      </ol>
    </details>
  );
}

// The commanders the Doctor offers, round by round: what it has learnt, the closest it found,
// and ways to sharpen the next round from the cards (the words go in the dock below).
export function CommanderBody({
  build,
  animate,
  acting,
  steer,
  notice,
  onChoose,
}: {
  build: Build;
  // Whether the Doctor's line is typed out as new.
  animate: boolean;
  acting: boolean;
  steer: CommanderSteer;
  // What to show above the cards: the Doctor at work on the next round, or why it couldn't.
  notice: ReactNode;
  onChoose: (name: string) => void;
}) {
  const round = build.rounds[build.rounds.length - 1];
  const refining = !!build.busy;
  const notes = build.rounds.length <= 1 ? (build.resolved?.notes ?? []).join(" ") : "";
  const understood = `${round?.understood || build.resolved?.understood || ""} ${notes}`.trim();
  const first = build.rounds.length <= 1;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <Says>
        <Typed text={understood} animate={animate} />
        <div className="station-note" style={{ marginTop: 6 }}>
          {first
            ? `${roundNote(build)}. Tell me more below, or rule one out, and I'll look again.`
            : `${roundNote(build)}.`}
        </div>
      </Says>
      {(build.facts.length > 0 || build.rejected.length > 0) && (
        <div className="facts">
          {build.facts.length > 0 && (
            <>
              <div className="kicker">WHAT I&apos;M LOOKING FOR · take one back with ×</div>
              <div className="mini-chips" style={{ marginTop: 0 }}>
                {build.facts.map((f) => (
                  <button key={f} type="button" className="fact" data-struck={steer.dropping.has(f)} disabled={refining} onClick={() => steer.onDrop(f)} title={steer.dropping.has(f) ? "Keep this" : "Take this back"}>
                    {f}
                    <span aria-hidden>{steer.dropping.has(f) ? "↺" : "×"}</span>
                  </button>
                ))}
              </div>
            </>
          )}
          {build.rejected.length > 0 && (
            <div className="station-note" style={{ marginTop: 8 }}>
              Ruled out: {build.rejected.map((r) => (r.reason ? `${r.name.split(",")[0]} (${r.reason})` : r.name.split(",")[0])).join(" · ")}
            </div>
          )}
        </div>
      )}
      {notice}
      <div
        className="stagger"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(250px, 330px))",
          gap: 18,
          alignItems: "stretch",
          opacity: refining ? 0.45 : 1,
          pointerEvents: refining ? "none" : undefined,
          transition: "opacity 200ms ease",
        }}
        aria-busy={refining}
      >
        {build.commander_options.map((o, i) => {
          const ruled = o.name in steer.rejecting;
          const liked = steer.liking.has(o.name);
          return (
            <div key={o.name} className="panel cmd-card" data-ruled={ruled} data-liked={liked} style={{ display: "flex", flexDirection: "column", gap: 10, ["--i" as string]: i }}>
              <CardImage cardId={o.id} version="normal" alt={o.name} loading="lazy" style={{ width: "100%", maxWidth: 240, margin: "0 auto", display: "block", borderRadius: 12, boxShadow: "0 6px 16px rgba(43, 32, 24, 0.3)" }} />
              <div style={{ fontSize: 19, fontWeight: 600, lineHeight: 1.25 }}>{o.name}</div>
              <div className="station-note">
                <strong style={{ color: "var(--text)" }}>{o.colors ? colorComboName(o.colors.split("")) : "Colorless"}</strong> · {o.num_decks.toLocaleString()} decks on EDHREC
                {o.decks_at_bracket !== null ? `, ${o.decks_at_bracket.toLocaleString()} at this power level` : ""}
              </div>
              {o.why && <div style={{ fontSize: 14, lineHeight: 1.55 }}>{o.why}</div>}
              {(o.fits.length > 0 || o.misses.length > 0) && (
                <ul className="fit-list">
                  {o.fits.map((f) => (
                    <li key={f} data-fit="yes">
                      {f}
                    </li>
                  ))}
                  {o.misses.map((f) => (
                    <li key={f} data-fit="no">
                      {f}
                    </li>
                  ))}
                </ul>
              )}
              <div style={{ marginTop: "auto", display: "flex", flexDirection: "column", gap: 8, paddingTop: 6 }}>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  <button type="button" className="pref" data-set={liked} aria-pressed={liked} onClick={() => steer.onLike(o.name)}>
                    {liked ? "✓ More like this" : "More like this"}
                  </button>
                  <button type="button" className="pref" data-set={ruled} aria-pressed={ruled} onClick={() => steer.onReject(o.name)}>
                    {ruled ? "✓ Not this one" : "Not this one"}
                  </button>
                </div>
                {ruled && (
                  <input
                    className="reason"
                    value={steer.rejecting[o.name]}
                    maxLength={200}
                    onChange={(e) => steer.onReason(o.name, e.target.value)}
                    placeholder="What's wrong with it? (helps the next round)"
                    aria-label={`What's wrong with ${o.name}`}
                  />
                )}
                <button className="go" disabled={acting} style={{ width: "100%" }} onClick={() => onChoose(o.name)}>
                  Build around {o.name.split(",")[0]}
                </button>
              </div>
            </div>
          );
        })}
      </div>
      <EarlierRounds rounds={build.rounds} />
      <div className="panel">
        <div style={{ fontWeight: 600, marginBottom: 8 }}>Or choose a different commander</div>
        <CardSearchBox placeholder="Search for a commander…" submitLabel="Use this one" onSubmit={async (name) => onChoose(name)} />
      </div>
    </div>
  );
}

// The strategy and the order, in the Doctor's words.
export function PlanBody({ build, animate }: { build: Build; animate: boolean }) {
  const plan = build.plan!;
  return (
    <div style={{ display: "flex", gap: 20, flexWrap: "wrap", alignItems: "flex-start" }}>
      {build.commander && (
        <CardImage cardId={build.commander.id} version="normal" alt={build.commander.name} style={{ width: 150, flexShrink: 0, borderRadius: 10, boxShadow: "0 6px 16px rgba(43, 32, 24, 0.3)" }} />
      )}
      <div style={{ flex: 1, minWidth: 260 }}>
        <Says>
          <Typed text={plan.strategy} animate={animate} />
        </Says>
        {plan.order_reason && (
          <div style={{ marginLeft: 42, borderLeft: "4px solid var(--accent-gold)", paddingLeft: 14, fontSize: 16, lineHeight: 1.6, maxWidth: 700 }}>
            <strong>The order.</strong> <Typed text={plan.order_reason} animate={animate} />
          </div>
        )}
        <div className="mini-chips" style={{ marginLeft: 42, marginTop: 14 }}>
          {plan.phases.map((p, i) => (
            <span key={p.id} className="mini-chip">
              {i + 1}. {p.label} · {p.count}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

// One proposed card: the card, what it does here, and whether it stays.
function PickTile({ pick, kept, onToggle }: { pick: BuildPick; kept: boolean; onToggle: () => void }) {
  return (
    <button type="button" className="pick" aria-pressed={kept} onClick={onToggle} title={kept ? "Click to take it out" : "Click to keep it"}>
      <CardImage cardId={pick.id} version="normal" alt={pick.name} loading="lazy" style={{ width: "100%", display: "block", borderRadius: 10 }} />
      <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span className="pick-mark">{kept ? "✓" : "×"}</span>
        <span style={{ fontSize: 15, fontWeight: 600, lineHeight: 1.25 }}>{pick.name}</span>
      </span>
      <span className="station-note">
        {pick.type.split("—")[0].trim()}
        {pick.price >= 1 ? ` · ${money(pick.price)}` : ""}
      </span>
      <span style={{ fontSize: 13, lineHeight: 1.5 }}>{pick.why}</span>
    </button>
  );
}

function LandRow({ pick, kept, onToggle }: { pick: BuildPick; kept: boolean; onToggle: () => void }) {
  return (
    <button type="button" className="land-row" aria-pressed={kept} onClick={onToggle} title={kept ? "Click to take it out" : "Click to keep it"}>
      <CardImage cardId={pick.id} version="small" alt="" loading="lazy" style={{ width: 52, borderRadius: 4, display: "block" }} />
      <span>
        <span style={{ fontWeight: 600, fontSize: 15 }}>{pick.name}</span>
        <span className="station-note" style={{ display: "block", fontSize: 13 }}>{pick.why}</span>
      </span>
      <span className="station-note">{pick.price >= 1 ? money(pick.price) : ""}</span>
      <span style={{ fontSize: 16, color: kept ? "var(--positive)" : "var(--danger)", fontWeight: 700, textAlign: "center" }}>{kept ? "✓" : "×"}</span>
    </button>
  );
}

// The open phase: what the Doctor chose and why, to keep or take out. Locking it in, or
// asking for something different, is done from the dock at the bottom.
export function PhaseBody({
  build,
  phase,
  removed,
  onToggle,
  animate,
}: {
  build: Build;
  phase: BuildPhase;
  removed: Set<string>;
  onToggle: (name: string) => void;
  animate: boolean;
}) {
  const proposal = build.proposal;
  if (build.working || !proposal) {
    return build.error ? null : <Thinking steps={[build.working_label ?? `Choosing the ${phase.label.toLowerCase()}…`]} />;
  }
  const lands = phase.kind === "lands";
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {proposal.summary && (
        <Says>
          <Typed text={proposal.summary} animate={animate} />
        </Says>
      )}
      {proposal.notes.map((n) => (
        <div key={n} className="station-note" style={{ color: "var(--accent-gold)", marginLeft: 42 }}>
          {n}
        </div>
      ))}
      {proposal.cards.length === 0 ? (
        <div className="panel">Nothing on the list suited this phase. Ask for something different below, or lock it in empty and move on.</div>
      ) : lands ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {proposal.cards.map((c) => (
            <LandRow key={c.name} pick={c} kept={!removed.has(c.name)} onToggle={() => onToggle(c.name)} />
          ))}
        </div>
      ) : (
        <div className="stagger" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 16, alignItems: "start" }}>
          {proposal.cards.map((c) => (
            <PickTile key={c.name} pick={c} kept={!removed.has(c.name)} onToggle={() => onToggle(c.name)} />
          ))}
        </div>
      )}
      {lands && proposal.basics && Object.keys(proposal.basics).length > 0 && (
        <div className="panel" style={{ fontSize: 15 }}>
          <strong>Plus basics, split by what your cards cost:</strong> {Object.entries(proposal.basics).map(([n, q]) => `${n} ×${q}`).join(", ")}
        </div>
      )}
      <div className="station-note">
        Click a card to take it out. Use the bar below to lock the phase in, or to have the Doctor replace what you took out.
      </div>
    </div>
  );
}

// The finished list, phase by phase.
export function ReviewBody({ build }: { build: Build }) {
  const phases = build.plan!.phases;
  const byPhase = useMemo(() => {
    const map = new Map<string, Build["deck"]["cards"]>();
    for (const c of build.deck.cards) map.set(c.phase, [...(map.get(c.phase) ?? []), c]);
    return map;
  }, [build.deck.cards]);
  // Basic lands to fill the places the phases left cost a little too.
  const total = build.deck.price + Math.max(99 - build.deck.count, 0) * 0.15;
  const over = build.budget !== null && total > build.budget + 1;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Says>
        {build.commander?.name} and {build.deck.count} more cards, {money(total)}
        {build.budget ? (over ? `, over your ${money(build.budget)} budget` : ` of your ${money(build.budget)} budget`) : ""}. Make it and the Doctor stays on in Correspondence with its reasons for every phase.
      </Says>
      {build.deck.count < 99 && (
        <div className="panel" style={{ borderColor: "var(--accent-gold)", fontSize: 15 }}>
          The phases came to {build.deck.count} cards, so the other {99 - build.deck.count} places will be basic lands. You can swap them for anything once the deck is made.
        </div>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))", gap: 14, alignItems: "start" }}>
        {phases.map((p) => {
          const cards = byPhase.get(p.id) ?? [];
          if (cards.length === 0) return null;
          return (
            <div key={p.id} className="panel" style={{ padding: "14px 16px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                <strong>{p.label}</strong>
                <span className="station-note">{cards.reduce((n, c) => n + c.qty, 0)}</span>
              </div>
              <div style={{ fontSize: 13, lineHeight: 1.7 }}>
                {cards.map((c) => (
                  <div key={c.name} style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
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
      </div>
    </div>
  );
}

// A phase that is done, opened up: what the Doctor said and the cards kept.
export function LockedPhaseBody({ build, phase }: { build: Build; phase: BuildPhase }) {
  const cards = build.deck.cards.filter((c) => c.phase === phase.id);
  return (
    <div className="mini-chips" style={{ marginTop: 0 }}>
      {cards.map((c) => (
        <span key={c.name} className="mini-chip" style={{ fontSize: 13 }}>
          {c.qty > 1 ? `${c.qty}× ` : ""}
          {c.name}
          {c.price >= 1 ? ` · ${money(c.price)}` : ""}
        </span>
      ))}
    </div>
  );
}

// Failures of the Doctor's work, with a way to try again. A problem only a person can fix
// (no credits, a rejected key) gets the check-again button as well.
export function ErrorBody({
  error,
  acting,
  onRetry,
  onBack,
}: {
  error: NonNullable<Build["error"]>;
  acting: boolean;
  onRetry: () => void;
  // Back to the brief, to change it; offered where the brief itself may be the problem.
  onBack?: () => void;
}) {
  const until = useMemo(() => (error.retry_after ? Date.now() + error.retry_after * 1000 : null), [error]);
  const wait = useSecondsUntil(until);
  const needsFixing = error.code === "ai_credits" || error.code === "ai_auth";
  // A 400 or 422 means what was asked can't be done as it stands; trying the same again won't change that.
  const briefProblem = error.status === 400 || error.status === 422;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10, maxWidth: 640 }}>
      <AiNotice message={error.detail} secondsLeft={wait} canCheck={needsFixing} />
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        {!briefProblem && (
          <button className="ghost" disabled={acting || wait > 0} onClick={onRetry}>
            Try again
          </button>
        )}
        {onBack && (
          <button className={briefProblem ? "go" : "ghost"} onClick={onBack}>
            Change the brief
          </button>
        )}
      </div>
    </div>
  );
}
