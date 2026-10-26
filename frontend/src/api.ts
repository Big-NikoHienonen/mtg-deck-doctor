import { clearAiProblem, reportAiProblem } from "./aiStatus";

const API_BASE = "http://localhost:8000";

// fetch() itself rejects on a network-level failure (offline, DNS, a CORS
// block with no response at all) — distinct from a normal non-2xx
// response, which resolves fine and is handled by each call site's own
// `!res.ok` check. Every function below goes through this instead of a
// bare fetch() so both failure modes end up in the same place: a soft-
// fail function (returns null/[]) treats "no response" the same as a bad
// one, and a hard-fail function (throws) throws the same message either
// way — never an unhandled TypeError surfacing as an uncaught rejection
// at a lazy .then() call site with no .catch().
async function safeFetch(input: string | URL, init?: RequestInit): Promise<Response | null> {
  try {
    const res = await fetch(input, init);
    // A model call that failed for a reason outside the request (see
    // backend/ai_errors.py) is recorded once, here, for the whole page.
    if (!res.ok && (res.status === 429 || res.status === 502 || res.status === 503)) {
      const body = await res.clone().json().catch(() => null);
      if (typeof body?.code === "string" && body.code.startsWith("ai_")) reportAiProblem(body);
    }
    return res;
  } catch {
    return null;
  }
}

// Asks the backend whether the model can be reached right now, without sending
// anyone's message. Clears the page-wide problem if it can. Returns null when
// it can, otherwise why not.
export async function checkAi(): Promise<string | null> {
  const res = await safeFetch(`${API_BASE}/ai/status`);
  if (!res) return "Couldn't reach the Deck Doctor backend. Is it running on port 8000?";
  if (res.ok) {
    clearAiProblem();
    return null;
  }
  const body = await res.json().catch(() => null);
  return body?.detail ?? "The Doctor still isn't available.";
}

export type MessageBlock =
  | { type: "text"; text: string }
  | { type: "tool_use"; id: string; name: string; input: Record<string, unknown> }
  | { type: "tool_result"; tool_use_id: string; content: string };

export type Message = {
  role: "user" | "assistant";
  content: string | MessageBlock[];
};

export type Deck = {
  id: string;
  name: string | null;
  commander: string | null;
  commander_color_identity: string[];
  cards: string[];
  // Cards the owner marked as keepers — never offered as cut candidates.
  keep: string[];
  messages: Message[];
  updated_at: string;
  // Counts saves; the backend refuses to save over a version it hasn't seen.
  version: number;
};

export function extractText(content: string | MessageBlock[]): string {
  if (typeof content === "string") return content;
  return content
    .filter((block): block is Extract<MessageBlock, { type: "text" }> => block.type === "text")
    .map((block) => block.text)
    .join("");
}

export async function createDeck(): Promise<Deck> {
  const res = await safeFetch(`${API_BASE}/decks`, { method: "POST" });
  if (!res || !res.ok) throw new Error("failed to create deck");
  return res.json();
}

export async function listDecks(): Promise<Deck[]> {
  const res = await safeFetch(`${API_BASE}/decks`);
  if (!res || !res.ok) throw new Error("failed to list decks");
  return res.json();
}

export async function deleteDeck(id: string): Promise<void> {
  const res = await safeFetch(`${API_BASE}/decks/${id}`, { method: "DELETE" });
  if (!res || !res.ok) throw new Error("failed to delete deck");
}

export async function duplicateDeck(id: string): Promise<Deck> {
  const res = await safeFetch(`${API_BASE}/decks/${id}/duplicate`, { method: "POST" });
  if (!res || !res.ok) throw new Error("failed to duplicate deck");
  return res.json();
}

export async function getDeck(id: string): Promise<Deck | null> {
  const res = await safeFetch(`${API_BASE}/decks/${id}`);
  if (!res) throw new Error("failed to load deck");
  if (res.status === 404) return null;
  if (!res.ok) throw new Error("failed to load deck");
  return res.json();
}

