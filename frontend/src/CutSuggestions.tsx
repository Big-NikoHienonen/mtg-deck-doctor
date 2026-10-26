import { useEffect, useMemo, useState } from "react";
import { aiBlocked } from "./aiStatus";
import {
  getCuts,
  keepCard,
  reviewCuts,
  swapCards,
  unkeepCard,
  type CardInfo,
  type CommanderIncludes,
  type CutReviewRequest,
  type Cuts,
  type Deck,
} from "./api";
import { analyzeCuts, describeFlag } from "./cutRanking";
import { analyzeDeck } from "./deckHealth";
import { relativeTime } from "./relativeTime";
import SwapRow from "./SwapRow";
import { CARD_MAX_WIDTH, TONES } from "./swapStyle";
import { buttonStyle } from "./styles";
import { useRowAction } from "./useRowAction";

// Each swap is two full-size cards, so a page of them is a lot of scrolling.
const PAGE_SIZE = 3;

const pct = (inclusion: number) => `${Math.round(inclusion * 100)}%`;

// A review takes about a minute and costs tokens, so one per deck at a time,
// shared by whoever asks — and a page that is left and come back to while one
// is running picks it up rather than starting another.
const inFlight = new Map<string, Promise<Cuts>>();

function requestReview(deckId: string, request: CutReviewRequest): Promise<Cuts> {
  let pending = inFlight.get(deckId);
  if (!pending) {
    pending = reviewCuts(deckId, request).finally(() => inFlight.delete(deckId));
    inFlight.set(deckId, pending);
  }
  return pending;
}

// Shown while the review runs — in the shape of the swap that will replace it,
// with a running clock, so it is plain that something is happening, what it is,
// and where the result will appear.
function ReviewProgress({ leads }: { leads: number }) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(timer);
  }, []);
  const pulse = { animation: "pulse 1.6s ease-in-out infinite" };
  const frame = (color: string) => (
    <div
      style={{
        width: "100%",
        maxWidth: CARD_MAX_WIDTH,
        aspectRatio: "488 / 680",
        border: `4px dashed ${color}`,
        borderRadius: 16,
        ...pulse,
      }}
    />
  );
  const line = (width: string) => (
    <div style={{ height: 11, width, background: "var(--user-bubble)", borderRadius: 6, ...pulse }} />
  );
  return (
    <div
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 16,
        padding: "18px 24px 26px",
        marginBottom: 28,
        boxShadow: "0 3px 14px rgba(43, 32, 24, 0.1)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12 }}>
        <div style={{ fontSize: 19, fontWeight: 600 }}>The Doctor is reviewing {leads} possible swaps…</div>
        <div style={{ fontSize: 15, color: "var(--text-muted)", fontVariantNumeric: "tabular-nums" }}>
          {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")}
        </div>
      </div>
      <div style={{ fontSize: 15, color: "var(--text-muted)", margin: "6px 0 22px", lineHeight: 1.5 }}>
        It is reading your commander and your whole list, checking each swap, and writing the reasons. The swaps it
        recommends will appear right here — usually within a minute or two.
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr) 56px minmax(0, 1fr)",
          columnGap: 14,
          rowGap: 16,
          justifyItems: "center",
          alignItems: "start",
        }}
      >
        {frame(TONES.cut.color)}
        <div aria-hidden style={{ alignSelf: "center", fontSize: 40, color: "var(--text-muted)", ...pulse }}>
          →
        </div>
        {frame(TONES.add.color)}
        {[0, 1].map((i) => (
          <div
            key={i}
            style={{
              gridColumn: i === 0 ? 1 : 3,
              width: "100%",
              maxWidth: 420,
              display: "flex",
              flexDirection: "column",
              gap: 9,
            }}
          >
            {line("92%")}
            {line("100%")}
            {line("70%")}
          </div>
        ))}
      </div>
    </div>
  );
}

// Decks the review has been started for automatically this session, so a
// failed review isn't retried in a loop — the button is there for that.
const autoStarted = new Set<string>();

