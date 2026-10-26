// Shared with DeckView's ledger grouping and the decklist exporter, so a
// card lands in the same category in both places.
export const CATEGORY_ORDER = [
  "Creatures",
  "Planeswalkers",
  "Battles",
  "Instants",
  "Sorceries",
  "Artifacts",
  "Enchantments",
  "Lands",
  "Other",
];

export function categoryFor(typeLine: string | undefined): string {
  if (!typeLine) return "Other";
  if (typeLine.includes("Creature")) return "Creatures";
  if (typeLine.includes("Planeswalker")) return "Planeswalkers";
  if (typeLine.includes("Battle")) return "Battles";
  if (typeLine.includes("Instant")) return "Instants";
  if (typeLine.includes("Sorcery")) return "Sorceries";
  if (typeLine.includes("Artifact")) return "Artifacts";
  if (typeLine.includes("Enchantment")) return "Enchantments";
  if (typeLine.includes("Land")) return "Lands";
  return "Other";
}
