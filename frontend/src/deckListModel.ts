import type { CardInfo } from "./api";
import { categoryFor } from "./cardCategories";

// What the deck page's list shows and how: one row per card, grouped and sorted by the
// viewer's choice. Pure functions, so the page and the footer bar can share them.

export type ViewMode = "text" | "condensed" | "grid" | "stacks";
export type GroupBy = "type" | "manaValue" | "color" | "colorIdentity" | "none";
export type SortBy = "name" | "manaValue" | "price" | "color";

export const VIEW_LABELS: Record<ViewMode, string> = {
  text: "Text",
  condensed: "Condensed Text",
  grid: "Visual Grid",
  stacks: "Visual Stacks",
};
export const GROUP_LABELS: Record<GroupBy, string> = {
  type: "Type",
  manaValue: "Mana Value",
  color: "Color",
  colorIdentity: "Color Identity",
  none: "No Grouping",
};
export const SORT_LABELS: Record<SortBy, string> = {
  name: "Name",
  manaValue: "Mana Value",
  price: "Price",
  color: "Color",
};

const COLOR_ORDER = ["W", "U", "B", "R", "G"];
const COLOR_WORDS: Record<string, string> = { W: "White", U: "Blue", B: "Black", R: "Red", G: "Green" };

// The order card types are listed in.
export const TYPE_ORDER = ["Commander", "Planeswalkers", "Creatures", "Sorceries", "Instants", "Artifacts", "Enchantments", "Battles", "Lands", "Other"];
// The mana-font icon (the part after "ms-") for each type group.
const TYPE_ICONS: Record<string, string | null> = {
  Commander: "commander",
  Planeswalkers: "planeswalker",
  Creatures: "creature",
  Sorceries: "sorcery",
  Instants: "instant",
  Artifacts: "artifact",
  Enchantments: "enchantment",
  Battles: "battle",
  Lands: "land",
  Other: null,
};

export type DeckRow = {
  name: string;
  count: number;
  info: CardInfo | undefined;
  // One copy's price in dollars, if known.
  price: number | null;
  // Mana value, if known (a land is 0).
  manaValue: number | null;
  // Colors of the mana cost, in WUBRG order; empty for lands and colorless cards.
  colors: string[];
  // The type group it belongs to, as in the exporter ("Creatures", "Lands"…).
  type: string;
  isCommander: boolean;
};

export type DeckGroup = {
  key: string;
  label: string;
  // mana-font icon name (the part after "ms-"), if the group has one.
  icon: string | null;
  rows: DeckRow[];
  // Cards in the group, counting copies.
  total: number;
};

// The symbols of a mana cost as mana-font names them: "{2}{W/U}{B}" → ["2", "wu", "b"].
export function manaSymbols(manaCost: string | null | undefined): string[] {
  if (!manaCost) return [];
  return [...manaCost.matchAll(/\{([^}]+)\}/g)].map((m) => m[1].toLowerCase().replace("/", ""));
}

// The colors a mana cost needs, in WUBRG order. Hybrid and Phyrexian symbols count for each color they name.
export function costColors(manaCost: string | null | undefined): string[] {
  const letters = new Set(
    [...(manaCost ?? "").matchAll(/\{([^}]+)\}/g)].flatMap((m) => m[1].toUpperCase().split("/")).filter((s) => COLOR_ORDER.includes(s)),
  );
  return COLOR_ORDER.filter((c) => letters.has(c));
}

// The deck as rows: the commander first, then each distinct card with its count.
export function buildRows(
  cards: string[],
  commander: string | null,
  cardInfo: Record<string, CardInfo>,
  priceFor: (name: string) => string | null,
): DeckRow[] {
  const counts = new Map<string, number>();
  for (const name of cards) counts.set(name, (counts.get(name) ?? 0) + 1);
  const row = (name: string, count: number, isCommander: boolean): DeckRow => {
    const info = cardInfo[name];
    const price = priceFor(name);
    const type = categoryFor(info?.typeLine ?? undefined);
    const colors = info?.manaCost !== undefined ? costColors(info.manaCost) : COLOR_ORDER.filter((c) => info?.colorIdentity?.includes(c));
    return {
      name,
      count,
      info,
      price: price === null ? null : parseFloat(price),
      manaValue: type === "Lands" ? 0 : (info?.cmc ?? null),
      colors,
      type,
      isCommander,
    };
  };
  return [...(commander ? [row(commander, 1, true)] : []), ...[...counts].map(([name, count]) => row(name, count, false))];
}