export async function sendMessage(id: string, message: string): Promise<{ reply: string; deck: Deck }> {
  const res = await safeFetch(`${API_BASE}/decks/${id}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!res) throw new Error("Couldn't reach the Deck Doctor backend. Is it running on port 8000?");
  if (!res.ok) {
    // Model failures are already recorded page-wide by safeFetch; the message is
    // the backend's own explanation of what went wrong.
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? "That message didn't go through.");
  }
  return res.json();
}

async function postCardName(url: string, name: string): Promise<Deck> {
  const res = await safeFetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!res || !res.ok) {
    const body = await res?.json().catch(() => null);
    throw new Error(body?.detail ?? "That didn't work.");
  }
  return res.json();
}

export function setCommander(deckId: string, name: string): Promise<Deck> {
  return postCardName(`${API_BASE}/decks/${deckId}/commander`, name);
}

export function renameDeck(deckId: string, name: string): Promise<Deck> {
  return postCardName(`${API_BASE}/decks/${deckId}/name`, name);
}

export function addCard(deckId: string, name: string): Promise<Deck> {
  return postCardName(`${API_BASE}/decks/${deckId}/cards`, name);
}

export async function removeCard(deckId: string, name: string): Promise<Deck> {
  const url = new URL(`${API_BASE}/decks/${deckId}/cards`);
  url.searchParams.set("name", name);
  const res = await safeFetch(url, { method: "DELETE" });
  if (!res || !res.ok) {
    const body = await res?.json().catch(() => null);
    throw new Error(body?.detail ?? "That didn't work.");
  }
  return res.json();
}

// Atomic on the backend: the replacement is validated against the deck as it
// will be once the cut is gone, and both changes are saved together or not
// at all — a rejected swap leaves the deck exactly as it was.
export async function swapCards(deckId: string, remove: string, add: string): Promise<Deck> {
  const res = await safeFetch(`${API_BASE}/decks/${deckId}/swap`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ remove, add }),
  });
  if (!res || !res.ok) {
    const body = await res?.json().catch(() => null);
    throw new Error(body?.detail ?? "Couldn't swap those cards.");
  }
  return res.json();
}

export function keepCard(deckId: string, name: string): Promise<Deck> {
  return postCardName(`${API_BASE}/decks/${deckId}/keep`, name);
}

export async function unkeepCard(deckId: string, name: string): Promise<Deck> {
  const url = new URL(`${API_BASE}/decks/${deckId}/keep`);
  url.searchParams.set("name", name);
  const res = await safeFetch(url, { method: "DELETE" });
  if (!res || !res.ok) {
    const body = await res?.json().catch(() => null);
    throw new Error(body?.detail ?? "That didn't work.");
  }
  return res.json();
}

export type BulkAddResult = { deck: Deck; added: number; failed: number; error: string | null };

export async function bulkAddCards(deckId: string, name: string, count: number): Promise<BulkAddResult> {
  const res = await safeFetch(`${API_BASE}/decks/${deckId}/cards/bulk`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, count }),
  });
  if (!res || !res.ok) {
    const body = await res?.json().catch(() => null);
    throw new Error(body?.detail ?? "That didn't work.");
  }
  return res.json();
}

export type ImportCardsResult = {
  deck: Deck;
  added: number;
  failed: { name: string; error: string }[];
};

// One request for the whole pasted decklist (every name + quantity at
// once) rather than one bulkAddCards call per unique name — same
// single-deck-load/save-cycle reasoning as every other bulk mutation
// here.
export async function importCards(
  deckId: string,
  entries: { name: string; quantity: number }[],
): Promise<ImportCardsResult> {
  const res = await safeFetch(`${API_BASE}/decks/${deckId}/cards/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ entries }),
  });
  if (!res || !res.ok) {
    const body = await res?.json().catch(() => null);
    throw new Error(body?.detail ?? "That didn't work.");
  }
  return res.json();
}

// id is the card's Scryfall id when the backend's card cache has it, so art
// can be shown without a lookup.
export type Recommendation = { name: string; reason: string; price_usd: string | null; id?: string | null };

export type Suggestions = {
  generated_at: string;
  // True when the deck's cards differ from what these were written for.
  deck_changed: boolean;
  recommendations: Recommendation[];
};

// Reads only — never triggers generation, so opening a deck can't spend
// LLM tokens by itself. null means none have been generated for this deck.
export async function getSuggestions(deckId: string): Promise<Suggestions | null> {
  const res = await safeFetch(`${API_BASE}/decks/${deckId}/suggestions`);
  if (!res || !res.ok) throw new Error("Couldn't load suggestions.");
  const data = await res.json();
  return data.suggestions;
}

// Runs the AI suggestion loop (~10s, costs tokens) and stores the result.
export async function refreshSuggestions(deckId: string): Promise<Suggestions> {
  const res = await safeFetch(`${API_BASE}/decks/${deckId}/suggestions/refresh`, { method: "POST" });
  if (!res || !res.ok) {
    const body = await res?.json().catch(() => null);
    throw new Error(body?.detail ?? "Couldn't get suggestions. Try again.");
  }
  const data = await res.json();
  return data.suggestions;
}

