import type { CardInfo, Deck } from "./api";
import { CATEGORY_ORDER, categoryFor } from "./cardCategories";

export type ParsedImportLine = { rawName: string; quantity: number };

const LINE_RE = /^(\d+)\s*x?\s+(.+)$/i;

// Strips the decorations real decklist exports commonly add around a
// name — foil/finish markers ("*F*"), and a trailing set code and/or
// collector number ("(C21) 263") — so the remaining text is just the
// card name. Harmless to run on a name that has none of these.
function cleanCardName(raw: string): string {
  return raw
    .replace(/\*[^*]*\*/g, "")
    .replace(/\([A-Za-z0-9]+\)\s*[\w-]*\s*$/, "")
    .trim();
}

// Parses a pasted decklist into quantity+name entries, merging repeated
// lines for the same name. A line with no leading quantity — a category
// header, "Commander: ...", a blank line, a "//" or "#" comment — isn't a
// card line and is silently skipped, same as every other deckbuilder's
// own paste-import.
export function parseDecklist(text: string): ParsedImportLine[] {
  const byName = new Map<string, number>();
  for (const rawLine of text.split("\n")) {
    const line = rawLine.trim();
    if (!line || line.startsWith("//") || line.startsWith("#")) continue;
    const match = line.match(LINE_RE);
    if (!match) continue;
    const quantity = parseInt(match[1], 10);
    const name = cleanCardName(match[2]);
    if (!name) continue;
    byName.set(name, (byName.get(name) ?? 0) + quantity);
  }
  return Array.from(byName, ([rawName, quantity]) => ({ rawName, quantity }));
}

// The de facto universal decklist format — "qty name" per line, groups
// with a header line — pastes straight into Moxfield/Archidekt/TappedOut/
// MTGGoldfish's own import boxes. Groups by the same category the ledger
// itself shows, so what you see on screen is what you get in the export.
export function buildDecklistText(
  deck: Deck,
  cardCounts: Map<string, number>,
  cardInfo: Record<string, CardInfo>,
): string {
  const lines: string[] = [];
  if (deck.commander) {
    lines.push(`Commander: ${deck.commander}`, "");
  }

  const byCategory = new Map<string, { name: string; count: number }[]>();
  cardCounts.forEach((count, name) => {
    const category = categoryFor(cardInfo[name]?.typeLine ?? undefined);
    if (!byCategory.has(category)) byCategory.set(category, []);
    byCategory.get(category)!.push({ name, count });
  });
  byCategory.forEach((entries) => entries.sort((a, b) => a.name.localeCompare(b.name)));

  const nonEmptyCategories = CATEGORY_ORDER.filter((category) => byCategory.get(category)?.length);
  nonEmptyCategories.forEach((category, i) => {
    if (i > 0) lines.push("");
    const entries = byCategory.get(category)!;
    const total = entries.reduce((sum, e) => sum + e.count, 0);
    lines.push(`${category} (${total})`);
    entries.forEach(({ name, count }) => lines.push(`${count} ${name}`));
  });

  return lines.join("\n");
}
