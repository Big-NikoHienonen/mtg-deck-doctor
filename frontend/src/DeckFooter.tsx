import { typeCounts, type DeckRow } from "./deckListModel";

// "Sorceries" → "sorcery", for a count of one.
const singular = (type: string) => (type === "Sorceries" ? "sorcery" : type.slice(0, -1).toLowerCase());

// The bar along the bottom of the page: how many cards, what they cost, and how many of each type.
export default function DeckFooter({ rows, cardCount, price, costToComplete }: { rows: DeckRow[]; cardCount: number; price: number; costToComplete: number }) {
  const commanderType = rows.find((r) => r.isCommander)?.type;
  return (
    <div className="dv-footer" role="contentinfo">
      <div className="dv-total">
        <strong>{cardCount} main deck</strong>
        {costToComplete > 0 && costToComplete < price && <span>${costToComplete.toFixed(2)} to complete</span>}
      </div>
      <span className="dv-format">
        <i className="ms ms-commander" aria-hidden /> Commander
      </span>
      <span className="dv-worth">${price.toFixed(2)}</span>
      <div className="dv-types">
        {typeCounts(rows).map((t) => {
          const tip = `${t.count} ${t.count === 1 ? singular(t.type) : t.type.toLowerCase()}${t.type === commanderType ? ", including your commander" : ""}`;
          return (
            <span key={t.type} className="dv-type" tabIndex={0} data-tip={tip} aria-label={tip}>
              {t.icon && <i className={`ms ms-${t.icon}`} aria-hidden />}
              {t.count}
            </span>
          );
        })}
      </div>
    </div>
  );
}