// A swap the Doctor recommends, with the two reasons that make it one: why
// the card goes, and why players run its replacement with this commander.
// source is "data" when it is one of the pairs the statistics flagged, and
// "doctor" when the Doctor chose the swap (or the replacement) itself.
export type CutSwap = {
  cut: string;
  add: string;
  reason_cut: string;
  reason_add: string;
  source: "data" | "doctor";
  price_usd: string | null;
  add_id?: string | null;
};

// A flagged card the Doctor would keep, and why.
export type CutKept = { cut: string; reason_cut: string };

export type Cuts = {
  generated_at: string;
  // True when the deck's cards differ from what the review was written for.
  deck_changed: boolean;
  swaps: CutSwap[];
  kept: CutKept[];
};

// What the Doctor is asked to review: pairs the ranking flagged (with why, in
// words) and the deck's composition against the standard mix.
export type CutReviewRequest = {
  candidates: { cut: string; add: string; flag: string }[];
  health: { label: string; count: number; target: number[]; cards: string[] }[];
};

// Reads only — never triggers a review. null means none has been run for
// this deck.
export async function getCuts(deckId: string): Promise<Cuts | null> {
  const res = await safeFetch(`${API_BASE}/decks/${deckId}/cuts`);
  if (!res || !res.ok) throw new Error("Couldn't load the Doctor's review.");
  const data = await res.json();
  return data.cuts;
}

