import { useEffect, useState, type ReactNode } from "react";
import { aiBlocked } from "./aiStatus";
import { Link } from "react-router-dom";
import { refreshDiscoveries, scryfallImageUrlById, type DeckDiscoveries, type Discovery, type Hub, type HubDeck } from "./api";
import CardImage from "./CardImage";
import { relativeTime } from "./relativeTime";
import { releaseName, releaseNames } from "./releases";
import { buttonStyle } from "./styles";

// Decks the Doctor has been sent to look through the newest sets for this
// session, so a failed look isn't retried in a loop — the button is for that.
const started = new Set<string>();

const pulse = { animation: "pulse 1.6s ease-in-out infinite" };

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en", { day: "numeric", month: "long", year: "numeric" });
}

// What makes this card worth showing, in the Doctor's words, and which of the
// deck's own cards it works with.
function Why({ pick }: { pick: Discovery }) {
  return (
    <>
      <div style={{ fontSize: 15, lineHeight: 1.55 }}>{pick.why}</div>
      {pick.works_with.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10, alignItems: "center" }}>
          <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.1em", color: "var(--accent)" }}>WORKS WITH</span>
          {pick.works_with.map((n) => (
            <span
              key={n}
              style={{ fontSize: 12, background: "var(--user-bubble)", borderRadius: 999, padding: "2px 10px" }}
            >
              {n}
            </span>
          ))}
        </div>
      )}
    </>
  );
}

function cardFacts(pick: Discovery): string {
  return [pick.type_line, pick.price_usd && `$${pick.price_usd}`].filter(Boolean).join(" · ");
}

// One pick as a card to look at: the card large, what it is, why it is here.
function PickCard({ pick, maxImage = 260, children }: { pick: Discovery; maxImage?: number; children?: ReactNode }) {
  return (
    <div
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 16,
        padding: "18px 18px 20px",
        boxShadow: "0 3px 14px rgba(43, 32, 24, 0.1)",
      }}
    >
      <CardImage
        cardId={pick.id}
        version="normal"
        alt={pick.name}
        title={pick.name}
        loading="lazy"
        style={{ width: "100%", maxWidth: maxImage, display: "block", margin: "0 auto", borderRadius: 14, boxShadow: "0 8px 20px rgba(43, 32, 24, 0.3)" }}
      />
      <div style={{ textAlign: "center", margin: "14px 0 12px" }}>
        <div style={{ fontSize: 18, fontWeight: 600, lineHeight: 1.25 }}>{pick.name}</div>
        <div style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 2 }}>{cardFacts(pick)}</div>
      </div>
      <Why pick={pick} />
      {children}
    </div>
  );
}

// Every pick for one deck, all the same size, over the page.
function PicksModal({ deck, picks, releases, onClose }: { deck: HubDeck; picks: Discovery[]; releases: string; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    // The page behind stays put while this is open.
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [onClose]);

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(20, 14, 8, 0.6)",
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        padding: "4vh 16px",
        zIndex: 100,
        overflowY: "auto",
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`New cards for ${deck.title}`}
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--bg)",
          border: "1px solid var(--border)",
          borderRadius: 16,
          width: "100%",
          maxWidth: 1180,
          padding: "22px 24px 28px",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, marginBottom: 20 }}>
          <Link to={`/decks/${deck.id}`} style={{ display: "flex", alignItems: "center", gap: 12, textDecoration: "none", color: "inherit" }}>
            {deck.commander_id && (
              <img
                src={scryfallImageUrlById(deck.commander_id, "art_crop")}
                alt=""
                style={{ width: 52, height: 52, borderRadius: "50%", objectFit: "cover" }}
              />
            )}
            <div>
              <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.1em", color: "var(--accent)" }}>
                {picks.length} NEW CARDS FOR YOUR DECK
              </div>
              <div style={{ fontSize: 24, fontWeight: 600, lineHeight: 1.2 }}>{deck.title}</div>
              <div style={{ fontSize: 14, color: "var(--text-muted)", marginTop: 2 }}>From {releases}, best fit first.</div>
            </div>
          </Link>
          <button onClick={onClose} aria-label="Close" className="btn" style={{ ...buttonStyle, padding: "4px 12px", fontSize: 18 }}>
            &times;
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 22, alignItems: "stretch" }}>
          {picks.map((pick) => (
            <PickCard key={pick.name} pick={pick} maxImage={300} />
          ))}
        </div>
      </div>
    </div>
  );
}

