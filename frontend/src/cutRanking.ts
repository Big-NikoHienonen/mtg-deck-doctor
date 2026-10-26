import type { CardInfo, CommanderIncludes, EdhrecCard } from "./api";
import { BASIC_LAND_NAMES } from "./basicLands";
import { classifyCard, type DeckHealth, type HealthMetric } from "./deckHealth";

// Coarse card types, shared by the deck's cards (from their type line) and
// EDHREC's per-commander categories, so a cut can be paired with a
// replacement of the same kind. Mana Artifacts and Utility Artifacts are
// one group: our oracle-text read of "ramp" and EDHREC's own split don't
// always agree, and a mismatch shouldn't block a pairing.
type Group = "Creatures" | "Instants" | "Sorceries" | "Enchantments" | "Planeswalkers" | "Artifacts" | "Lands";

function groupOfCard(typeLine: string): Group | null {
  if (typeLine.includes("Creature")) return "Creatures";
  if (typeLine.includes("Planeswalker")) return "Planeswalkers";
  if (typeLine.includes("Instant")) return "Instants";
  if (typeLine.includes("Sorcery")) return "Sorceries";
  if (typeLine.includes("Artifact")) return "Artifacts";
  if (typeLine.includes("Enchantment")) return "Enchantments";
  if (typeLine.includes("Land")) return "Lands";
  return null;
}

function groupOfEdhrec(category: string): Group | null {
  switch (category) {
    case "Creatures":
    case "Instants":
    case "Sorceries":
    case "Enchantments":
    case "Planeswalkers":
      return category;
    case "Mana Artifacts":
    case "Utility Artifacts":
      return "Artifacts";
    case "Lands":
    case "Utility Lands":
      return "Lands";
    default:
      return null;
  }
}

// Used when EDHREC lists no card at all for a group.
const FALLBACK_CUTOFF = 0.05;
// How much a card in an over-target category is discounted when ranking:
// the deck has more of that kind of card than it needs, so each one is
// worth less to it than its popularity alone says.
const SURPLUS_DISCOUNT = 0.5;
const MAX_SWAPS = 8;
// How far down EDHREC's most-played list replacements are drawn from. Each
// needs its card data loaded (to know what role it fills), so the pool is
// bounded rather than the whole list.
export const POOL_SIZE = 40;

// EDHREC's most-played cards that the deck doesn't have, best first — the
// candidates for taking a cut card's place.
export function replacementPool(
  includes: Extract<CommanderIncludes, { available: true }>,
  inDeck: { has(name: string): boolean },
): EdhrecCard[] {
  return includes.cards
    .filter((c) => !inDeck.has(c.name))
    .sort((a, b) => b.inclusion - a.inclusion)
    .slice(0, POOL_SIZE);
}

export type CutCandidate = {
  name: string;
  copies: number;
  // EDHREC's inclusion rate (0–1), or null when EDHREC doesn't list the
  // card for this commander. EDHREC only lists each type's top ~50 cards,
  // so unlisted means "below the lowest one it does list", not "unknown".
  inclusion: number | null;
  // For an unlisted card: the lowest inclusion EDHREC lists in its group,
  // i.e. the card is under this.
  belowInclusion: number | null;
  groupLabel: string | null;
  // The category this cut is trimming, when that's why it's suggested.
  surplus: HealthMetric | null;
  replacement: EdhrecCard;
};

const pct = (inclusion: number) => `${Math.round(inclusion * 100)}%`;

// Why the statistics flagged a card, as a plain statement of fact. Shown
// next to the flagged pairs, and handed to the Doctor as the lead to check
// — it is evidence, not a reason to cut.
export function describeFlag(c: CutCandidate): string {
  const parts: string[] = [];
  if (c.surplus) {
    parts.push(`${c.surplus.label}: ${c.surplus.count} against a target of ${c.surplus.target[0]}–${c.surplus.target[1]}`);
  }
  if (c.inclusion !== null) {
    parts.push(`played in ${pct(c.inclusion)} of decks with this commander`);
  } else if (c.belowInclusion !== null) {
    parts.push(
      `not among the ${c.groupLabel ?? "cards"} EDHREC lists for this commander (the least-played one it lists is in ${pct(c.belowInclusion)} of decks)`,
    );
  }
  return parts.join("; ");
}

export type CutAnalysis = {
  candidates: CutCandidate[];
  // Cards left out because cutting them would take a category that's
  // already at or under its target range lower still.
  protectedCount: number;
  // Cards left out because their card data hasn't loaded yet.
  unknownCount: number;
};

type Ranked = {
  name: string;
  copies: number;
  group: Group | null;
  roles: Set<HealthMetric["key"]>;
  inclusion: number | null;
  belowInclusion: number | null;
  score: number;
  surplus: HealthMetric | null;
};

