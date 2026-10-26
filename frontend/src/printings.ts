import { scryfallImageUrlById, type ImageVersion } from "./api";

// Which specific printing's art (and price) to show for a card is a
// per-viewer display preference, not deck data — it doesn't affect
// legality or validation, which is keyed on card name only. Persisted in
// localStorage per deck, same reasoning as the images/list view toggle,
// and deliberately never sent to the backend.
export type SelectedPrinting = { id: string; setName: string; priceUsd: string | null };

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