const byName = (a: DeckRow, b: DeckRow) => a.name.localeCompare(b.name);
// Colors compare by how many, then in WUBRG order: colorless, white, blue … multicolor last.
const colorKey = (r: DeckRow) => `${r.colors.length === 0 ? 0 : r.colors.length === 1 ? 1 : 2}${r.colors.map((c) => COLOR_ORDER.indexOf(c)).join("")}`;

export function sortRows(rows: DeckRow[], sortBy: SortBy): DeckRow[] {
  const compare: Record<SortBy, (a: DeckRow, b: DeckRow) => number> = {
    name: byName,
    manaValue: (a, b) => (a.manaValue ?? 99) - (b.manaValue ?? 99) || byName(a, b),
    // Dearest first; cards without a price last.
    price: (a, b) => (b.price ?? -1) - (a.price ?? -1) || byName(a, b),
    color: (a, b) => colorKey(a).localeCompare(colorKey(b)) || byName(a, b),
  };
  return [...rows].sort(compare[sortBy]);
}

function group(key: string, label: string, icon: string | null, rows: DeckRow[]): DeckGroup {
  return { key, label, icon, rows, total: rows.reduce((n, r) => n + r.count, 0) };
}

// The commander is its own group at the top, whatever the grouping.
export function groupRows(rows: DeckRow[], groupBy: GroupBy, sortBy: SortBy): DeckGroup[] {
  const commander = rows.filter((r) => r.isCommander);
  const rest = rows.filter((r) => !r.isCommander);
  const head = commander.length ? [group("Commander", "Commander", TYPE_ICONS.Commander, commander)] : [];
  const sorted = sortRows(rest, sortBy);
  const bucket = (keyOf: (r: DeckRow) => string) => {
    const map = new Map<string, DeckRow[]>();
    for (const r of sorted) map.set(keyOf(r), [...(map.get(keyOf(r)) ?? []), r]);
    return map;
  };

  if (groupBy === "none") return [...head, ...(sorted.length ? [group("all", "Cards", null, sorted)] : [])];

  if (groupBy === "type") {
    const map = bucket((r) => r.type);
    return [...head, ...TYPE_ORDER.filter((t) => map.get(t)).map((t) => group(t, t, TYPE_ICONS[t], map.get(t)!))];
  }

  if (groupBy === "manaValue") {
    const map = bucket((r) => (r.type === "Lands" ? "Lands" : r.manaValue === null ? "?" : String(Math.min(Math.floor(r.manaValue), 7))));
    const keys = [...map.keys()].filter((k) => k !== "Lands" && k !== "?").sort((a, b) => Number(a) - Number(b));
    const label = (k: string) => (k === "7" ? "Mana Value 7+" : `Mana Value ${k}`);
    return [
      ...head,
      ...keys.map((k) => group(k, label(k), null, map.get(k)!)),
      ...(map.get("?") ? [group("?", "Unknown", null, map.get("?")!)] : []),
      ...(map.get("Lands") ? [group("Lands", "Lands", TYPE_ICONS.Lands, map.get("Lands")!)] : []),
    ];
  }

  if (groupBy === "color") {
    const keyOf = (r: DeckRow) => (r.type === "Lands" ? "Lands" : r.colors.length === 0 ? "Colorless" : r.colors.length > 1 ? "Multicolor" : r.colors[0]);
    const map = bucket(keyOf);
    const order = [...COLOR_ORDER, "Multicolor", "Colorless", "Lands"];
    const meta = (k: string): [string, string | null] =>
      k in COLOR_WORDS ? [COLOR_WORDS[k], k.toLowerCase()] : k === "Multicolor" ? [k, "multiple"] : k === "Colorless" ? [k, "c"] : [k, "land"];
    return [...head, ...order.filter((k) => map.get(k)).map((k) => group(k, meta(k)[0], meta(k)[1], map.get(k)!))];
  }

  // Color identity: by the identity itself, fewest colors first.
  const identity = (r: DeckRow) => COLOR_ORDER.filter((c) => r.info?.colorIdentity?.includes(c)).join("");
  const map = bucket(identity);
  const label = (k: string) => (k === "" ? "Colorless" : k.split("").map((c) => COLOR_WORDS[c]).join("-"));
  const keys = [...map.keys()].sort((a, b) => (a === "" ? 0 : a.length) - (b === "" ? 0 : b.length) || a.localeCompare(b));
  return [...head, ...keys.map((k) => group(k, label(k), k.length === 1 ? k.toLowerCase() : k === "" ? "c" : "multiple", map.get(k)!))];
}