// Has the Doctor review the flagged swaps (about a minute, costs tokens) and
// stores the result.
export async function reviewCuts(deckId: string, request: CutReviewRequest): Promise<Cuts> {
  const res = await safeFetch(`${API_BASE}/decks/${deckId}/cuts/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res || !res.ok) {
    const body = await res?.json().catch(() => null);
    throw new Error(body?.detail ?? "Couldn't get the Doctor's review. Try again.");
  }
  const data = await res.json();
  return data.cuts;
}

// One of the Doctor's orders on the landing page: a recommended swap from one
// of the decks' stored reviews, with what the page needs to show it.
export type HubOrder = CutSwap & {
  deck_id: string;
  deck_title: string;
  rank_in_deck: number;
  cut_id: string | null;
  cut_inclusion: number | null;
  add_inclusion: number | null;
  add_synergy: number | null;
  deck_changed: boolean;
};

// A card from a newly released set that the Doctor thinks could work in a deck,
// and how.
export type Discovery = {
  name: string;
  id: string;
  why: string;
  works_with: string[];
  price_usd: string | null;
  mana_cost: string | null;
  type_line: string;
  rarity: string | null;
  set: string;
};

export type DeckDiscoveries = {
  generated_at: string;
  picks: Discovery[];
  // False once a newer set has been released than the one these were found in.
  current: boolean;
};

// -- the new-deck helper ------------------------------------------------------

export type WizardCommander = {
  name: string;
  id: string | null;
  num_decks: number;
  // Decks of this commander carrying the chosen theme; null when none is chosen.
  themed_decks: number | null;
  // Decks at the chosen power level; null when none is chosen.
  decks_at_bracket: number | null;
  bracket_counts: Record<string, number>;
  themes: { name: string; slug: string; count: number }[];
  signature: string[];
};

// fell_back_from: the style asked for, when there was no legal commander for it and the list shows the
// most-built ones in those colors instead.
export type WizardCandidates = {
  commanders: WizardCommander[];
  relaxed: boolean;
  unavailable: boolean;
  fell_back_from: string | null;
  // Lesser-known commanders were asked for but there were none to show, so
  // these are the usual most-built ones.
  niche_fallback: boolean;
};

export type WizardPlan = {
  commander: { name: string; id: string | null; price_usd: number };
  cards: { name: string; quantity: number; category: string; price_usd: number; id: string | null }[];
  card_count: number;
  total_price: number;
  budget: number | null;
  budget_reached: boolean;
  game_changers: string[];
  // What a tailoring request asked for: the cards that went in, the ones refused
  // (with why) and the ones taken out.
  included: string[];
  include_dropped: { name: string; reason: string }[];
  avoided: string[];
  category_counts: Record<string, number>;
  // What each part of the deck costs, the limit set on it (if any) and
  // whether it was marked to spend more on.
  spend: { area: string; label: string; price: number; cap: number | null; invest: boolean }[];
  variant: string;
  swaps: { out: string; in: string; saved: number }[];
  notes: string[];
};

// How the player wants the budget spent: a dollar limit for the parts they'd
// rather not spend on, and the parts to spend more on. Keys are wizardData's
// SPEND_AREAS slugs.
export type Spending = { caps: Record<string, number>; invest: string[] };

async function wizardGet<T>(path: string, params: Record<string, string | number | null | undefined>, failure: string): Promise<T> {
  const url = new URL(`${API_BASE}${path}`);
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined) url.searchParams.set(k, String(v));
  const res = await safeFetch(url);
  if (!res || !res.ok) {
    const body = await res?.json().catch(() => null);
    throw new Error(body?.detail ?? failure);
  }
  return res.json();
}

// How many commanders each theme has in these colours (null: couldn't be read).
export async function getWizardThemes(colors: string, themes: string[]): Promise<Record<string, number | null>> {
  const data = await wizardGet<{ counts: Record<string, number | null> }>(
    "/wizard/themes",
    { colors, themes: themes.join(",") },
    "Couldn't load the styles.",
  );
  return data.counts;
}

async function wizardPost<T>(path: string, body: unknown, failure: string): Promise<T> {
  const res = await safeFetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res || !res.ok) {
    const detail = await res?.json().catch(() => null);
    throw new Error(detail?.detail ?? failure);
  }
  return res.json();
}

// One sentence per commander on why it suits these answers.
export async function explainWizardCommanders(
  colors: string,
  theme: string | null,
  bracket: number | null,
  budget: number | null,
  niche: boolean,
): Promise<Record<string, string>> {
  const data = await wizardPost<{ reasons: Record<string, string> }>(
    "/wizard/explain",
    { colors, theme, bracket, budget, niche },
    "Couldn't explain these just now.",
  );
  return data.reasons;
}

export function getWizardCommanders(colors: string, theme: string | null, bracket: number | null, niche: boolean): Promise<WizardCandidates> {
  return wizardGet("/wizard/commanders", { colors, theme, bracket, niche: niche ? "true" : null }, "Couldn't load commanders.");
}

export function getWizardPreview(commander: string, bracket: number, budget: number | null, spending: Spending): Promise<WizardPlan> {
  const caps = Object.entries(spending.caps).map(([area, cap]) => `${area}:${cap}`).join(",");
  return wizardGet(
    "/wizard/preview",
    { commander, bracket, budget, caps: caps || null, invest: spending.invest.join(",") || null },
    "Couldn't build a starting list.",
  );
}

export async function buildWizardDeck(
  commander: string,
  bracket: number,
  budget: number | null,
  spending: Spending,
): Promise<{ deck: Deck; added: number; failed: { name: string; error: string }[]; notes: string[] }> {
  const res = await safeFetch(`${API_BASE}/wizard/build`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ commander, bracket, budget, caps: spending.caps, invest: spending.invest }),
  });
  if (!res || !res.ok) {
    const body = await res?.json().catch(() => null);
    throw new Error(body?.detail ?? "Couldn't build the deck.");
  }
  return res.json();
}

// What the player gave the new-deck page (every part optional) and said in their
// own words. null / empty / false mean "no preference".
export type BuildBrief = {
  text: string;
  styles: string[];
  colors: string[];
  colorless: boolean;
  theme: string | null;
  bracket: number | null;
  budget: number | "none" | null;
  caps: Record<string, number>;
  invest: string[];
  lesser_known: boolean;
  commander: string | null;
};

// One card the Doctor has chosen for a phase, and why.
export type BuildPick = { name: string; id: string | null; why: string; price: number; category: string; type: string; cmc: number };

export type BuildPhase = {
  id: string;
  kind: string;
  label: string;
  goal: string;
  count: number;
  // The Doctor's reason this phase is here, at this point in the order.
  why: string;
  status: "pending" | "ready" | "locked";
  locked: number;
  // What the Doctor said about the cards it chose, once it has chosen them.
  summary: string;
};

export type BuildCommanderOption = {
  name: string;
  id: string | null;
  why: string | null;
  // Its color identity as WUBRG letters; empty for colorless.
  colors: string;
  num_decks: number;
  decks_at_bracket: number | null;
  themes: string[];
  signature: string[];
  // Which of the Doctor's facts about what the player wants this one satisfies, and which it doesn't.
  fits: string[];
  misses: string[];
};

// One round of finding the commander: what the player said, what the Doctor made of it, what it offered.
export type BuildRound = {
  said: string | null;
  rejected: string[];
  liked: string[];
  understood: string;
  facts: string[];
  // How many commanders it looked at, how many of those the searches found, and — when the
  // searches found too few — the colors the rest were added from.
  considered: number;
  matched: number;
  topped_up: string | null;
  options: string[];
};

// What the player says to sharpen a round: more words, commanders ruled out (with why), commanders
// to find more like, and facts to take back.
export type BuildRefinement = {
  text: string;
  reject: { name: string; reason: string }[];
  like: string[];
  drop: string[];
};

// A deck being built with the Doctor, a phase at a time. The server holds it, so it
// survives a reload; the page follows it by asking.
export type Build = {
  id: string;
  stage: "reading" | "commander" | "planning" | "plan" | "building" | "review" | "done";
  // What the Doctor is doing right now, outside a phase's cards; null when idle.
  busy: string | null;
  // What it has done and is doing, in order, each tagged with the step it belongs to.
  steps: { during: string; label: string }[];
  // While it chooses the current phase's cards: what it is looking through.
  working_label: string | null;
  // What the player gave the new-deck page (without the styles list).
  brief: Omit<BuildBrief, "styles">;
  error: { status: number; detail: string; code: string; retry_after?: number | null } | null;
  resolved: { understood: string; notes: string[]; budget: number | null; bracket: number } | null;
  commander_options: BuildCommanderOption[];
  // What the Doctor has learnt about the commander wanted, the rounds so far, and what is ruled out.
  facts: string[];
  rounds: BuildRound[];
  rejected: { name: string; reason: string }[];
  liked: string[];
  commander: { name: string; id: string | null; why: string | null; price: number; colors: string[] } | null;
  plan: { strategy: string; order_reason: string; phases: BuildPhase[] } | null;
  current: string | null;
  proposal: { summary: string; cards: BuildPick[]; count: number; notes: string[]; basics: Record<string, number> | null } | null;
  // The Doctor is choosing the current phase's cards.
  working: boolean;
  deck: {
    count: number;
    price: number;
    by_category: Record<string, number>;
    cards: { name: string; id: string | null; phase: string; qty: number; price: number }[];
  };
  budget: number | null;
  deck_id: string | null;
};

async function buildRequest<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  const res = await safeFetch(`${API_BASE}${path}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res) throw new Error("Couldn't reach the Deck Doctor backend. Is it running on port 8000?");
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(data?.detail ?? "That didn't work.");
  return data;
}

