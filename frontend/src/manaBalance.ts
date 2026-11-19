import type { DeckRow } from "./deckListModel";

// Manalytics' comparison of what a deck's costs ask for with what its cards can make. For each color it has the
// colored mana symbols in the costs (the demand) and the cards that tap for the color (the supply), and says
// whether the supply falls short of the demand. A rule of thumb, not a calculation of the odds: it compares how
// the two split between the colors, and doesn't know how many lands the deck runs or how early a card is cast.

const COLORS = ["W", "U", "B", "R", "G"];

// A color is short when its share of the sources is this far below its share of the symbols (0.1 is ten
// percentage points: 40% of the symbols but 30% of the sources).
export const SHORT_BY = 0.1;
// Shares are fractions, and 0.5 - 0.4 is 0.09999999999999998, so "exactly ten points" needs a little room.
const EPSILON = 1e-9;

export type ColorBalance = {
  color: string;
  symbols: number;
  // This color's part of all the colored symbols in the deck, 0 to 1.
  symbolShare: number;
  // Cards that tap for this color, counting copies: lands, and every other permanent.
  lands: number;
  other: number;
  sources: number;
  // This color's part of all the color-making cards counted, 0 to 1. A dual land counts for both its colors.
  sourceShare: number;
  // `sourceShare` split by where the sources come from; the two add up to it.
  landShare: number;
  otherShare: number;
  // "none": the deck needs the color and has nothing that makes it. "short": see SHORT_BY. Otherwise "ok".
  verdict: "ok" | "short" | "none";
};

export type ManaBalance = {
  colors: ColorBalance[];
  // Cards that tap for colorless mana, counting copies. They fill generic costs, so no color is held against them.
  colorlessSources: number;
  // Cards whose mana production isn't known yet. While there are any, the sources are incomplete and no verdict
  // should be believed.
  unknown: number;
  totalSymbols: number;
};

// `symbols` is the count of colored symbols in costs per color (deckStats' `colors`). `identity` is the commander's
// colors: a card that taps for "any color" is counted for these only, as the deck can't have a cost outside them.
export function manaBalance(symbols: { color: string; symbols: number }[], rows: DeckRow[], identity: string[]): ManaBalance {
  const demand = new Map(symbols.map((s) => [s.color, s.symbols]));
  const lands = new Map(COLORS.map((c) => [c, 0]));
  const other = new Map(COLORS.map((c) => [c, 0]));
  let colorlessSources = 0;
  let unknown = 0;

  for (const r of rows) {
    // A spell is cast, not kept: a ritual makes mana once, so it is no source.
    if (r.type === "Instants" || r.type === "Sorceries") continue;
    const produced = r.info?.producedMana;
    if (produced === undefined) {
      unknown += r.count;
      continue;
    }
    const into = r.type === "Lands" ? lands : other;
    for (const c of COLORS) {
      if (produced.includes(c) && identity.includes(c)) into.set(c, into.get(c)! + r.count);
    }
    if (produced.includes("C")) colorlessSources += r.count;
  }

  // The colors the deck is in, or has a symbol for.
  const shown = COLORS.filter((c) => identity.includes(c) || (demand.get(c) ?? 0) > 0);
  const totalSymbols = shown.reduce((n, c) => n + (demand.get(c) ?? 0), 0);
  const totalSources = shown.reduce((n, c) => n + lands.get(c)! + other.get(c)!, 0);

  const colors = shown.map((color): ColorBalance => {
    const symbolCount = demand.get(color) ?? 0;
    const sources = lands.get(color)! + other.get(color)!;
    const symbolShare = totalSymbols ? symbolCount / totalSymbols : 0;
    const sourceShare = totalSources ? sources / totalSources : 0;
    const verdict = symbolCount > 0 && sources === 0 ? "none" : symbolShare - sourceShare >= SHORT_BY - EPSILON ? "short" : "ok";
    const landShare = totalSources ? lands.get(color)! / totalSources : 0;
    const otherShare = totalSources ? other.get(color)! / totalSources : 0;
    return { color, symbols: symbolCount, symbolShare, lands: lands.get(color)!, other: other.get(color)!, sources, sourceShare, landShare, otherShare, verdict };
  });
  return { colors, colorlessSources, unknown, totalSymbols };
}