// How many cards of each type the deck holds, counting copies, in display order.
export function typeCounts(rows: DeckRow[]): { type: string; icon: string | null; count: number }[] {
  const counts = new Map<string, number>();
  for (const r of rows) counts.set(r.type, (counts.get(r.type) ?? 0) + r.count);
  return TYPE_ORDER.filter((t) => t !== "Commander" && counts.get(t)).map((t) => ({ type: t, icon: TYPE_ICONS[t], count: counts.get(t)! }));
}

export type DeckStats = {
  // Cards at each mana value 0–7 (7 means 7 or more), lands left out, split by permanent or spell.
  curve: { manaValue: number; permanents: number; spells: number }[];
  // With and without lands, as Moxfield words it.
  average: { withLands: number; withoutLands: number };
  median: { withLands: number; withoutLands: number };
  totalManaValue: number;
  // Share of the colored mana symbols in costs, by color; the symbols counted.
  colors: { color: string; symbols: number; share: number }[];
  // Cards with no known mana value yet.
  unknown: number;
};

const median = (values: number[]): number => {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
};

export function deckStats(rows: DeckRow[], costOf: (name: string) => string | null | undefined): DeckStats {
  const curve = Array.from({ length: 8 }, (_, manaValue) => ({ manaValue, permanents: 0, spells: 0 }));
  const all: number[] = [];
  const spellsOnly: number[] = [];
  const symbols: Record<string, number> = { W: 0, U: 0, B: 0, R: 0, G: 0, C: 0 };
  let unknown = 0;
  for (const r of rows) {
    if (r.manaValue === null) {
      unknown += r.count;
      continue;
    }
    for (let i = 0; i < r.count; i++) all.push(r.manaValue);
    if (r.type === "Lands") continue;
    for (let i = 0; i < r.count; i++) spellsOnly.push(r.manaValue);
    const slot = curve[Math.min(Math.floor(r.manaValue), 7)];
    if (r.type === "Instants" || r.type === "Sorceries") slot.spells += r.count;
    else slot.permanents += r.count;
    for (const token of manaSymbols(costOf(r.name))) {
      for (const part of token.toUpperCase().split(/(?=[WUBRGC])/)) {
        if (part in symbols) symbols[part] += r.count;
      }
    }
  }
  const sum = (values: number[]) => values.reduce((a, b) => a + b, 0);
  const totalSymbols = sum(Object.values(symbols));
  return {
    curve,
    average: { withLands: all.length ? sum(all) / all.length : 0, withoutLands: spellsOnly.length ? sum(spellsOnly) / spellsOnly.length : 0 },
    median: { withLands: median(all), withoutLands: median(spellsOnly) },
    totalManaValue: sum(all),
    colors: Object.entries(symbols).map(([color, n]) => ({ color, symbols: n, share: totalSymbols ? n / totalSymbols : 0 })),
    unknown,
  };
}
