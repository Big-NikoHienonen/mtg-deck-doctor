import type { CardInfo } from "./api";

// Target ranges come from the standard Commander composition the AI's own
// system prompt already uses (36-38 lands, ~10 each of ramp / interaction
// / draw, out of 99 non-commander cards) — widened a little so a deck
// isn't flagged for being a card off.
export type HealthMetric = {
  key: "lands" | "ramp" | "draw" | "interaction";
  label: string;
  count: number;
  target: [number, number];
  status: "low" | "ok" | "high";
  // Which cards were counted — shown on demand, because the oracle-text
  // matching below is a heuristic and a wrong count should be checkable.
  cards: string[];
};

export type DeckHealth = {
  metrics: HealthMetric[];
  // How many of the deck's distinct cards had card data loaded to analyze.
  coveredCards: number;
  totalCards: number;
};

const TARGETS: Record<HealthMetric["key"], { label: string; target: [number, number] }> = {
  lands: { label: "Lands", target: [35, 38] },
  ramp: { label: "Ramp", target: [8, 12] },
  draw: { label: "Card draw", target: [8, 12] },
  interaction: { label: "Removal & interaction", target: [8, 12] },
};

const MANA_ABILITY = /\badd\b[^.]*\{[wubrgcx0-9]\}|\badd (one|two|three|four) mana/;
const LAND_FETCH =
  /search your library for [^.]*\b(land|plains|island|swamp|mountain|forest)\b[^.]*onto the battlefield/;
const DRAW = /\bdraws? (a|an|two|three|four|five|x|\d+) (additional )?cards?\b|\bdraw cards equal\b/;
const IMPULSE_DRAW = /exile the top [^.]*you may (play|cast)/;
const SPOT_REMOVAL =
  /(destroy|exile) (up to \w+ )?target [^.]*(creature|permanent|artifact|enchantment|planeswalker|nonland|battle)/;
const SWEEPER = /(destroy|exile) all [^.]*(creature|permanent|artifact|enchantment|nonland)/;
const DAMAGE_REMOVAL = /deals? (\d+|x) damage to (any target|target creature|each creature|each other creature)/;
const SHRINK = /target creature gets -(\d+|x)\/-(\d+|x)/;
// "target creature" but not "target creature card" — recursion from the
// graveyard (Golgari Thug) is the opposite of removal.
const TUCK = /owner of target permanent shuffles|(shuffle|put) [^.]*target (creature|permanent)(?! card)[^.]*library/;
const COUNTERSPELL = /counter target (spell|activated|triggered)/;

export function classifyCard(typeLine: string, oracle: string): Set<HealthMetric["key"]> {
  const found = new Set<HealthMetric["key"]>();
  if (typeLine.includes("Land")) {
    found.add("lands");
    return found;
  }
  // Reminder text lives in parentheses — "Cycling {2} ({2}, Discard this
  // card: Draw a card.)" would otherwise read as a card-draw spell, and a
  // Treasure's reminder text as a mana ability.
  const text = oracle.replace(/\([^)]*\)/g, "").toLowerCase();
  const isSpell = typeLine.includes("Instant") || typeLine.includes("Sorcery");
  const isManaPermanent =
    !isSpell && (typeLine.includes("Artifact") || typeLine.includes("Creature") || typeLine.includes("Enchantment"));

  if ((isManaPermanent && MANA_ABILITY.test(text)) || LAND_FETCH.test(text)) found.add("ramp");
  if (DRAW.test(text) || IMPULSE_DRAW.test(text)) found.add("draw");
  if (
    SPOT_REMOVAL.test(text) ||
    SWEEPER.test(text) ||
    DAMAGE_REMOVAL.test(text) ||
    SHRINK.test(text) ||
    TUCK.test(text) ||
    COUNTERSPELL.test(text)
  ) {
    found.add("interaction");
  }
  return found;
}

// A rough health read of the deck's composition from card oracle text —
// explicitly a heuristic (a creature that taps for mana counts as ramp, a
// "destroy target" spell counts as removal), so it's labeled as an
// estimate in the UI and every count can be expanded to its cards.
export function analyzeDeck(cardCounts: Map<string, number>, cardInfo: Record<string, CardInfo>): DeckHealth {
  const buckets: Record<HealthMetric["key"], { count: number; cards: string[] }> = {
    lands: { count: 0, cards: [] },
    ramp: { count: 0, cards: [] },
    draw: { count: 0, cards: [] },
    interaction: { count: 0, cards: [] },
  };

  let covered = 0;
  cardCounts.forEach((quantity, name) => {
    const info = cardInfo[name];
    if (!info || info.typeLine === null) return;
    covered++;
    for (const key of classifyCard(info.typeLine, info.oracleText ?? "")) {
      buckets[key].count += quantity;
      buckets[key].cards.push(quantity > 1 ? `${name} ×${quantity}` : name);
    }
  });

  const metrics = (Object.keys(TARGETS) as HealthMetric["key"][]).map((key) => {
    const { label, target } = TARGETS[key];
    const { count, cards } = buckets[key];
    const status: HealthMetric["status"] = count < target[0] ? "low" : count > target[1] ? "high" : "ok";
    return { key, label, count, target, status, cards: cards.sort((a, b) => a.localeCompare(b)) };
  });

  return { metrics, coveredCards: covered, totalCards: cardCounts.size };
}