export const startBuild = (brief: BuildBrief) => buildRequest<{ id: string }>("POST", "/builds", brief).then((r) => r.id);
export const getBuild = (id: string) => buildRequest<Build>("GET", `/builds/${id}`);
export const chooseBuildCommander = (id: string, name: string) => buildRequest<Build>("POST", `/builds/${id}/commander`, { name });
export const refineBuildCommander = (id: string, refinement: BuildRefinement) => buildRequest<Build>("POST", `/builds/${id}/commander/refine`, refinement);
export const beginBuild = (id: string) => buildRequest<Build>("POST", `/builds/${id}/begin`);
export const lockBuildPhase = (id: string, phase: string, keep: string[]) => buildRequest<Build>("POST", `/builds/${id}/phases/${phase}/lock`, { keep });
export const redoBuildPhase = (id: string, phase: string, remove: string[], note: string) =>
  buildRequest<Build>("POST", `/builds/${id}/phases/${phase}/redo`, { remove, note });
export const retryBuild = (id: string) => buildRequest<Build>("POST", `/builds/${id}/retry`);
export const createBuildDeck = (id: string) => buildRequest<{ deck: Deck; added: number; failed: { name: string; error: string }[] }>("POST", `/builds/${id}/create`);

// A commander from a newly released set that the Doctor thinks this player
// would enjoy building around. edhrec_decks and pairs_with are EDHREC's own
// numbers and top-synergy cards for it, not the Doctor's claims.
export type CommanderPick = {
  name: string;
  id: string;
  why: string;
  // Commanders of the player's own decks this one is in the spirit of; empty
  // when it is a different direction.
  like_decks: string[];
  price_usd: string | null;
  mana_cost: string | null;
  type_line: string;
  color_identity: string[];
  rarity: string | null;
  set: string;
  edhrec_decks: number | null;
  pairs_with: string[];
};

export type NewCommanders = {
  generated_at: string;
  picks: CommanderPick[];
  // False once a newer set is out, or the player's decks have changed.
  current: boolean;
};

export type HubDeck = {
  id: string;
  title: string;
  commander: string | null;
  commander_id: string | null;
  color_identity: string[];
  card_count: number;
  price_usd: number;
  updated_at: string;
  // null until the Doctor has looked through the newest sets for this deck.
  discoveries: DeckDiscoveries | null;
  // null until the Doctor has reviewed the deck.
  review: { swaps: number; kept: number; generated_at: string; deck_changed: boolean } | null;
};

export type Hub = {
  commanders: NewCommanders | null;
  // The newest two releases that have new cards: every set in them, and each release
  // on its own (a main set and its Commander set are one release), newest first.
  latest_sets: {
    released_at: string;
    sets: { code: string; name: string }[];
    releases: { released_at: string; title: string; sets: { code: string; name: string }[] }[];
  } | null;
  orders: HubOrder[];
  more_swaps: number;
  decks: HubDeck[];
};

