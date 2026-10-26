import { Link } from "react-router-dom";
import { keepCard, swapCards, type Hub } from "./api";
import SwapRow from "./SwapRow";
import { useRowAction } from "./useRowAction";

const pct = (inclusion: number) => `${Math.round(inclusion * 100)}%`;

const noop = () => {};

// The Doctor's best moves across every deck, as the same big swap panels the
// Insights tab uses, with the deck each one is for and what it costs. Applying
// one (or keeping the card) re-reads the page, which is what brings the next
// best move up. The list is short on purpose: a few things the Doctor stands
// behind, not an inbox.
export default function DoctorsOrders({
  hub,
  onChanged,
}: {
  hub: Hub;
  // Called after an order was applied or dismissed, to reload the page's data.
  onChanged: () => Promise<void>;
}) {
  const row = useRowAction();

  async function apply(run: () => Promise<unknown>) {
    await run();
    await onChanged();
  }

  return (
    <section>
      <div style={{ fontSize: 15, color: "var(--text-muted)", margin: "4px 0 22px", maxWidth: 700, lineHeight: 1.5 }}>
        Entirely optional — your decks are yours. These are the swaps the Doctor would try first, each with its reasons.
        Make one, or keep a card and it won't be suggested for cutting again.
      </div>

      {hub.orders.length === 0 && (
        <div
          style={{
            background: "var(--surface)",
            border: "1px dashed var(--border)",
            borderRadius: 16,
            padding: "28px 24px",
            marginBottom: 28,
          }}
        >
          <div style={{ fontSize: 19, fontWeight: 600 }}>No orders yet</div>
          <div style={{ fontSize: 15, color: "var(--text-muted)", marginTop: 6, lineHeight: 1.5 }}>
            The Doctor reviews a deck the first time you open its Insights tab.
          </div>
        </div>
      )}

      {hub.orders.map((o, i) => {
        const key = `${o.deck_id}:${o.cut}`;
        return (
          <SwapRow
            key={key}
            index={i + 1}
            total={hub.orders.length}
            label={
              <>
                IDEA {i + 1} OF {hub.orders.length} ·{" "}
                <Link to={`/decks/${o.deck_id}`} style={{ color: "var(--accent)" }}>
                  {o.deck_title.toUpperCase()}
                </Link>
              </>
            }
            tag={o.source === "doctor" ? "THE DOCTOR'S OWN PICK" : undefined}
            cut={{ name: o.cut, id: o.cut_id, stat: o.cut_inclusion !== null ? `${pct(o.cut_inclusion)} of decks` : undefined }}
            add={{
              name: o.add,
              id: o.add_id,
              stat: [
                o.add_inclusion !== null && `${pct(o.add_inclusion)} of decks`,
                o.add_synergy !== null && o.add_synergy >= 0.1 && `+${Math.round(o.add_synergy * 100)}% synergy`,
                o.price_usd && `$${o.price_usd}`,
              ]
                .filter(Boolean)
                .join(" · "),
            }}
            reasonCut={o.reason_cut}
            reasonAdd={o.reason_add}
            owned={false}
            busy={row.pending === key}
            error={row.errors[key]}
            onSwap={() => row.run(key, () => apply(() => swapCards(o.deck_id, o.cut, o.add)))}
            onKeep={() => row.run(key, () => apply(() => keepCard(o.deck_id, o.cut)))}
            onHoverCard={noop}
          />
        );
      })}

      <Footer more={hub.more_swaps} />
    </section>
  );
}

function Footer({ more }: { more: number }) {
  if (more === 0) return null;
  return (
    <div style={{ fontSize: 14, color: "var(--text-muted)", lineHeight: 1.6, marginBottom: 8 }}>
      {more} more swap{more === 1 ? " is" : "s are"} on your decks' Insights tabs.
    </div>
  );
}
