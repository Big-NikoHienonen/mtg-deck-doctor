/**
 * Tests for the Manalytics comparison of colored symbols with mana sources (frontend/src/manaBalance.ts). It is
 * plain TypeScript with only type imports, so Node runs it as it is (Node 22.18 or later; on 22.6 to 22.17 add
 * --experimental-strip-types). Run with
 *
 *     node tests/test_mana_balance.ts
 */

import { manaBalance } from "../frontend/src/manaBalance.ts";

let pass = 0, fail = 0;
const check = (name: string, ok: unknown, detail = "") => { ok ? pass++ : fail++; console.log((ok ? "PASS " : "FAIL ") + name + (detail ? `  [${detail}]` : "")); };

const row = (name: string, type: string, count: number, produced?: string[]) =>
  ({ name, count, type, info: produced === undefined ? {} : { producedMana: produced }, price: null, manaValue: 0, colors: [], isCommander: false }) as any;
const symbols = (o: Record<string, number>) => ["W", "U", "B", "R", "G", "C"].map((color) => ({ color, symbols: o[color] ?? 0 }));
const by = (b: ReturnType<typeof manaBalance>, c: string) => b.colors.find((x) => x.color === c)!;

// A Grixis-ish deck: lots of black symbols, but the mana leans red.
const rows = [
  row("Swamp", "Lands", 3, ["B"]), row("Mountain", "Lands", 8, ["R"]), row("Island", "Lands", 4, ["U"]),
  row("Dimir Guildgate", "Lands", 1, ["B", "U"]), row("Command Tower", "Lands", 1, ["B", "U", "R", "W", "G"]),
  row("Sol Ring", "Artifacts", 1, ["C"]), row("Arcane Signet", "Artifacts", 1, ["B", "U", "R", "W", "G"]),
  row("Dark Ritual", "Instants", 1, ["B"]), row("Rampant Growth", "Sorceries", 1, []),
];
const b = manaBalance(symbols({ B: 20, U: 10, R: 10 }), rows, ["B", "U", "R"]);
check("only the deck's colors are shown", b.colors.map((c) => c.color).join("") === "UBR", b.colors.map((c) => c.color).join(""));
check("a land counts for each color it makes", by(b, "B").lands === 3 + 1 + 1 && by(b, "U").lands === 4 + 1 + 1 && by(b, "R").lands === 8 + 1);
check("a rock counts under other", by(b, "B").other === 1 && by(b, "R").other === 1);
check("'any color' is limited to the commander's colors (no W or G)", b.colors.every((c) => c.color !== "W" && c.color !== "G"));
check("a ritual (instant) is not a source", by(b, "B").sources === 3 + 1 + 1 + 1, String(by(b, "B").sources));
check("Sol Ring counts as colorless, not as a color", b.colorlessSources === 1);
check("symbol shares add up to 1", Math.abs(b.colors.reduce((n, c) => n + c.symbolShare, 0) - 1) < 1e-9);
check("source shares add up to 1", Math.abs(b.colors.reduce((n, c) => n + c.sourceShare, 0) - 1) < 1e-9);
check("land and other shares add up to the source share", b.colors.every((c) => Math.abs(c.landShare + c.otherShare - c.sourceShare) < 1e-9));
check("black is short: half the symbols, a smaller share of the sources", by(b, "B").symbolShare === 0.5 && by(b, "B").verdict === "short", `${by(b, "B").symbolShare} vs ${by(b, "B").sourceShare}`);
check("red, with plenty of mana, is fine", by(b, "R").verdict === "ok");
check("nothing is unknown", b.unknown === 0);

// A color with symbols and no source at all.
const none = manaBalance(symbols({ W: 2, G: 8 }), [row("Forest", "Lands", 10, ["G"])], ["W", "G"]);
check("a color with symbols and no source is 'none'", by(none, "W").verdict === "none" && by(none, "G").verdict === "ok");

// A color in the identity with no symbols: shown, never short.
const idle = manaBalance(symbols({ G: 5 }), [row("Forest", "Lands", 5, ["G"]), row("Island", "Lands", 2, ["U"])], ["G", "U"]);
check("a color in the identity with no symbols is shown and fine", by(idle, "U").verdict === "ok" && by(idle, "U").symbols === 0);

// A splash with a symbol but outside the identity (hybrid/odd data) still shows.
const splash = manaBalance(symbols({ R: 1, G: 20 }), [row("Forest", "Lands", 10, ["G"])], ["G"]);
check("a color with symbols but outside the identity is shown", splash.colors.some((c) => c.color === "R"));

// Unknown mana production.
const partial = manaBalance(symbols({ G: 5 }), [row("Forest", "Lands", 5, ["G"]), row("Mystery", "Artifacts", 2, undefined)], ["G"]);
check("cards with no mana production recorded are counted as unknown, not as non-sources", partial.unknown === 2);
const noinfo = manaBalance(symbols({ G: 5 }), [{ ...row("Forest", "Lands", 3), info: undefined }], ["G"]);
check("a card that hasn't loaded at all is unknown too", noinfo.unknown === 3);

// A colorless deck.
const colorless = manaBalance(symbols({}), [row("Wastes", "Lands", 20, ["C"]), row("Sol Ring", "Artifacts", 1, ["C"])], []);
check("a colorless deck has no colors to compare", colorless.colors.length === 0 && colorless.colorlessSources === 21 && colorless.totalSymbols === 0);

// No sources and no symbols at all: nothing divides by zero.
const empty = manaBalance(symbols({}), [], ["W"]);
check("an empty deck doesn't divide by zero", empty.colors.length === 1 && empty.colors[0].symbolShare === 0 && empty.colors[0].sourceShare === 0 && empty.colors[0].verdict === "ok");

// The boundary: exactly 10 points short is short, just under is not.
const edge = manaBalance(symbols({ W: 50, U: 50 }), [row("Plains", "Lands", 40, ["W"]), row("Island", "Lands", 60, ["U"])], ["W", "U"]);
check("ten points short counts as short", by(edge, "W").verdict === "short", `${by(edge, "W").symbolShare} vs ${by(edge, "W").sourceShare}`);
const near = manaBalance(symbols({ W: 50, U: 50 }), [row("Plains", "Lands", 41, ["W"]), row("Island", "Lands", 59, ["U"])], ["W", "U"]);
check("nine points short does not", by(near, "W").verdict === "ok");

console.log(`\n${pass}/${pass + fail} passed`); process.exit(fail ? 1 : 0);
