import { useEffect, useState } from "react";
import { aiBlocked } from "./aiStatus";
import { useNavigate } from "react-router-dom";
import { refreshNewCommanders, type CommanderPick, type Hub, type NewCommanders as Picks } from "./api";
import CardImage from "./CardImage";
import ManaPips from "./ManaPips";
import { releaseNames } from "./releases";
import { buttonStyle } from "./styles";

// Set once the Doctor has been sent to look this session, so a failed look
// isn't retried in a loop — the button is for that.
let started = false;

const pulse = { animation: "pulse 1.6s ease-in-out infinite" };

function Pick({ pick, onStart }: { pick: CommanderPick; onStart: () => void }) {
  return (
    <div
      style={{
        display: "flex",
        gap: 18,
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 16,
        padding: 18,
        boxShadow: "0 3px 14px rgba(43, 32, 24, 0.1)",
      }}
    >
      <CardImage
        cardId={pick.id}
        version="normal"
        alt={pick.name}
        title={pick.name}
        loading="lazy"
        style={{ width: 220, flexShrink: 0, alignSelf: "flex-start", borderRadius: 13, boxShadow: "0 8px 20px rgba(43, 32, 24, 0.3)" }}
      />
      <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 10 }}>
        <div>
          <div style={{ fontSize: 19, fontWeight: 600, lineHeight: 1.25 }}>{pick.name}</div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--text-muted)", marginTop: 3, flexWrap: "wrap" }}>
            <ManaPips colors={pick.color_identity} size={15} />
            <span>{[pick.type_line, pick.price_usd && `$${pick.price_usd}`].filter(Boolean).join(" · ")}</span>
          </div>
        </div>

        <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.1em", color: pick.like_decks.length ? "var(--accent)" : "var(--accent-gold)" }}>
          {pick.like_decks.length ? `IN THE SPIRIT OF ${pick.like_decks.join(" · ").toUpperCase()}` : "A NEW DIRECTION"}
        </div>

        <div style={{ fontSize: 15, lineHeight: 1.55 }}>{pick.why}</div>

        {(pick.edhrec_decks !== null || pick.pairs_with.length > 0) && (
          <div style={{ fontSize: 13, color: "var(--text-muted)", lineHeight: 1.5 }}>
            {pick.edhrec_decks !== null && <div>{pick.edhrec_decks.toLocaleString()} decks on EDHREC so far.</div>}
            {pick.pairs_with.length > 0 && <div>Players pair it with {pick.pairs_with.join(", ")}.</div>}
          </div>
        )}

        <div style={{ marginTop: "auto", paddingTop: 4 }}>
          <button onClick={onStart} className="btn btn-positive" style={{ ...buttonStyle, fontWeight: 600 }}>
            {`Start a deck with ${pick.name.split(",")[0]}`}
          </button>
        </div>
      </div>
    </div>
  );
}

// New commanders from the latest sets that the Doctor thinks you'd enjoy
// building around — chosen with your own decks in mind, each with what it asks
// you to build and a button that starts that deck in the new-deck helper. Looked for once per set
// release (or when your decks change), by itself, and kept.
export default function NewCommanders({ hub, onPicks }: { hub: Hub; onPicks: (picks: Picks) => void }) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function look() {
    started = true;
    setBusy(true);
    setError(null);
    refreshNewCommanders()
      .then(onPicks)
      .catch((err) => setError(err instanceof Error ? err.message : "Couldn't look through the new commanders."))
      .finally(() => setBusy(false));
  }

  useEffect(() => {
    if (hub.latest_sets && !hub.commanders?.current && !started && !aiBlocked()) look();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hub.latest_sets, hub.commanders]);

  // Into the new-deck helper with this commander chosen: it still asks for a
  // power level and a budget, then builds the starting list.
  function start(pick: CommanderPick) {
    navigate(`/new?commander=${encodeURIComponent(pick.name)}`);
  }

  const picks = hub.commanders?.picks ?? [];
  // Nothing to show — no picks, no look under way, no error to retry — means no
  // section, not a heading over an apology.
  if (!hub.latest_sets || (!busy && picks.length === 0 && !error)) return null;
  const setNames = releaseNames(hub).join(" and ");

  return (
    <section>
      <h2 style={{ fontSize: 32, fontWeight: 600, margin: 0, lineHeight: 1.2 }}>New commanders to build around</h2>
      <div style={{ fontSize: 16, color: "var(--text-muted)", marginTop: 6, marginBottom: 24, maxWidth: 720, lineHeight: 1.5 }}>
        Legendary creatures from {setNames} that could lead your next deck, chosen with the decks you already play in mind.
      </div>

      {busy && (
        <div style={{ display: "flex", gap: 18, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 16, padding: 18 }}>
          <div style={{ width: 200, flexShrink: 0, aspectRatio: "488 / 680", border: "4px dashed var(--accent-gold)", borderRadius: 12, ...pulse }} />
          <div style={{ fontSize: 15, color: "var(--text-muted)", lineHeight: 1.5 }}>
            The Doctor is reading through the new commanders and your decks to find the ones you'd enjoy… about a minute.
          </div>
        </div>
      )}

      {!busy && picks.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(560px, 1fr))", gap: 20, alignItems: "stretch" }}>
          {picks.map((pick) => (
            <Pick key={pick.name} pick={pick} onStart={() => start(pick)} />
          ))}
        </div>
      )}

      {!busy && error && (
        <div style={{ fontSize: 14, color: "var(--danger)" }}>
          {error}{" "}
          <button className="btn" style={{ ...buttonStyle, fontSize: 12, padding: "3px 10px", marginLeft: 4 }} onClick={look}>
            Try again
          </button>
        </div>
      )}
    </section>
  );
}
