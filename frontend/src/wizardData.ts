// The words the new-deck helper uses: what the colours, styles, power levels and
// budgets are called and mean. Fixed text, written here so it can be edited
// without touching the flow.

export const COLOR_LETTERS = ["W", "U", "B", "R", "G"] as const;

export const COLOR_INFO: Record<string, { name: string; blurb: string }> = {
  W: { name: "White", blurb: "Order, protection, small creatures and lifegain" },
  U: { name: "Blue", blurb: "Card draw, counterspells and clever tricks" },
  B: { name: "Black", blurb: "Removal, bringing things back, sacrifice" },
  R: { name: "Red", blurb: "Damage, speed and chaos" },
  G: { name: "Green", blurb: "Mana ramp and enormous creatures" },
};

// What each exact combination of colours is called.
const COMBO_NAMES: Record<string, string> = {
  "": "Colorless",
  W: "Mono-white", U: "Mono-blue", B: "Mono-black", R: "Mono-red", G: "Mono-green",
  WU: "Azorius", UB: "Dimir", BR: "Rakdos", RG: "Gruul", GW: "Selesnya",
  WB: "Orzhov", UR: "Izzet", BG: "Golgari", RW: "Boros", GU: "Simic",
  GWU: "Bant", WUB: "Esper", UBR: "Grixis", BRG: "Jund", RGW: "Naya",
  WBG: "Abzan", URW: "Jeskai", BGU: "Sultai", RWB: "Mardu", GUR: "Temur",
  WUBR: "Yore-Tiller", UBRG: "Glint-Eye", BRGW: "Dune-Brood", RGWU: "Ink-Treader", GWUB: "Witch-Maw",
  WUBRG: "Five-color",
};

// Letters in the order the backend and the site both use.
export function canonicalColors(letters: string[]): string {
  return COLOR_LETTERS.filter((c) => letters.includes(c)).join("");
}

export function colorComboName(letters: string[]): string {
  const key = canonicalColors(letters);
  const found = Object.entries(COMBO_NAMES).find(([k]) => canonicalColors(k.split("")) === key);
  return found ? found[1] : key;
}

export function colorWords(letters: string[]): string {
  if (letters.length === 0) return "no colors at all";
  return COLOR_LETTERS.filter((c) => letters.includes(c))
    .map((c) => COLOR_INFO[c].name.toLowerCase())
    .join(", ");
}

export type Style = { slug: string; label: string; blurb: string };

// Strategies, by the names EDHREC uses for them.
export const STRATEGIES: Style[] = [
  { slug: "tokens", label: "Tokens", blurb: "Fill the table with small creatures and make them matter" },
  { slug: "aristocrats", label: "Aristocrats", blurb: "Sacrifice your own creatures for value and drain" },
  { slug: "reanimator", label: "Reanimator", blurb: "Cheat big creatures out of the graveyard" },
  { slug: "self-mill", label: "Self-mill", blurb: "Fill your own graveyard, then use it" },
  { slug: "voltron", label: "Voltron", blurb: "One commander, suited up and enormous" },
  { slug: "spellslinger", label: "Spellslinger", blurb: "Cast lots of instants and sorceries" },
  { slug: "big-mana", label: "Big mana", blurb: "Ramp into huge spells" },
  { slug: "lifegain", label: "Lifegain", blurb: "Gain life and turn it into an advantage" },
  { slug: "artifacts", label: "Artifacts", blurb: "Build around artifacts and what they do" },
  { slug: "equipment", label: "Equipment", blurb: "Gear up your creatures" },
  { slug: "landfall", label: "Landfall", blurb: "Get rewarded for playing lands" },
  { slug: "blink", label: "Blink", blurb: "Reuse enter-the-battlefield effects" },
  { slug: "control", label: "Control", blurb: "Answer threats and win late" },
  { slug: "group-hug", label: "Group hug", blurb: "Help everyone, and come out ahead" },
];

export const CREATURE_TYPES: Style[] = [
  "dragons", "zombies", "vampires", "elves", "goblins", "angels", "cats", "dinosaurs",
  "merfolk", "wizards", "pirates", "slivers", "werewolves", "elementals", "knights", "ninjas",
].map((slug) => ({ slug, label: slug[0].toUpperCase() + slug.slice(1), blurb: `A ${slug.replace(/s$/, "")} deck` }));

export const ALL_STYLE_SLUGS = [...STRATEGIES, ...CREATURE_TYPES].map((s) => s.slug);

// The Commander Brackets, in plain words. EDHREC sorts decks into these by what
// their builders said they were, so the descriptions are about feel, not rules.
export const BRACKETS = [
  { n: 1, label: "Exhibition", blurb: "Theme first. Silly and casual is the point; winning isn't." },
  { n: 2, label: "Core", blurb: "About a preconstructed deck's level. Straightforward plans, few tutors or combos." },
  { n: 3, label: "Upgraded", blurb: "Tuned past a precon: strong synergies and some premium cards." },
  { n: 4, label: "Optimized", blurb: "High power. Fast mana, tutors and efficient combos; games end quickly." },
] as const;

export const DEFAULT_BRACKET = 2;

// The parts of a deck the player can say how to spend on. Slugs are the
// backend's (wizard.AREAS). "cap" is what "keep it cheap" starts at when there
// is no budget to take a share of.
export const SPEND_AREAS = [
  { slug: "lands", label: "Lands", blurb: "Duals, fetches and other non-basic lands. They can cost more than all your spells put together.", cap: 30 },
  { slug: "rocks", label: "Mana rocks", blurb: "Sol Ring, signets and other artifacts that make mana.", cap: 15 },
  { slug: "creatures", label: "Creatures", blurb: "Your creatures, commander aside.", cap: 50 },
  { slug: "spells", label: "Other spells", blurb: "Instants, sorceries, enchantments, planeswalkers and non-mana artifacts.", cap: 50 },
] as const;

export type SpendMode = "cheap" | "normal" | "invest";

// What "keep it cheap" starts at: a seventh of the budget, rounded to $5.
export function defaultCap(slug: string, budget: number | null): number {
  const fallback = SPEND_AREAS.find((a) => a.slug === slug)?.cap ?? 30;
  return budget === null ? fallback : Math.max(5, Math.round(budget / 7 / 5) * 5);
}

// null is "no preference", which leaves the budget to the Doctor; "none" is a
// stated wish for no limit.
export const BUDGETS: { label: string; cap: number | "none" | null }[] = [
  { label: "No preference", cap: null },
  { label: "Up to $50", cap: 50 },
  { label: "Up to $100", cap: 100 },
  { label: "Up to $250", cap: 250 },
  { label: "No limit", cap: "none" },
];