// Has the Doctor look through the newest sets for commanders this player would
// enjoy (about a minute, costs tokens) and stores the result.
export async function refreshNewCommanders(): Promise<NewCommanders> {
  const res = await safeFetch(`${API_BASE}/commanders/new/refresh`, { method: "POST" });
  if (!res || !res.ok) {
    const body = await res?.json().catch(() => null);
    throw new Error(body?.detail ?? "Couldn't look through the new commanders. Try again.");
  }
  const data = await res.json();
  return data.commanders;
}

// Has the Doctor look through the newest sets for cards that could work in
// this deck (about a minute, costs tokens) and stores the result.
export async function refreshDiscoveries(deckId: string): Promise<DeckDiscoveries> {
  const res = await safeFetch(`${API_BASE}/decks/${deckId}/discoveries/refresh`, { method: "POST" });
  if (!res || !res.ok) {
    const body = await res?.json().catch(() => null);
    throw new Error(body?.detail ?? "Couldn't look through the new cards. Try again.");
  }
  const data = await res.json();
  return data.discoveries;
}

// Everything the landing page shows, in one read of what's stored — it never
// spends tokens.
export async function getHub(): Promise<Hub> {
  const res = await safeFetch(`${API_BASE}/hub`);
  if (!res || !res.ok) throw new Error("Couldn't load your decks.");
  return res.json();
}

// One card from EDHREC's per-commander data. inclusion is 0–1: the share of
// decks that *could* have played the card which did (num_decks /
// potential_decks), EDHREC's own definition.
export type EdhrecCard = {
  name: string;
  id: string | null;
  category: string;
  inclusion: number;
  synergy: number;
  lift: number;
  num_decks: number;
  potential_decks: number;
  game_changer: boolean;
  is_new: boolean;
};

export type CommanderIncludes =
  | { available: true; num_decks: number; cards: EdhrecCard[] }
  | { available: false; reason: string };

export async function getCommanderIncludes(commander: string): Promise<CommanderIncludes> {
  const res = await safeFetch(`${API_BASE}/edhrec/commander?name=${encodeURIComponent(commander)}`);
  if (!res || !res.ok) return { available: false, reason: "Couldn't reach the Deck Doctor backend." };
  return res.json();
}

// The user's owned-card collection — tracked by name only, no quantity or
// printing (see collection.py). A plain deduplicated set, not scoped to any
// deck, so it's fetched once per page rather than per deck.
export async function getCollection(): Promise<string[]> {
  const res = await safeFetch(`${API_BASE}/collection`);
  if (!res || !res.ok) throw new Error("Couldn't load your collection.");
  const data = await res.json();
  return data.cards;
}

export async function addToCollection(name: string): Promise<string[]> {
  const res = await safeFetch(`${API_BASE}/collection`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!res || !res.ok) throw new Error("Couldn't update your collection.");
  const data = await res.json();
  return data.cards;
}

// One backend call for the whole batch rather than one addToCollection per
// card — avoids firing dozens of overlapping requests at a JSON file with
// no per-write locking (same read-modify-write race noted for deck.py).
export async function addManyToCollection(names: string[]): Promise<string[]> {
  const res = await safeFetch(`${API_BASE}/collection/bulk`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ names }),
  });
  if (!res || !res.ok) throw new Error("Couldn't update your collection.");
  const data = await res.json();
  return data.cards;
}

export async function removeFromCollection(name: string): Promise<string[]> {
  const url = new URL(`${API_BASE}/collection`);
  url.searchParams.set("name", name);
  const res = await safeFetch(url, { method: "DELETE" });
  if (!res || !res.ok) throw new Error("Couldn't update your collection.");
  const data = await res.json();
  return data.cards;
}

// Confirmed via Scryfall's /symbology endpoint: mana symbol SVGs are served
// at this predictable path, one file per WUBRG letter (plus C for colorless).
export function scryfallManaSymbolUrl(letter: string): string {
  return `https://svgs.scryfall.io/card-symbols/${letter}.svg`;
}

// Card art is served straight from Scryfall's image host, keyed by the
// card's own id — never through api.scryfall.com. The API's
// /cards/named?format=image redirect (what this used to be) is the
// rate-limited 2/sec endpoint, so a page of tiles (or one lazy-load burst)
// tripped a 429 and rendered broken images; Scryfall's docs state the
// *.scryfall.io hosts have no rate limit at all. This URL is exactly the
// official image_uris front-face URL minus its trailing ?timestamp
// cache-buster (verified by curl for normal, transform and split cards),
// and the host sends cache-control max-age of a year, so the browser's own
// cache keeps every image after the first load. Front face only, same as
// the redirect it replaces.
export type ImageVersion = "small" | "normal" | "art_crop";

