import type { ReactNode } from "react";
import type { WizardPlan as Plan } from "./api";
import CardImage from "./CardImage";
import { buttonStyle } from "./styles";

const money = (n: number) => `$${n.toLocaleString("en", { maximumFractionDigits: 0 })}`;

const CATEGORY_NAMES: Record<string, [string, string]> = {
  Creature: ["creature", "creatures"],
  Planeswalker: ["planeswalker", "planeswalkers"],
  Instant: ["instant", "instants"],
  Sorcery: ["sorcery", "sorceries"],
  Artifact: ["artifact", "artifacts"],
  Enchantment: ["enchantment", "enchantments"],
  Land: ["land", "lands"],
  Other: ["other card", "other cards"],
};
const categoryName = (category: string, count: number) => (CATEGORY_NAMES[category] ?? [category, category])[count === 1 ? 0 : 1];

function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "good" | "warn" }) {
  return (
    <div style={{ background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 10, padding: "10px 14px", minWidth: 0 }}>
      <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.1em", color: "var(--accent)" }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 600, marginTop: 2, color: tone === "good" ? "var(--positive)" : tone === "warn" ? "var(--accent-gold)" : undefined }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2, lineHeight: 1.4 }}>{sub}</div>}
    </div>
  );
}

// The starting list the helper would build for this commander, power level and
// budget — what it costs, what it's made of, what was changed to fit — with the
// button that builds it. Nothing is created until that button is pressed.
export default function WizardPlan({
  plan,
  building,
  buildError,
  onBuild,
  note,
}: {
  plan: Plan;
  building: boolean;
  buildError: string | null;
  onBuild: () => void;
  // Shown under the price and counts: what the Doctor did with the list, when it built it.
  note?: ReactNode;
}) {
  const byCategory = new Map<string, Plan["cards"]>();
  for (const card of plan.cards) byCategory.set(card.category, [...(byCategory.get(card.category) ?? []), card]);
  const order = ["Creature", "Planeswalker", "Instant", "Sorcery", "Artifact", "Enchantment", "Land", "Other"];
  const categories = [...byCategory.keys()].sort((a, b) => order.indexOf(a) - order.indexOf(b));
  const fits = plan.budget === null || plan.budget_reached;
  const spendRows = [
    { label: "Commander", price: plan.commander.price_usd, note: "" },
    ...plan.spend.map((s) => ({
      label: s.label,
      price: s.price,
      note: s.cap !== null ? `limit ${money(s.cap)}` : s.invest ? "spending more" : "",
    })),
  ];
  const biggest = Math.max(1, ...spendRows.map((r) => r.price));

  return (
    <div
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 16,
        padding: 22,
        boxShadow: "0 3px 14px rgba(43, 32, 24, 0.1)",
      }}
    >
      <div style={{ display: "flex", gap: 18, alignItems: "flex-start", flexWrap: "wrap" }}>
        <CardImage
          cardId={plan.commander.id}
          version="normal"
          alt={plan.commander.name}
          style={{ width: 170, flexShrink: 0, borderRadius: 11, boxShadow: "0 8px 20px rgba(43, 32, 24, 0.3)" }}
        />
        <div style={{ flex: 1, minWidth: 260 }}>
          <div style={{ fontSize: 24, fontWeight: 600, lineHeight: 1.2 }}>{plan.commander.name}</div>
          <div style={{ fontSize: 14, color: "var(--text-muted)", marginTop: 4, lineHeight: 1.5 }}>
            A starting list of {plan.card_count} cards, from EDHREC's average list for {plan.variant}
            {plan.swaps.length > 0 && ", with some cards swapped to fit"}. You can change anything once it's built.
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10, marginTop: 14 }}>
            <Stat
              label="PRICE"
              value={money(plan.total_price)}
              tone={plan.budget === null ? undefined : fits ? "good" : "warn"}
              sub={
                (plan.budget === null ? "No budget set" : fits ? `Within your ${money(plan.budget)} budget` : `Over your ${money(plan.budget)} budget`) +
                (plan.commander.price_usd >= 1 ? ` · includes the ${money(plan.commander.price_usd)} commander` : "")
              }
            />
            <Stat label="CARDS" value={`${plan.card_count + 1}`} sub="Including the commander" />
            <Stat
              label="GAME CHANGERS"
              value={plan.game_changers.length}
              sub={plan.game_changers.length ? plan.game_changers.join(", ") : "None in this list"}
            />
          </div>
        </div>
      </div>

      {note}

      {plan.notes.length > 0 && (
        <div style={{ marginTop: 16, borderLeft: "4px solid var(--accent-gold)", paddingLeft: 14, fontSize: 14, lineHeight: 1.55 }}>
          {plan.notes.map((n) => (
            <div key={n}>{n}</div>
          ))}
        </div>
      )}

      <div style={{ marginTop: 18 }}>
        <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.1em", color: "var(--accent)", marginBottom: 6 }}>WHERE THE MONEY GOES</div>
        {spendRows.map((row) => (
          <div key={row.label} style={{ display: "grid", gridTemplateColumns: "minmax(96px, 130px) 1fr 64px", alignItems: "center", gap: 10, fontSize: 14, lineHeight: 1.9 }}>
            <span>{row.label}</span>
            <span style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
              <span style={{ height: 8, width: `${Math.max(row.price > 0 ? 1 : 0, (row.price / biggest) * 100)}%`, maxWidth: "70%", background: "var(--accent)", borderRadius: 4, opacity: 0.75 }} />
              {row.note && <span style={{ fontSize: 12, color: "var(--text-muted)", whiteSpace: "nowrap" }}>{row.note}</span>}
            </span>
            <span style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{money(row.price)}</span>
          </div>
        ))}
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 16 }}>
        {categories.map((c) => (
          <span key={c} style={{ fontSize: 13, background: "var(--user-bubble)", borderRadius: 999, padding: "3px 12px" }}>
            {plan.category_counts[c]} {categoryName(c, plan.category_counts[c])}
          </span>
        ))}
      </div>

      {plan.swaps.length > 0 && (
        <details style={{ marginTop: 14 }}>
          <summary style={{ cursor: "pointer", fontSize: 14, color: "var(--accent)" }}>
            What changed ({plan.swaps.length} swaps)
          </summary>
          <div style={{ marginTop: 8, fontSize: 14, lineHeight: 1.7 }}>
            {plan.swaps.map((s, i) => (
              <div key={i}>
                {s.out} <span style={{ color: "var(--text-muted)" }}>→</span> {s.in}{" "}
                <span style={{ color: "var(--text-muted)", fontSize: 12 }}>
                  {s.saved >= 0.5 ? `saves ${money(s.saved)}` : s.saved <= -0.5 ? `costs ${money(-s.saved)} more` : "about the same price"}
                </span>
              </div>
            ))}
          </div>
        </details>
      )}

      <details style={{ marginTop: 10 }}>
        <summary style={{ cursor: "pointer", fontSize: 14, color: "var(--accent)" }}>See the full list</summary>
        <div style={{ columnWidth: 230, columnGap: 24, marginTop: 10 }}>
          {categories.map((c) => (
            <div key={c} style={{ breakInside: "avoid", marginBottom: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.1em", color: "var(--accent)", marginBottom: 4 }}>
                {c.toUpperCase()} ({plan.category_counts[c]})
              </div>
              {byCategory.get(c)!.map((card) => (
                <div key={card.name} style={{ display: "flex", justifyContent: "space-between", gap: 8, fontSize: 13, lineHeight: 1.6 }}>
                  <span>
                    {card.quantity > 1 && `${card.quantity}× `}
                    {card.name}
                  </span>
                  <span style={{ color: "var(--text-muted)" }}>{card.price_usd >= 1 ? money(card.price_usd) : ""}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      </details>

      <div style={{ marginTop: 20, display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
        <button onClick={onBuild} disabled={building} className="btn btn-positive" style={{ ...buttonStyle, fontWeight: 600, fontSize: 16, padding: "10px 22px" }}>
          {building ? "Building your deck…" : "Build this deck"}
        </button>
        {buildError && <span style={{ fontSize: 14, color: "var(--danger)" }}>{buildError}</span>}
      </div>
    </div>
  );
}
