import { manaSymbols } from "./deckListModel";

// A mana cost as the round symbols on the card, drawn with the mana-font icons.
export default function ManaCost({ cost }: { cost: string | null | undefined }) {
  const symbols = manaSymbols(cost);
  if (symbols.length === 0) return null;
  return (
    <span className="dv-cost" aria-label={cost ?? undefined} title={cost ?? undefined}>
      {symbols.map((s, i) => (
        <i key={i} className={`ms ms-cost ms-shadow ms-${s}`} />
      ))}
    </span>
  );
}