export function scryfallImageUrlById(id: string, version: ImageVersion = "small"): string {
  return `https://cards.scryfall.io/${version}/front/${id[0]}/${id[1]}/${id}.jpg`;
}

export type Printing = { id: string; setName: string; releasedAt: string | null; priceUsd: string | null };

// Every printing of a card by exact name, newest first, via the backend's
// cache (card_details.py) rather than a Scryfall search from the browser on
// every picker open. Only the first results page (175) — plenty for
// virtually any card; only heavily-reprinted basics have more. null means
// the lookup failed with nothing cached — distinct from [], a real "no
// printings found".
export async function getPrintings(name: string): Promise<Printing[] | null> {
  const res = await safeFetch(`${API_BASE}/cards/printings?name=${encodeURIComponent(name)}`);
  if (!res || !res.ok) return null;
  return (await res.json()).printings;
}

export async function scryfallAutocomplete(query: string): Promise<string[]> {
  if (query.trim().length < 2) return [];
  const res = await safeFetch(`https://api.scryfall.com/cards/autocomplete?q=${encodeURIComponent(query)}`);
  if (!res || !res.ok) return [];
  const data = await res.json();
  return data.data ?? [];
}

export type CardInfo = {
  id: string | null;
  typeLine: string | null;
  priceUsd: string | null;
  // Scryfall's own legalities.commander value: "legal" | "not_legal" |
  // "banned" | "restricted".
  legality: string | null;
  oracleText: string | null;
};

// Used to bucket the ledger by card type (Creatures/Instants/Lands/...), to
// total up the deck's price, and to fill in the card detail modal (price/
// legality/oracle text/id). Unlike every other Scryfall-ish call in this
// file, this one goes through our *own* backend (see card_cache.py)
// instead of hitting Scryfall directly from the browser — a card's type
// line/oracle text/legality essentially never change and price moves
// slowly, so there's no reason to re-fetch the same ~100 deck names from
// Scryfall on every single page load, which is what was reliably tripping
// Scryfall's rate limit on ordinary use of a full deck. The backend
// caches by name and serves the cache on every call unless `refresh` is
// set (wired to a "Refresh card data" action, not a default).
export async function getCardInfo(name: string, refresh = false): Promise<CardInfo | null> {
  const params = new URLSearchParams({ name });
  if (refresh) params.set("refresh", "1");
  const res = await safeFetch(`${API_BASE}/cards?${params.toString()}`);
  if (!res || !res.ok) return null;
  const data = await res.json();
  return data.info;
}

export type CardInfoBatchResult = {
  info: Record<string, CardInfo>;
  // Confirmed Scryfall 404s (genuinely not a real card / a typo) versus
  // names a lookup attempt simply failed on (almost always the rate
  // limit, worth retrying) — see card_cache.py's own docstring. A plain
  // "is this name in info" check can't tell these apart, which matters a
  // lot right after a big batch (importing a pasted decklist): a
  // rate-limited burst shouldn't read as "half these names are typos".
  notFound: string[];
  failed: string[];
};