// Which cards to cut, each paired with a card to put in its place.
//
// A replacement never adds to a category the deck is already full on, never
// refills the category the cut was trimming, and prefers a card that fills
// a category the deck is short on, then one of the same type as the cut.
// Counts are tracked across the whole list, so two swaps can't both add the
// last open ramp slot.
//
// Ranking is by EDHREC inclusion (ascending), adjusted for the deck's own
// health: a card filling a category that's at or under its target range is
// never offered (cutting it makes the gap worse), and a card in an
// over-target category ranks as if it were half as popular. Basics only
// come up when the deck has more lands than the target allows — they have
// no inclusion rate — and then as a single row, the most plentiful basic,
// since a basic is the same card ten times over.
//
// Computed from page state that's already loaded (health, card data,
// EDHREC), so it updates instantly as the deck changes.
export function analyzeCuts({
  cardCounts,
  cardInfo,
  keep,
  includes,
  health,
}: {
  cardCounts: Map<string, number>;
  cardInfo: Record<string, CardInfo>;
  keep: string[];
  includes: Extract<CommanderIncludes, { available: true }>;
  health: DeckHealth;
}): CutAnalysis {
  const metric = (key: HealthMetric["key"]) => health.metrics.find((m) => m.key === key)!;
  const kept = new Set(keep);
  const listed = new Map(includes.cards.map((c) => [c.name, c]));

  const cutoffs = new Map<Group, number>();
  for (const card of includes.cards) {
    const group = groupOfEdhrec(card.category);
    if (group) cutoffs.set(group, Math.min(cutoffs.get(group) ?? Infinity, card.inclusion));
  }

  let protectedCount = 0;
  let unknownCount = 0;
  const ranked: Ranked[] = [];
  let topBasic: { name: string; copies: number } | null = null;

  for (const [name, copies] of cardCounts) {
    if (kept.has(name)) continue;
    const info = cardInfo[name];
    if (!info || info.typeLine === null) {
      unknownCount++;
      continue;
    }

    const lands = metric("lands");
    if (BASIC_LAND_NAMES.has(name)) {
      if (lands.status === "high" && (!topBasic || copies > topBasic.copies)) topBasic = { name, copies };
      continue;
    }

    const roles = classifyCard(info.typeLine, info.oracleText ?? "");
    const group = groupOfCard(info.typeLine);

    const fillsShortRole = [...roles].some((key) => metric(key).count <= metric(key).target[0]);
    if (fillsShortRole) {
      protectedCount++;
      continue;
    }

    const surplusKey = [...roles].find((key) => metric(key).status === "high");
    const surplus = surplusKey ? metric(surplusKey) : null;
    const entry = listed.get(name);
    const cutoff = (group && cutoffs.get(group)) ?? FALLBACK_CUTOFF;
    // An unlisted card is below the lowest listed one in its group, so it
    // is scored at half that — under every listed card of its kind.
    const base = entry ? entry.inclusion : cutoff * 0.5;
    ranked.push({
      name,
      copies,
      group,
      roles,
      inclusion: entry ? entry.inclusion : null,
      belowInclusion: entry ? null : cutoff,
      score: surplus ? base * SURPLUS_DISCOUNT : base,
      surplus,
    });
  }

  if (topBasic) {
    const { name, copies } = topBasic;
    ranked.push({
      name,
      copies,
      group: "Lands",
      roles: new Set(["lands"]),
      inclusion: null,
      belowInclusion: null,
      score: -1,
      surplus: metric("lands"),
    });
  }

  ranked.sort((a, b) => a.score - b.score || a.name.localeCompare(b.name));

  // Only candidates whose card data has loaded: without it there's no
  // knowing what role a card fills.
  const pool = replacementPool(includes, cardCounts).flatMap((card) => {
    const info = cardInfo[card.name];
    return info?.typeLine ? [{ card, roles: classifyCard(info.typeLine, info.oracleText ?? "") }] : [];
  });
  const delta: Record<HealthMetric["key"], number> = { lands: 0, ramp: 0, draw: 0, interaction: 0 };
  const count = (key: HealthMetric["key"]) => metric(key).count + delta[key];

  const candidates: CutCandidate[] = [];
  for (const card of ranked) {
    if (candidates.length >= MAX_SWAPS) break;

    // The surplus ends once earlier swaps in the list have used it up: with
    // ramp one over target, only one ramp card is spare, not every one.
    const surplus = card.surplus && count(card.surplus.key) > card.surplus.target[1] ? card.surplus : null;
    const eligible = pool.filter((p) => {
      if (surplus && p.roles.has(surplus.key)) return false;
      return [...p.roles].every((key) => card.roles.has(key) || count(key) + 1 <= metric(key).target[1]);
    });
    const tier = (p: (typeof pool)[number]) =>
      [...p.roles].some((key) => count(key) < metric(key).target[0])
        ? 0
        : groupOfEdhrec(p.card.category) === card.group
          ? 1
          : 2;
    // The pool is already best-first, so the first of the best tier wins.
    const best = eligible.reduce<(typeof pool)[number] | undefined>(
      (chosen, p) => (!chosen || tier(p) < tier(chosen) ? p : chosen),
      undefined,
    );
    if (!best) continue;

    pool.splice(pool.indexOf(best), 1);
    card.roles.forEach((key) => delta[key]--);
    best.roles.forEach((key) => delta[key]++);

    candidates.push({
      name: card.name,
      copies: card.copies,
      inclusion: card.inclusion,
      belowInclusion: card.belowInclusion,
      groupLabel: card.group ? card.group.toLowerCase() : null,
      surplus,
      replacement: best.card,
    });
  }

  return { candidates, protectedCount, unknownCount };
}