// One deck's column: the best new card for it, large, with why, and a way to see
// all of them at the same size.
function DeckColumn({
  deck,
  discoveries,
  releases,
  busy,
  error,
  onRetry,
}: {
  deck: HubDeck;
  discoveries: DeckDiscoveries | null;
  releases: string;
  busy: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  const picks = discoveries?.picks ?? [];
  const [top] = picks;
  const [showAll, setShowAll] = useState(false);
  return (
    <div style={{ minWidth: 0 }}>
      <Link
        to={`/decks/${deck.id}`}
        style={{ display: "flex", alignItems: "center", gap: 10, textDecoration: "none", color: "inherit", marginBottom: 14 }}
      >
        {deck.commander_id && (
          <img
            src={scryfallImageUrlById(deck.commander_id, "art_crop")}
            alt=""
            style={{ width: 40, height: 40, borderRadius: "50%", objectFit: "cover" }}
          />
        )}
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.1em", color: "var(--accent)" }}>FOR YOUR DECK</div>
          <div style={{ fontSize: 17, fontWeight: 600, lineHeight: 1.2 }}>{deck.title}</div>
        </div>
      </Link>

      {top && <PickCard pick={top} />}

      {picks.length > 1 && (
        <button
          onClick={() => setShowAll(true)}
          className="btn"
          style={{ ...buttonStyle, width: "100%", marginTop: 12, fontSize: 15, padding: "10px 14px" }}
        >
          See all {picks.length} picks for {deck.title}
        </button>
      )}
      {showAll && <PicksModal deck={deck} picks={picks} releases={releases} onClose={() => setShowAll(false)} />}

      {busy && (
        <div
          style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 16, padding: "18px 18px 22px" }}
        >
          <div
            style={{
              width: "100%",
              maxWidth: 260,
              aspectRatio: "488 / 680",
              margin: "0 auto",
              border: "4px dashed var(--accent-gold)",
              borderRadius: 14,
              ...pulse,
            }}
          />
          <div style={{ fontSize: 15, color: "var(--text-muted)", marginTop: 14, lineHeight: 1.5 }}>
            The Doctor is looking through the new cards for {deck.title}… about a minute.
          </div>
        </div>
      )}

      {!busy && error && (
        <div style={{ fontSize: 14, color: "var(--danger)" }}>
          {error}{" "}
          <button className="btn" style={{ ...buttonStyle, fontSize: 12, padding: "3px 10px", marginLeft: 4 }} onClick={onRetry}>
            Try again
          </button>
        </div>
      )}
    </div>
  );
}

// The page's opening: cards from the newest sets that could work in each of
// your decks, found and explained by the Doctor — a look at what's new, not a
// list of what's wrong. The Doctor looks once per deck per set release, by
// itself, and the result is kept.
export default function NewCards({
  hub,
  onDiscoveries,
}: {
  hub: Hub;
  onDiscoveries: (deckId: string, discoveries: DeckDiscoveries) => void;
}) {
  const [busy, setBusy] = useState<Set<string>>(new Set());
  const [errors, setErrors] = useState<Record<string, string>>({});
  const decks = hub.decks.filter((d) => d.commander);

  function look(deck: HubDeck) {
    started.add(deck.id);
    setBusy((prev) => new Set(prev).add(deck.id));
    setErrors((prev) => ({ ...prev, [deck.id]: "" }));
    refreshDiscoveries(deck.id)
      .then((d) => onDiscoveries(deck.id, d))
      .catch((err) => setErrors((prev) => ({ ...prev, [deck.id]: err instanceof Error ? err.message : "Couldn't look through the new cards." })))
      .finally(() =>
        setBusy((prev) => {
          const next = new Set(prev);
          next.delete(deck.id);
          return next;
        }),
      );
  }

  useEffect(() => {
    if (!hub.latest_sets) return;
    for (const deck of decks) {
      if (!deck.discoveries?.current && !started.has(deck.id) && !aiBlocked()) look(deck);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hub.latest_sets, hub.decks]);

  // A deck gets a column only when there is something to show in it: cards, a
  // look under way, or an error to retry. One the Doctor found nothing for is
  // left out rather than shown as an empty heading, and with none to show the
  // whole section goes.
  const shown = decks.filter((d) => busy.has(d.id) || errors[d.id] || (d.discoveries?.picks.length ?? 0) > 0);
  if (!hub.latest_sets || shown.length === 0) return null;

  return (
    <section>
      <h2 style={{ fontSize: 32, fontWeight: 600, margin: 0, lineHeight: 1.2 }}>New in {releaseNames(hub).join(" and ")}</h2>
      <div style={{ fontSize: 16, color: "var(--text-muted)", marginTop: 6, marginBottom: 24, maxWidth: 720, lineHeight: 1.5 }}>
        {hub.latest_sets.releases.map((r) => `${releaseName(r)} came out ${formatDate(r.released_at)}`).join(", ")}. Cards from them that the
        Doctor thinks could work in your decks, and how.
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(270px, 1fr))", gap: 24, alignItems: "start" }}>
        {shown.map((deck) => (
          <DeckColumn
            key={deck.id}
            deck={deck}
            discoveries={deck.discoveries}
            releases={releaseNames(hub).join(" and ")}
            busy={busy.has(deck.id)}
            error={errors[deck.id] || null}
            onRetry={() => look(deck)}
          />
        ))}
      </div>
      {shown.some((d) => d.discoveries) && (
        <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 14 }}>
          Looked through {releaseNames(hub).join(" and ")}
          {(() => {
            const t = shown.map((d) => d.discoveries?.generated_at).filter(Boolean).sort().at(-1);
            return t ? ` · ${relativeTime(t)}` : "";
          })()}
        </div>
      )}
    </section>
  );
}