export async function getCardInfoBatch(names: string[], refresh = false): Promise<CardInfoBatchResult> {
  if (names.length === 0) return { info: {}, notFound: [], failed: [] };
  const res = await safeFetch(`${API_BASE}/cards/batch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ names, refresh }),
  });
  if (!res || !res.ok) return { info: {}, notFound: [], failed: [...names] };
  const data = await res.json();
  return { info: data.info, notFound: data.not_found, failed: data.failed };
}

export type Ruling = { source: string; publishedAt: string; comment: string };

// Rulings live at a separate Scryfall endpoint keyed by the card's own id
// (confirmed via its `rulings_uri` field), not on the card object itself —
// fetched lazily when the card detail modal opens rather than folded into
// getCardInfo's batch fetch, since most cards have none and the whole
// deck doesn't need them up front. Served from the backend's cache
// (card_details.py); null means the lookup failed with nothing cached,
// distinct from [] ("this card has no rulings").
export async function getRulings(id: string): Promise<Ruling[] | null> {
  const res = await safeFetch(`${API_BASE}/cards/rulings?id=${encodeURIComponent(id)}`);
  if (!res || !res.ok) return null;
  return (await res.json()).rulings;
}

export type SearchCard = {
  id: string;
  name: string;
  typeLine: string | null;
  priceUsd: string | null;
  colorIdentity: string[];
};

export type SearchResult = { cards: SearchCard[]; hasMore: boolean; totalCards: number };

// The card-search page's browser, built on Scryfall's own search syntax
// (confirmed piece by piece via curl: bare terms match name, c:/id: default
// to "at least these colors" with =/<=/>= for exact/subset/superset, cmc
// range is two separate clauses, t:/o:/set: are substring-ish operators).
// A search with zero matches is a real, valid outcome Scryfall reports as
// an HTTP 404 with code "not_found" — distinguished here from an actual
// request failure so the page can show "no results" instead of an error.
export type SortOrder = "name" | "usd" | "color";
export type SortDir = "asc" | "desc";

// order=color/usd confirmed via curl alongside the default order=name —
// Scryfall sorts color in WUBRG order (ascending starts at White) and usd
// by real market price.
export async function scryfallSearchCards(
  query: string,
  page: number,
  order: SortOrder = "name",
  dir: SortDir = "asc",
): Promise<SearchResult> {
  const params = new URLSearchParams({ q: query, order, dir, page: String(page) });
  const res = await safeFetch(`https://api.scryfall.com/cards/search?${params.toString()}`);
  if (!res) throw new Error("Search failed. Try again.");
  if (res.status === 404) return { cards: [], hasMore: false, totalCards: 0 };
  if (!res.ok) throw new Error("Search failed. Try again.");
  const data = await res.json();
  return {
    cards: (data.data ?? []).map(
      (c: { id: string; name: string; type_line?: string; prices?: { usd?: string }; color_identity?: string[] }) => ({
        id: c.id,
        name: c.name,
        typeLine: c.type_line ?? null,
        priceUsd: c.prices?.usd ?? null,
        colorIdentity: c.color_identity ?? [],
      }),
    ),
    hasMore: data.has_more ?? false,
    totalCards: data.total_cards ?? 0,
  };
}

// "Only my collection" folds the owned-card list into the query as an
// exact-name OR-clause, ANDed onto whatever real filter is already
// there (or standing alone with none) — but Scryfall's parser hard-caps
// a query at around 36 boolean terms (confirmed via curl: a 36-name
// clause parses fine, 37 fails with "Your search contains unclosed
// parentheses", regardless of query length or how the terms are
// grouped/nested). COLLECTION_CHUNK_SIZE stays well under that so a
// query with several other real filter terms still has headroom, and
// each chunk needs only one Scryfall request (a chunk of exact names can
// never match more than its own size, well under one results page).
const COLLECTION_CHUNK_SIZE = 25;

function collectionClause(names: string[]): string {
  return `(${names.map((name) => `!"${name}"`).join(" or ")})`;
}

function chunk<T>(items: T[], size: number): T[][] {
  const chunks: T[][] = [];
  for (let i = 0; i < items.length; i += size) chunks.push(items.slice(i, i + size));
  return chunks;
}

// Computes the true, complete intersection of a (possibly empty) real
// Scryfall query with the owned-card list, so a caller can sort/paginate
// the *whole* matching set locally — never a page that's empty just
// because the matches happened to sort onto a different Scryfall page.
export async function scryfallSearchOwnedCards(query: string, ownedNames: string[]): Promise<SearchCard[]> {
  if (ownedNames.length === 0) return [];
  const chunks = chunk(ownedNames, COLLECTION_CHUNK_SIZE);
  const results: SearchCard[] = [];
  const concurrency = 4;
  for (let i = 0; i < chunks.length; i += concurrency) {
    const batch = chunks.slice(i, i + concurrency);
    const fetched = await Promise.all(
      batch.map((names) => scryfallSearchCards(query ? `${query} ${collectionClause(names)}` : collectionClause(names), 1)),
    );
    fetched.forEach((r) => results.push(...r.cards));
  }
  return results;
}

export type ScryfallSet = { code: string; name: string };

// Set types excluded here are ones that don't help a deckbuilder narrow
// down a search (blank-backed tokens, box toppers, oversized vanguard/
// archenemy cards) — everything else (expansions, core sets, Commander
// precons, masters/reprint sets, etc.) stays.
const IRRELEVANT_SET_TYPES = new Set(["token", "memorabilia", "minigame", "vanguard"]);

let cachedSets: ScryfallSet[] | null = null;

// Fetched once per session and cached in memory — the set list (1000+
// entries) doesn't change while the app is open, and every visit to the
// search page needs it for the set filter's dropdown.
export async function scryfallSets(): Promise<ScryfallSet[]> {
  if (cachedSets) return cachedSets;
  const res = await safeFetch("https://api.scryfall.com/sets");
  if (!res || !res.ok) return [];
  const data = await res.json();
  const sets = (data.data ?? [])
    .filter((s: { set_type: string; digital: boolean }) => !IRRELEVANT_SET_TYPES.has(s.set_type) && !s.digital)
    .map((s: { code: string; name: string }) => ({ code: s.code, name: s.name }));
  cachedSets = sets;
  return sets;
}