// What to cut, and why. The data finds the leads — cards EDHREC decks rarely
// run with this commander, each paired with the card they run most that the
// deck lacks — and computes them here from state the page already has. A lead
// is not shown as a recommendation, or with a reason of its own: the Doctor
// reads the commander and the list, decides which swaps are really worth
// making, and says why. That review starts by itself when there is none for
// the deck (and after an import, once it is done), and is kept.
export default function CutSuggestions({
  deck,
  cardInfo,
  includes,
  replacementsReady,
  ownedCards,
  paused,
  onDeckChange,
  onHoverCard,
}: {
  deck: Deck;
  cardInfo: Record<string, CardInfo>;
  includes: CommanderIncludes | null;
  // Whether card data for the replacement candidates has been fetched (or
  // given up on) — until then pairings would come and go as it trickles in.
  replacementsReady: boolean;
  ownedCards: Set<string>;
  // True while an import is running: the review waits for it to finish.
  paused: boolean;
  onDeckChange: (deck: Deck) => void;
  onHoverCard: (name: string, id?: string | null) => void;
}) {
  const [keptOpen, setKeptOpen] = useState(false);
  const [consideredOpen, setConsideredOpen] = useState(false);
  const [shown, setShown] = useState(PAGE_SIZE);
  // undefined while the stored review is loading, null once we know there is none.
  const [cuts, setCuts] = useState<Cuts | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const row = useRowAction();

  const { analysis, health } = useMemo(() => {
    if (!includes?.available) return { analysis: null, health: null };
    const cardCounts = new Map<string, number>();
    deck.cards.forEach((name) => cardCounts.set(name, (cardCounts.get(name) ?? 0) + 1));
    const health = analyzeDeck(cardCounts, cardInfo);
    return { analysis: analyzeCuts({ cardCounts, cardInfo, keep: deck.keep, includes, health }), health };
  }, [deck.cards, deck.keep, cardInfo, includes]);

  useEffect(() => {
    let cancelled = false;
    setCuts(undefined);
    setError(null);
    setLoadFailed(false);
    const pending = inFlight.get(deck.id);
    if (pending) setBusy(true);
    getCuts(deck.id)
      .then((stored) => {
        if (!cancelled) setCuts(stored);
      })
      .catch(() => {
        if (cancelled) return;
        setCuts(null);
        setLoadFailed(true);
        setError("Couldn't load the Doctor's review.");
      });
    pending
      ?.then((result) => {
        if (!cancelled) setCuts(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Couldn't get the Doctor's review.");
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [deck.id]);

  async function review() {
    if (!analysis || !health) return;
    setBusy(true);
    setError(null);
    try {
      setCuts(
        await requestReview(deck.id, {
          candidates: analysis.candidates.map((c) => ({ cut: c.name, add: c.replacement.name, flag: describeFlag(c) })),
          health: health.metrics.map((m) => ({ label: m.label, count: m.count, target: m.target, cards: m.cards })),
        }),
      );
      setShown(PAGE_SIZE);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't get the Doctor's review. Try again.");
    } finally {
      setBusy(false);
    }
  }

  const canReview = !!analysis && replacementsReady && analysis.candidates.length > 0 && !busy && cuts !== undefined;

  // The review starts by itself: once there are leads to review, none is
  // stored, and no import is running. Once per deck per session — if it
  // fails, the button below is how to try again.
  useEffect(() => {
    if (!canReview || cuts !== null || loadFailed || paused || autoStarted.has(deck.id) || aiBlocked()) return;
    autoStarted.add(deck.id);
    review();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canReview, cuts, loadFailed, paused, deck.id]);

  async function swap(cut: string, add: string) {
    onDeckChange(await swapCards(deck.id, cut, add));
  }

  async function keep(name: string) {
    onDeckChange(await keepCard(deck.id, name));
  }

  // Whatever the user acts on leaves the review; the stored review drops it
  // too the next time it is read.
  function dismiss(cut: string) {
    setCuts((prev) =>
      prev ? { ...prev, swaps: prev.swaps.filter((s) => s.cut !== cut), kept: prev.kept.filter((k) => k.cut !== cut) } : prev,
    );
  }

  const edhrec = new Map(includes?.available ? includes.cards.map((c) => [c.name, c]) : []);
  const candidateByCut = new Map(analysis?.candidates.map((c) => [c.name, c]));

  // What the data says about a card, in a few words, to sit under its name.
  function cutStat(name: string) {
    const c = candidateByCut.get(name);
    if (c?.inclusion === null && c.belowInclusion !== null) return `under ${pct(c.belowInclusion)} of decks`;
    const listed = edhrec.get(name);
    if (listed) return `${pct(listed.inclusion)} of decks`;
    return c && c.copies > 1 ? `${c.copies} copies` : undefined;
  }
  function addStat(name: string) {
    const card = edhrec.get(name);
    if (!card) return undefined;
    return `${pct(card.inclusion)} of decks${card.synergy >= 0.1 ? ` · +${Math.round(card.synergy * 100)}% synergy` : ""}`;
  }

  const keepers = deck.keep.filter((name) => deck.cards.includes(name));
  const swaps = cuts?.swaps ?? [];
  const considered = cuts?.kept ?? [];
  return (
    <section>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, marginBottom: 18 }}>
        <div>
          <h2 style={{ fontSize: 28, fontWeight: 600, margin: 0, lineHeight: 1.2 }}>Recommended swaps</h2>
          <div style={{ fontSize: 16, color: "var(--text-muted)", marginTop: 6, maxWidth: 680, lineHeight: 1.5 }}>
            Cut the red card, add the green one. The Doctor checks each swap against {deck.commander} and your list, and
            only recommends the ones it can explain.
          </div>
        </div>
        {analysis && (cuts || error) && (
          <button className="btn" style={{ ...buttonStyle, flexShrink: 0 }} onClick={review} disabled={!canReview}>
            {busy ? "Reviewing…" : cuts ? "Review again" : "Try again"}
          </button>
        )}
      </div>

      {includes === null && <div style={{ fontSize: 15, color: "var(--text-muted)" }}>Loading EDHREC data…</div>}
      {includes && !includes.available && (
        <div style={{ fontSize: 15, color: "var(--text-muted)" }}>
          {includes.reason} The review starts from EDHREC's numbers, so it isn't available for this commander.
        </div>
      )}
      {analysis && !replacementsReady && (
        <div style={{ fontSize: 15, color: "var(--text-muted)" }}>Checking replacement candidates…</div>
      )}
      {analysis && replacementsReady && !cuts && !busy && !error && analysis.candidates.length === 0 && (
        <div style={{ fontSize: 15, color: "var(--text-muted)" }}>
          {analysis.unknownCount > 0
            ? "Still loading card data…"
            : "Nothing stands out to cut — everything left is either a keeper or fills a category that's already short."}
        </div>
      )}

      {busy && <ReviewProgress leads={analysis?.candidates.length ?? 0} />}
      {error && <div style={{ color: "var(--danger)", fontSize: 15, marginBottom: 12 }}>{error}</div>}

      {/* After one: what the Doctor recommends, with its reasons. */}
      {cuts && (
        <>
          <div style={{ fontSize: 14, color: "var(--text-muted)", marginBottom: 20 }}>
            <strong style={{ color: "var(--text)" }}>
              {swaps.length} swap{swaps.length === 1 ? "" : "s"} recommended
            </strong>
            {considered.length > 0 && ` · ${considered.length} flagged card${considered.length === 1 ? "" : "s"} the Doctor would keep`}
            {" · "}reviewed {relativeTime(cuts.generated_at)}
            {cuts.deck_changed && (
              <div style={{ color: "var(--accent-gold)", marginTop: 4 }}>
                Your deck has changed since this review — use “Review again” for swaps that fit it as it is now.
              </div>
            )}
          </div>

          {swaps.length === 0 && !busy && (
            <div style={{ color: "var(--text-muted)", fontSize: 14, marginBottom: 8 }}>
              {considered.length > 0
                ? "The Doctor would keep every flagged card as it is — its reasons are below."
                : "Nothing left to act on from that review."}
            </div>
          )}

          {swaps.slice(0, shown).map((s, i) => (
            <SwapRow
              key={s.cut}
              index={i + 1}
              total={swaps.length}
              tag={s.source === "doctor" ? "THE DOCTOR'S OWN PICK" : undefined}
              cut={{ name: s.cut, id: cardInfo[s.cut]?.id, stat: cutStat(s.cut) }}
              add={{ name: s.add, id: s.add_id, stat: addStat(s.add) }}
              reasonCut={s.reason_cut}
              reasonAdd={s.reason_add}
              owned={ownedCards.has(s.add)}
              busy={row.pending === s.cut}
              error={row.errors[s.cut]}
              onSwap={() =>
                row.run(s.cut, async () => {
                  await swap(s.cut, s.add);
                  dismiss(s.cut);
                })
              }
              onKeep={() =>
                row.run(s.cut, async () => {
                  await keep(s.cut);
                  dismiss(s.cut);
                })
              }
              onHoverCard={onHoverCard}
            />
          ))}

          {swaps.length > shown && (
            <button
              className="btn"
              style={{ ...buttonStyle, marginBottom: 8 }}
              onClick={() => setShown((n) => n + PAGE_SIZE)}
            >
              Show {Math.min(PAGE_SIZE, swaps.length - shown)} more
            </button>
          )}

          {considered.length > 0 && (
            <div style={{ marginTop: 6 }}>
              <button
                className="btn"
                style={{ ...buttonStyle, fontSize: 12, padding: "3px 10px" }}
                onClick={() => setConsideredOpen((v) => !v)}
              >
                {consideredOpen ? "▾" : "▸"} Flagged, but the Doctor would keep ({considered.length})
              </button>
              {consideredOpen && (
                <div style={{ marginTop: 6 }}>
                  {considered.map((k) => (
                    <div
                      key={k.cut}
                      className="card-row"
                      onMouseEnter={() => onHoverCard(k.cut, cardInfo[k.cut]?.id)}
                      style={{ padding: "8px 4px", borderBottom: "1px solid var(--border)" }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <div style={{ flex: 1, fontSize: 14, fontWeight: 600 }}>
                          {k.cut} <span style={{ fontSize: 12, fontWeight: 400, color: "var(--text-muted)" }}>{cutStat(k.cut)}</span>
                        </div>
                        <button
                          className="btn"
                          title="Never suggest cutting this card"
                          style={{ ...buttonStyle, fontSize: 12, padding: "3px 10px" }}
                          disabled={row.pending === k.cut}
                          onClick={() =>
                            row.run(k.cut, async () => {
                              await keep(k.cut);
                              dismiss(k.cut);
                            })
                          }
                        >
                          Always keep
                        </button>
                      </div>
                      <div style={{ fontSize: 13, color: "var(--text-muted)", lineHeight: 1.5, marginTop: 2 }}>{k.reason_cut}</div>
                      {row.errors[k.cut] && <div style={{ fontSize: 12, color: "var(--danger)" }}>{row.errors[k.cut]}</div>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}

      {analysis && (analysis.protectedCount > 0 || analysis.unknownCount > 0) && (
        <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 8 }}>
          {analysis.protectedCount > 0 &&
            `${analysis.protectedCount} cards aren't flagged because they fill a category the deck is already short on. `}
          {analysis.unknownCount > 0 && `${analysis.unknownCount} cards are skipped until their card data loads.`}
        </div>
      )}

      {keepers.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <button
            className="btn"
            style={{ ...buttonStyle, fontSize: 12, padding: "3px 10px" }}
            onClick={() => setKeptOpen((v) => !v)}
          >
            {keptOpen ? "▾" : "▸"} Kept cards ({keepers.length})
          </button>
          {keptOpen && (
            <div style={{ marginTop: 6 }}>
              {keepers.map((name) => (
                <div
                  key={name}
                  className="card-row"
                  onMouseEnter={() => onHoverCard(name, cardInfo[name]?.id)}
                  style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 4px", borderBottom: "1px solid var(--border)" }}
                >
                  <div style={{ flex: 1, fontSize: 14 }}>{name}</div>
                  <button
                    className="btn"
                    style={{ ...buttonStyle, fontSize: 12, padding: "3px 10px" }}
                    disabled={row.pending === name}
                    onClick={() => row.run(name, async () => onDeckChange(await unkeepCard(deck.id, name)))}
                  >
                    Unkeep
                  </button>
                  {row.errors[name] && <div style={{ fontSize: 12, color: "var(--danger)" }}>{row.errors[name]}</div>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
