import { scryfallImageUrlById, type ImageVersion, type Printing } from "./api";

// Which specific printing's art (and price) to show for a card is a
// per-viewer display preference, not deck data — it doesn't affect
// legality or validation, which is keyed on card name only. Persisted in
// localStorage per deck, same reasoning as the images/list view toggle,
// and deliberately never sent to the backend.
export type SelectedPrinting = {
  id: string;
  setName: string;
  priceUsd: string | null;
  // The foil copy of this printing: its price, the finishes it comes in
  // ("nonfoil", "foil", "etched"), and whether the viewer uses it. Printings
  // saved before foil existed lack the first two; the card modal looks them up
  // the first time foil is asked for.
  priceUsdFoil?: string | null;
  finishes?: string[];
  foil?: boolean;
};

// Whether the printing can be used as a foil. "unknown" until its finishes
// are known; "only" for a printing that doesn't come any other way.
export type FoilSupport = "unknown" | "none" | "optional" | "only";

export function foilSupport(printing: SelectedPrinting | undefined): FoilSupport {
  const finishes = printing?.finishes;
  if (!finishes) return "unknown";
  if (!finishes.some((f) => f === "foil" || f === "etched")) return "none";
  return finishes.includes("nonfoil") ? "optional" : "only";
}

// A picked printing, as the viewer will keep it. `foil` is what they were using
// before: it carries over to a printing that comes in foil, and a printing that
// only comes in foil is always used as one.
export function selectPrinting(printing: Printing, foil = false): SelectedPrinting {
  const picked: SelectedPrinting = {
    id: printing.id,
    setName: printing.setName,
    priceUsd: printing.priceUsd,
    priceUsdFoil: printing.priceUsdFoil,
    finishes: printing.finishes,
  };
  const support = foilSupport(picked);
  return { ...picked, foil: support === "only" || (foil && support === "optional") };
}

// What one copy costs: the picked printing's price, in its foil form if that is
// what's used; the card's own price if no printing is picked or it has none.
export function priceUsdOf(printing: SelectedPrinting | undefined, fallback: string | null | undefined): string | null {
  const price = printing && (printing.foil ? (printing.priceUsdFoil ?? printing.priceUsd) : printing.priceUsd);
  return price ?? fallback ?? null;
}

function storageKey(deckId: string): string {
  return `mtg-deck-doctor:printings:${deckId}`;
}

export function loadSelectedPrintings(deckId: string): Record<string, SelectedPrinting> {
  try {
    const raw = localStorage.getItem(storageKey(deckId));
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

export function saveSelectedPrinting(
  deckId: string,
  cardName: string,
  printing: SelectedPrinting,
): Record<string, SelectedPrinting> {
  const all = loadSelectedPrintings(deckId);
  all[cardName] = printing;
  try {
    localStorage.setItem(storageKey(deckId), JSON.stringify(all));
  } catch {
    // per-viewer convenience only — fine if it's unavailable
  }
  return all;
}

export function clearSelectedPrinting(deckId: string, cardName: string): Record<string, SelectedPrinting> {
  const all = loadSelectedPrintings(deckId);
  delete all[cardName];
  try {
    localStorage.setItem(storageKey(deckId), JSON.stringify(all));
  } catch {
    // per-viewer convenience only
  }
  return all;
}

// Whether a printing matches what was typed in the picker's search box. Every
// word has to match somewhere in the set name, set code, collector number, year,
// or treatments, in any order: "commander legends", "2x2 borderless", "2019".
// A word that starts with "#" is a collector number and has to match the start
// of it, so "#47" finds "472" while you type. A bare "#" matches everything.
export function matchesPrinting(printing: Printing, query: string): boolean {
  const words = query.toLowerCase().split(/\s+/).filter((w) => w && w !== "#");
  if (words.length === 0) return true;
  const text = [printing.setName, printing.set, printing.collectorNumber, printing.releasedAt?.slice(0, 4), ...printing.treatments]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  const number = printing.collectorNumber?.toLowerCase();
  return words.every((w) => (w.startsWith("#") ? Boolean(number?.startsWith(w.slice(1))) : text.includes(w)));
}

// A printing the viewer picked wins; otherwise the card's own
// (default-printing) Scryfall id. null while neither is known yet — callers
// show a placeholder rather than a request that can't succeed.
export function cardImageUrl(
  cardId: string | null | undefined,
  printing: SelectedPrinting | undefined,
  version: ImageVersion = "small",
): string | null {
  const id = printing?.id ?? cardId;
  return id ? scryfallImageUrlById(id, version) : null;
}
