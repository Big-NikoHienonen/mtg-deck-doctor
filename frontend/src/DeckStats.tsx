import type { DeckStats as Stats } from "./deckListModel";

const COLOR_NAMES: Record<string, string> = { W: "White", U: "Blue", B: "Black", R: "Red", G: "Green", C: "Colorless" };

const round = (n: number) => (Math.round(n * 100) / 100).toString();

// Under the list: the mana curve, the averages, and how the colored symbols in the costs split.
export default function DeckStats({ stats }: { stats: Stats }) {
  const tallest = Math.max(1, ...stats.curve.map((c) => c.permanents + c.spells));
  return (
    <section className="dv-stats" aria-label="Deck statistics">
      <h2>Mana curve</h2>
      <div className="dv-stats-row">
        <div className="dv-curve">
          <div className="dv-curve-bars">
            {stats.curve.map((c) => (
              <div key={c.manaValue} className="dv-curve-col" title={`${c.permanents} permanents, ${c.spells} spells at mana value ${c.manaValue}${c.manaValue === 7 ? "+" : ""}`}>
                <div className="dv-bar-spells" style={{ height: `${(c.spells / tallest) * 100}%` }} />
                <div className="dv-bar-permanents" style={{ height: `${(c.permanents / tallest) * 100}%` }} />
              </div>
            ))}
          </div>
          <div className="dv-curve-axis">
            {stats.curve.map((c) => (
              <span key={c.manaValue}>{c.manaValue === 7 ? "7+" : c.manaValue}</span>
            ))}
          </div>
          <div className="dv-legend">
            <span>
              <i style={{ background: "var(--accent)" }} />
              Permanents
            </span>
            <span>
              <i style={{ background: "var(--dv-spells)" }} />
              Spells
            </span>
          </div>
        </div>
        <p className="dv-averages">
          The average mana value of your main deck is <strong>{stats.average.withLands.toFixed(2)}</strong> with lands and <strong>{stats.average.withoutLands.toFixed(2)}</strong> without lands. The median mana value is <strong>{round(stats.median.withLands)}</strong> with lands and{" "}
          <strong>{round(stats.median.withoutLands)}</strong> without lands. The deck's total mana value is <strong>{stats.totalManaValue}</strong>.
          {stats.unknown > 0 && ` ${stats.unknown} ${stats.unknown === 1 ? "card has" : "cards have"} no mana value yet and ${stats.unknown === 1 ? "is" : "are"} left out.`}
        </p>
      </div>
      <div className="dv-colors">
        {stats.colors.map((c) => (
          <div key={c.color} data-zero={c.symbols === 0} title={`${COLOR_NAMES[c.color]}: ${c.symbols} symbols`}>
            <i className={`ms ms-${c.color.toLowerCase()} ms-cost ms-shadow`} aria-hidden />
            <div className="dv-share">{Math.round(c.share * 100)}%</div>
            <div className="dv-symbols">
              {c.symbols} {c.symbols === 1 ? "symbol" : "symbols"}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
