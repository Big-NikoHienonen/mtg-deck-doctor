import type { ReactNode } from "react";
import CardImage from "./CardImage";
import { buttonStyle, eyebrowStyle } from "./styles";
import { CARD_MAX_WIDTH, TONES } from "./swapStyle";

type Side = {
  name: string;
  id?: string | null;
  // Short fact shown under the name, e.g. "46% of decks".
  stat?: ReactNode;
};

// One side of a swap: the card at full size in a red (cut) or green (add)
// frame, with a label pinned to its top edge.
function CardFrame({ side, tone, onHover }: { side: Side; tone: keyof typeof TONES; onHover: () => void }) {
  const { color, glow, label } = TONES[tone];
  return (
    <div style={{ position: "relative", width: "100%", maxWidth: CARD_MAX_WIDTH }} onMouseEnter={onHover}>
      <CardImage
        cardId={side.id}
        version="normal"
        alt={side.name}
        title={side.name}
        loading="lazy"
        style={{
          width: "100%",
          display: "block",
          borderRadius: 16,
          border: `4px solid ${color}`,
          boxShadow: `0 8px 20px ${glow}`,
        }}
      />
      <span
        style={{
          position: "absolute",
          top: -12,
          left: "50%",
          transform: "translateX(-50%)",
          background: color,
          color: "#fff",
          fontSize: 12,
          fontWeight: 600,
          letterSpacing: "0.12em",
          padding: "3px 16px",
          borderRadius: 999,
        }}
      >
        {label}
      </span>
    </div>
  );
}

function Caption({ side, extra }: { side: Side; extra?: ReactNode }) {
  return (
    <div style={{ width: "100%", maxWidth: CARD_MAX_WIDTH, textAlign: "center", minWidth: 0 }}>
      <div style={{ fontSize: 17, fontWeight: 600, lineHeight: 1.25 }}>{side.name}</div>
      <div style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 2, minHeight: 18 }}>
        {side.stat}
        {extra}
      </div>
    </div>
  );
}

// The reason for one side of the swap, set under its own card and marked with
// a bar in the card's colour, so there is never any doubt what it explains.
function Reason({ tone, children }: { tone: keyof typeof TONES; children: ReactNode }) {
  const { color } = TONES[tone];
  return (
    <div style={{ width: "100%", borderLeft: `4px solid ${color}`, paddingLeft: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 600, letterSpacing: "0.1em", color, marginBottom: 4 }}>
        {tone === "cut" ? "WHY CUT IT" : "WHY ADD IT"}
      </div>
      <div style={{ fontSize: 15, lineHeight: 1.55 }}>{children}</div>
    </div>
  );
}

// One recommended swap, as its own panel — the thing the Insights page is
// about. The card to cut on the left in a red frame, the card to put in its
// place on the right in a green one; under each, the Doctor's reason for it,
// then the action that belongs to it (keep the one, swap in the other). A swap
// is only ever shown with both reasons.
export default function SwapRow({
  index,
  total,
  label,
  tag,
  cut,
  add,
  reasonCut,
  reasonAdd,
  owned,
  busy,
  error,
  onSwap,
  onKeep,
  onHoverCard,
}: {
  index: number;
  total: number;
  // Replaces the default "SWAP n OF m" heading — the landing page uses it to
  // say which deck the swap is for.
  label?: ReactNode;
  // Set when the Doctor chose this swap itself rather than the statistics.
  tag?: string;
  cut: Side;
  add: Side;
  reasonCut: ReactNode;
  reasonAdd: ReactNode;
  owned: boolean;
  busy: boolean;
  error?: string;
  onSwap: () => void;
  onKeep: () => void;
  onHoverCard: (name: string, id?: string | null) => void;
}) {
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
      <div style={{ ...eyebrowStyle, fontSize: 12, marginBottom: 20 }}>
        {label ?? `SWAP ${index} OF ${total}`}
        {tag && <span style={{ color: "var(--accent-gold)" }}> · {tag}</span>}
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
        <CardFrame side={cut} tone="cut" onHover={() => onHoverCard(cut.name, cut.id)} />
        <div
          aria-hidden
          style={{ alignSelf: "center", fontSize: 40, lineHeight: 1, color: "var(--text-muted)", paddingBottom: 4 }}
        >
          →
        </div>
        <CardFrame side={add} tone="add" onHover={() => onHoverCard(add.name, add.id)} />

        <Caption side={cut} />
        <div />
        <Caption
          side={add}
          extra={owned && <span style={{ color: "var(--positive)", fontWeight: 600 }}> · ✓ OWNED</span>}
        />

        <Reason tone="cut">{reasonCut}</Reason>
        <div />
        <Reason tone="add">{reasonAdd}</Reason>

        <button
          onClick={onKeep}
          disabled={busy}
          className="btn"
          title="Never suggest cutting this card"
          style={{ ...buttonStyle, width: "100%", maxWidth: CARD_MAX_WIDTH }}
        >
          Keep this card
        </button>
        <div />
        <button
          onClick={onSwap}
          disabled={busy}
          className="btn btn-positive"
          style={{ ...buttonStyle, width: "100%", maxWidth: CARD_MAX_WIDTH, fontWeight: 600 }}
        >
          {busy ? "Swapping…" : "Make this swap"}
        </button>
      </div>
      {error && <div style={{ fontSize: 13, color: "var(--danger)", marginTop: 12 }}>{error}</div>}
    </div>
  );
}
