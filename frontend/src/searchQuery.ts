import type { Deck, SearchCard } from "./api";
import { BASIC_LAND_NAMES } from "./basicLands";

export type ColorMode = "exact" | "at-least" | "at-most";

export type SearchFilters = {
  name: string;
  colors: string[];
  colorMode: ColorMode;
  identity: string[];
  identityMode: ColorMode;
  cmcMin: string;
  cmcMax: string;
  subtype: string;
  oracleText: string;
  set: string;
  includeAlchemy: boolean;
};

export const EMPTY_FILTERS: SearchFilters = {
  name: "",
  colors: [],
  colorMode: "at-least",
  identity: [],
  identityMode: "at-most",
  cmcMin: "",
  cmcMax: "",
  subtype: "",
  oracleText: "",
  set: "",
  includeAlchemy: false,
};

export function hasAnyFilter(f: SearchFilters): boolean {
  return Boolean(
    f.name.trim() ||
      f.colors.length ||
      f.identity.length ||
      f.cmcMin ||
      f.cmcMax ||
      f.subtype.trim() ||
      f.oracleText.trim() ||
      f.set,
  );
}

function quoteIfNeeded(term: string): string {
  return term.includes(" ") ? `"${term}"` : term;
}

const MODE_OPERATOR: Record<ColorMode, string> = {
  exact: "=",
  "at-least": ">=",
  "at-most": "<=",
};

// Built and verified piece by piece against Scryfall's real search API
// (see api.ts's scryfallSearchCards comment) rather than guessed from
// memory of the syntax guide.
export function buildScryfallQuery(f: SearchFilters): string {
  const parts: string[] = [];
  if (f.name.trim()) parts.push(quoteIfNeeded(f.name.trim()));
  if (f.colors.length) parts.push(`c${MODE_OPERATOR[f.colorMode]}${f.colors.join("")}`);
  if (f.identity.length) parts.push(`id${MODE_OPERATOR[f.identityMode]}${f.identity.join("")}`);
  if (f.cmcMin) parts.push(`cmc>=${f.cmcMin}`);
  if (f.cmcMax) parts.push(`cmc<=${f.cmcMax}`);
  if (f.subtype.trim()) parts.push(`t:${quoteIfNeeded(f.subtype.trim())}`);
  if (f.oracleText.trim()) parts.push(`o:${quoteIfNeeded(f.oracleText.trim())}`);
  if (f.set) parts.push(`set:${f.set}`);
  // Alchemy (Arena-only new designs + "A-" rebalanced reprints) is off by
  // default — confirmed via curl that Scryfall's set-type operator covers
  // it (-st:alchemy dropped a dragon search from 444 to 429 results).
  if (!f.includeAlchemy) parts.push("-st:alchemy");
  return parts.join(" ");
}

// Client-side convenience filter, not a second copy of the real rules —
// the backend's add_card validator is still the actual gate at add time.
// This just hides results that would obviously be rejected (wrong color
// identity, already-in-deck singleton) so browsing stays useful once a
// target deck is picked. Deliberately doesn't check the banned list (not
// exposed by any endpoint this app calls) — a banned card can still slip
// through this filter and will get caught, correctly, when Add is clicked.
export function isAddableToDeck(card: SearchCard, deck: Deck): boolean {
  const withinIdentity = card.colorIdentity.every((c) => deck.commander_color_identity.includes(c));
  if (!withinIdentity) return false;
  const alreadyIn = deck.cards.includes(card.name);
  if (alreadyIn && !BASIC_LAND_NAMES.has(card.name)) return false;
  return true;
}
