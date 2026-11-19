import type { DeckRow, DeckStats as Stats } from "./deckListModel";
import { manaBalance, type ManaBalance } from "./manaBalance";

const COLOR_NAMES: Record<string, string> = { W: "White", U: "Blue", B: "Black", R: "Red", G: "Green", C: "Colorless" };

const round = (n: number) => (Math.round(n * 100) / 100).toString();
const percent = (share: number) => `${Math.round(share * 100)}%`;
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

// Under the list: the mana curve, the averages, how the colored symbols in the costs split, and how that split
// compares with the cards that make each color. `rows` and `identity` (the commander's colors) are for the
// comparison.
export default function DeckStats({ stats, rows, identity }: { stats: Stats; rows: DeckRow[]; identity: string[] }) {
  const tallest = Math.max(1, ...stats.curve.map((c) => c.permanents + c.spells));
  const balance = manaBalance(stats.colors, rows, identity);
  return (
    <section className="dv-stats" aria-label="Manalytics">
      <h2>Manalytics</h2>
      <h3>Mana curve</h3>
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
      <div className="dv-block">
        <h3>Colored symbols</h3>
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
      </div>
      {balance.colors.length > 0 && <SymbolsAndSources balance={balance} />}
    </section>
  );
}

// How the colored symbols in the costs split between the colors, next to how the cards that make each color
// split. Where a color's sources are a smaller part of the mana than its symbols are of the costs, it is short.
function SymbolsAndSources({ balance }: { balance: ManaBalance }) {
  const complete = balance.unknown === 0;
  // The longest bar fills its track, so the differences are easy to see; the numbers beside the bars are the real shares.
  const scale = Math.max(0.01, ...balance.colors.flatMap((c) => [c.symbolShare, c.sourceShare]));
  const wide = (share: number) => `${(share / scale) * 100}%`;
  const problems = balance.colors.filter((c) => c.verdict !== "ok");

  return (
    <div className="dv-block dv-balance">
      <h3>Symbols and sources</h3>
      <div className="dv-balance-note" role="status">
        {!complete ? (
          <p>Mana production isn't known for {plural(balance.unknown, "card", "cards")} yet, so the sources are incomplete.</p>
        ) : problems.length > 0 ? (
          problems.map((c) =>
            c.verdict === "none" ? (
              <p key={c.color}>
                No <strong>{COLOR_NAMES[c.color]}</strong> sources, but {plural(c.symbols, "symbol needs", "symbols need")} it.
              </p>
            ) : (
              <p key={c.color}>
                Short on <strong>{COLOR_NAMES[c.color]}</strong>: {percent(c.symbolShare)} of your symbols but {percent(c.sourceShare)} of your sources.
              </p>
            ),
          )
        ) : balance.totalSymbols > 0 ? (
          <p>Your sources split the way your symbols do.</p>
        ) : null}
      </div>

      <div className="dv-bal">
        {balance.colors.map((c) => (
          <div
            key={c.color}
            className="dv-bal-row"
            data-verdict={complete ? c.verdict : "ok"}
            role="group"
            aria-label={`${COLOR_NAMES[c.color]}: ${plural(c.symbols, "symbol", "symbols")}, ${plural(c.sources, "source", "sources")}`}
          >
            <i className={`ms ms-${c.color.toLowerCase()} ms-cost ms-shadow`} aria-hidden />
            <div className="dv-bal-bars">
              <div className="dv-bal-bar" title={`${COLOR_NAMES[c.color]}: ${plural(c.symbols, "symbol", "symbols")} in costs, ${percent(c.symbolShare)} of the colored symbols`}>
                <span>Symbols</span>
                <div className="dv-bal-track">
                  <div className="dv-bal-fill dv-bal-symbols" style={{ width: wide(c.symbolShare) }} />
                </div>
                <span className="dv-bal-n">
                  {percent(c.symbolShare)} · {c.symbols}
                </span>
              </div>
              <div className="dv-bal-bar" title={`${COLOR_NAMES[c.color]}: ${plural(c.sources, "source", "sources")}, ${plural(c.lands, "land", "lands")} and ${c.other} other`}>
                <span>Sources</span>
                <div className="dv-bal-track">
                  <div className="dv-bal-fill dv-bal-lands" style={{ width: wide(c.landShare) }} />
                  <div className="dv-bal-fill dv-bal-other" style={{ width: wide(c.otherShare) }} />
                </div>
                <span className="dv-bal-n">
                  {percent(c.sourceShare)} · {c.sources}
                </span>
              </div>
            </div>
            <span className="dv-bal-flag">{complete ? (c.verdict === "none" ? "No sources" : c.verdict === "short" ? "Short" : "") : ""}</span>
          </div>
        ))}
      </div>

      <div className="dv-legend">
        <span>
          <i style={{ background: "var(--accent)" }} />
          Symbols in costs
        </span>
        <span>
          <i style={{ background: "var(--accent-gold)" }} />
          Lands
        </span>
        <span>
          <i style={{ background: "color-mix(in srgb, var(--accent-gold) 45%, transparent)" }} />
          Other sources
        </span>
      </div>
      <p className="dv-balance-foot">
        Each bar shows the color's share, then how many. A source is a land or other permanent that taps for the color, counted by copy and limited to your commander's colors. A card that makes two colors counts for both.
        {balance.colorlessSources > 0 && ` ${plural(balance.colorlessSources, "card makes", "cards make")} colorless mana.`} Fetch lands and cards that make Treasures aren't counted yet.
      </p>
    </div>
  );
}
