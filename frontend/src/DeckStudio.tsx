import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  beginBuild,
  buildWizardDeck,
  chooseBuildCommander,
  createBuildDeck,
  createDeck,
  explainWizardCommanders,
  getBuild,
  getWizardCommanders,
  getWizardPreview,
  getWizardThemes,
  lockBuildPhase,
  redoBuildPhase,
  refineBuildCommander,
  retryBuild,
  startBuild,
  type Build,
  type Spending,
  type WizardCandidates,
  type WizardPlan as Plan,
} from "./api";
import { useAiProblem } from "./aiStatus";
import AiNotice, { useSecondsUntil } from "./AiNotice";
import CommandersModal from "./CommandersModal";
import { CommanderBody, ErrorBody, LockedPhaseBody, PhaseBody, PlanBody, ReviewBody, money, type CommanderSteer } from "./StudioBodies";
import BriefCard from "./StudioBrief";
import { ActionDock, DeckDrawer, RefineDock, SteerDock, StudioBar, type RailItem } from "./StudioChrome";
import { Group, Station, Thinking } from "./StudioStation";
import {
  ALL_STYLE_SLUGS,
  BRACKETS,
  CREATURE_TYPES,
  DEFAULT_BRACKET,
  SPEND_AREAS,
  STRATEGIES,
  canonicalColors,
  colorComboName,
  defaultCap,
  type SpendMode,
} from "./wizardData";
import WizardPlan from "./WizardPlan";
import "./wizard.css";
import "./build.css";
import "./studio.css";

// Where the build in progress is remembered, to offer to carry on with it.
const LAST_BUILD = "mtg-deck-doctor:lastBuild";

// The first sentence of `text`, kept short, ending at a word.
function firstSentence(text: string): string {
  const sentence = text.match(/^.*?[.!?](?=\s|$)/)?.[0] ?? text;
  if (sentence.length <= 130) return sentence;
  return `${sentence.slice(0, 130).replace(/\s+\S*$/, "")}…`;
}

// The chips that say what a brief contained, for the folded first station.
function briefChips(b: Build["brief"]): string[] {
  const chips: string[] = [];
  if (b.commander) chips.push(b.commander.split(",")[0]);
  else {
    if (b.colorless) chips.push("Colorless");
    else if (b.colors.length) chips.push(colorComboName(b.colors));
    const style = [...STRATEGIES, ...CREATURE_TYPES].find((s) => s.slug === b.theme);
    if (style) chips.push(style.label);
    if (b.lesser_known) chips.push("Lesser-known commanders");
  }
  if (b.bracket) chips.push(`${BRACKETS.find((x) => x.n === b.bracket)!.label} power`);
  if (b.budget !== null) chips.push(b.budget === "none" ? "No budget limit" : `Up to $${b.budget}`);
  for (const a of SPEND_AREAS) {
    if (a.slug in b.caps) chips.push(`${a.label} ≤ $${b.caps[a.slug]}`);
    if (b.invest.includes(a.slug)) chips.push(`More on ${a.label.toLowerCase()}`);
  }
  return chips;
}

// What there is on screen to type out when it first shows, so opening a build again doesn't
// replay what was already said.
function spokenKeys(b: Build): string[] {
  const keys: string[] = [];
  if (b.resolved) keys.push("understood");
  if (b.rounds.length) keys.push(`round:${b.rounds.length}`);
  if (b.plan) keys.push("plan");
  for (const p of b.plan?.phases ?? []) if (p.summary) keys.push(`phase:${p.id}`);
  return keys;
}

// The deck studio. One page that is the whole process of making a deck with the Doctor: a
// timeline of stations — your brief, the commander, the plan, each phase the Doctor chose, the
// review — with what's done folded up, what's open in front of you, and what's still to
// come dimmed behind. It's the same page from the first word to the last (/new, then
// /new/:id as the build is saved), so nothing jumps.
export default function DeckStudio() {
  const navigate = useNavigate();
  const { buildId } = useParams();
  const [params] = useSearchParams();

  // The brief: every part optional. null / empty / false are "no preference".
  const [ask, setAsk] = useState("");
  const [letters, setLetters] = useState<string[]>([]);
  const [colorless, setColorless] = useState(false);
  const [theme, setTheme] = useState<string | null>(null);
  const [bracket, setBracket] = useState<number | null>(null);
  const [budget, setBudget] = useState<number | "none" | null>(null);
  const [lesserKnown, setLesserKnown] = useState(false);
  const [spendMode, setSpendMode] = useState<Record<string, SpendMode>>({});
  const [capValue, setCapValue] = useState<Record<string, number>>({});
  const [chosen, setChosen] = useState<string | null>(params.get("commander"));

  const level = bracket ?? DEFAULT_BRACKET;
  const budgetCap = typeof budget === "number" ? budget : null;
  const colorKey = colorless ? "" : canonicalColors(letters);
  const hasColors = colorless || letters.length > 0;
  const themeStyle = [...STRATEGIES, ...CREATURE_TYPES].find((s) => s.slug === theme) ?? null;

  // Spending more only means something with a budget to spend from.
  const spending: Spending = useMemo(() => {
    const caps: Record<string, number> = {};
    const invest: string[] = [];
    for (const a of SPEND_AREAS) {
      const mode = spendMode[a.slug] ?? "normal";
      if (mode === "cheap") caps[a.slug] = capValue[a.slug] ?? defaultCap(a.slug, budgetCap);
      else if (mode === "invest" && budgetCap !== null) invest.push(a.slug);
    }
    return { caps, invest };
  }, [spendMode, capValue, budgetCap]);

  // The build the Doctor is making with us, followed by asking while it works.
  const [build, setBuild] = useState<Build | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [acting, setActing] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [removed, setRemoved] = useState<Set<string>>(new Set());
  const [note, setNote] = useState("");
  const [deckOpen, setDeckOpen] = useState(false);
  // What is staged for the next round of finding the commander: words, commanders ruled out
  // (with why) or liked, facts taken back. All of it goes when the player asks for another look.
  const [refineText, setRefineText] = useState("");
  const [rejecting, setRejecting] = useState<Record<string, string>>({});
  const [liking, setLiking] = useState<Set<string>>(new Set());
  const [dropping, setDropping] = useState<Set<string>>(new Set());

  // Starting the Doctor on the brief. After a failure the button waits a few seconds, so a
  // problem isn't hammered.
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [startWaitUntil, setStartWaitUntil] = useState<number | null>(null);
  const aiProblem = useAiProblem();
  const aiWait = useSecondsUntil(aiProblem?.until ?? null);
  const startWait = useSecondsUntil(startWaitUntil);
  const aiNeedsFixing = aiProblem !== null && aiProblem.until === null;
  const startLocked = starting || aiNeedsFixing || aiWait > 0 || startWait > 0;

  // A build left unfinished, to carry on with.
  const [resume, setResume] = useState<Build | null>(null);

  // Text the Doctor says is typed out the first time it appears, but not when a build is opened again.
  const startedHere = useRef(false);
  const quiet = useRef<Set<string> | null>(null);
  const animate = (key: string) => !(quiet.current?.has(key) ?? false);

  useEffect(() => {
    if (!startedHere.current) quiet.current = null;
    startedHere.current = false;
    setRemoved(new Set());
    setNote("");
    if (!buildId) setBuild(null);
  }, [buildId]);

  useEffect(() => {
    if (buildId) return;
    let id: string | null = null;
    try {
      id = localStorage.getItem(LAST_BUILD);
    } catch {
      /* no memory of one */
    }
    if (!id) return;
    let cancelled = false;
    getBuild(id)
      .then((b) => !cancelled && b.stage !== "done" && !(b.stage === "reading" && b.error) && setResume(b))
      .catch(() => {
        try {
          localStorage.removeItem(LAST_BUILD);
        } catch {
          /* nothing to forget */
        }
      });
    return () => {
      cancelled = true;
    };
  }, [buildId]);

  // Ask while the Doctor is working; stop when it is waiting on the player.
  useEffect(() => {
    if (!buildId) return;
    let cancelled = false;
    let timer: number | undefined;
    async function tick() {
      try {
        const b = await getBuild(buildId!);
        if (cancelled) return;
        if (quiet.current === null) quiet.current = new Set(spokenKeys(b));
        setBuild(b);
        setLoadError(null);
        const busy = !!b.busy || b.working || b.stage === "reading" || b.stage === "planning" || (b.stage === "building" && !b.proposal);
        if (busy && !b.error) timer = window.setTimeout(tick, 1400);
      } catch (err) {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : "Couldn't load this build.");
      }
    }
    tick();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [buildId, nonce]);

  // A new round starts with nothing staged.
  const roundKey = build ? `${build.id}|${build.rounds.length}` : "";
  useEffect(() => {
    setRefineText("");
    setRejecting({});
    setLiking(new Set());
    setDropping(new Set());
  }, [roundKey]);

  // A new proposal starts with everything kept and nothing asked.
  const proposalKey = build?.proposal ? build.proposal.cards.map((c) => c.name).join("|") : "";
  useEffect(() => {
    setRemoved(new Set());
    setNote("");
  }, [build?.current, proposalKey]);

  // Style counts for the colors picked, and the commanders that fit, to pick from yourself.
  const [themeCounts, setThemeCounts] = useState<Record<string, number | null> | null>(null);
  useEffect(() => {
    if (!hasColors || chosen || buildId) {
      setThemeCounts(null);
      return;
    }
    let cancelled = false;
    setThemeCounts(null);
    getWizardThemes(colorKey, ALL_STYLE_SLUGS)
      .then((counts) => {
        if (cancelled) return;
        setThemeCounts(counts);
        // A style with no commanders in the new colors can't stay chosen.
        setTheme((t) => (t && counts[t] === 0 ? null : t));
      })
      .catch(() => !cancelled && setThemeCounts({}));
    return () => {
      cancelled = true;
    };
  }, [colorKey, hasColors, chosen, buildId]);

  const [browsing, setBrowsing] = useState(false);
  const [candidates, setCandidates] = useState<WizardCandidates | null>(null);
  const [explained, setExplained] = useState<{ key: string; reasons: Record<string, string> } | null>(null);
  const [explaining, setExplaining] = useState(false);
  const [explainError, setExplainError] = useState<string | null>(null);
  useEffect(() => {
    if (!browsing || !hasColors || chosen) return;
    let cancelled = false;
    setCandidates(null);
    getWizardCommanders(colorKey, theme, level, lesserKnown)
      .then((found) => !cancelled && setCandidates(found))
      .catch(() => !cancelled && setCandidates({ commanders: [], relaxed: false, unavailable: true, fell_back_from: null, niche_fallback: false }));
    return () => {
      cancelled = true;
    };
  }, [browsing, colorKey, hasColors, theme, level, lesserKnown, chosen]);
  const explainKey = `${colorKey}|${theme}|${level}|${budgetCap}|${lesserKnown}`;
  async function explain() {
    setExplaining(true);
    setExplainError(null);
    try {
      setExplained({ key: explainKey, reasons: await explainWizardCommanders(colorKey, theme, level, budgetCap, lesserKnown) });
    } catch (err) {
      setExplainError(err instanceof Error ? err.message : "Couldn't explain these just now.");
    } finally {
      setExplaining(false);
    }
  }
  const reasons = explained?.key === explainKey ? explained.reasons : null;

  // A plain starting list for the chosen commander, from the rules alone — no model.
  const [starter, setStarter] = useState<{ plan: Plan | null; error: string | null } | null>(null);
  const [building, setBuilding] = useState(false);
  const [buildError, setBuildError] = useState<string | null>(null);
  async function showStarter() {
    if (!chosen) return;
    setStarter({ plan: null, error: null });
    setBuildError(null);
    try {
      setStarter({ plan: await getWizardPreview(chosen, level, budgetCap, spending), error: null });
    } catch (err) {
      setStarter({ plan: null, error: err instanceof Error ? err.message : "Couldn't build a starting list." });
    }
  }
  async function buildStarter() {
    setBuilding(true);
    setBuildError(null);
    try {
      navigate(`/decks/${(await buildWizardDeck(chosen!, level, budgetCap, spending)).deck.id}`);
    } catch (err) {
      setBuildError(err instanceof Error ? err.message : "Couldn't build the deck.");
      setBuilding(false);
    }
  }
  async function startEmpty() {
    try {
      navigate(`/decks/${(await createDeck()).id}`);
    } catch {
      /* nothing was made */
    }
  }

  // Everything in the brief goes to the Doctor, which starts on it; this page carries on as the build.
  async function start() {
    if (startLocked) return;
    setStarting(true);
    setStartError(null);
    try {
      const id = await startBuild({
        text: ask,
        styles: ALL_STYLE_SLUGS,
        colors: chosen ? [] : letters,
        colorless: chosen ? false : colorless,
        theme: chosen ? null : theme,
        bracket,
        budget,
        caps: spending.caps,
        invest: spending.invest,
        lesser_known: chosen ? false : lesserKnown,
        commander: chosen,
      });
      try {
        localStorage.setItem(LAST_BUILD, id);
      } catch {
        /* the build still goes ahead */
      }
      startedHere.current = true;
      quiet.current = new Set();
      navigate(`/new/${id}`, { replace: true });
    } catch (err) {
      setStartError(err instanceof Error ? err.message : "The Doctor couldn't start on that.");
      setStartWaitUntil(Date.now() + 3000);
    } finally {
      setStarting(false);
    }
  }

  // Back to the brief with everything as it was typed, for a build that couldn't start on it.
  function backToBrief() {
    try {
      localStorage.removeItem(LAST_BUILD);
    } catch {
      /* nothing to forget */
    }
    setBuild(null);
    navigate("/new");
  }

  function newBrief() {
    setAsk("");
    setLetters([]);
    setColorless(false);
    setTheme(null);
    setBracket(null);
    setBudget(null);
    setLesserKnown(false);
    setSpendMode({});
    setChosen(null);
    setStarter(null);
    navigate("/new");
  }

  // Does something to the build and shows what it comes to.
  const act = useCallback(async (run: () => Promise<Build>) => {
    setActing(true);
    setActionError(null);
    try {
      setBuild(await run());
      setNonce((n) => n + 1);
      return true;
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "That didn't work.");
      return false;
    } finally {
      setActing(false);
    }
  }, []);

  async function makeDeck() {
    setActing(true);
    setActionError(null);
    try {
      const made = await createBuildDeck(buildId!);
      try {
        localStorage.removeItem(LAST_BUILD);
      } catch {
        /* nothing to forget */
      }
      navigate(`/decks/${made.deck.id}`);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Couldn't make the deck.");
      setActing(false);
    }
  }

  // Bring the open station into view as the build moves along.
  const focusKey = build ? `${build.stage}|${build.current}|${build.proposal ? 1 : 0}|${build.working ? 1 : 0}|${build.rounds.length}|${build.stage === "commander" && build.busy ? 1 : 0}` : "";
  useEffect(() => {
    if (!focusKey) return;
    const el = document.querySelector('[data-state="current"][data-station]');
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [focusKey]);

  // ---- what the timeline shows -------------------------------------------------------------

  if (buildId && !build) {
    return loadError ? (
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ color: "var(--danger)" }}>{loadError}</div>
        <button className="text-link" style={{ textAlign: "left" }} onClick={newBrief}>
          Start a new deck
        </button>
      </div>
    ) : (
      <div className="station-note">Loading…</div>
    );
  }
  if (build?.stage === "done" && build.deck_id) return <Navigate to={`/decks/${build.deck_id}`} replace />;

  if (starter) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        <div>
          <button className="text-link" onClick={() => setStarter(null)}>
            ← Back to the brief
          </button>
          <h1 style={{ fontSize: 30, fontWeight: 600, margin: "8px 0 0" }}>Your starting list</h1>
        </div>
        {!starter.plan && !starter.error && <div className="panel" style={{ borderStyle: "dashed", animation: "pulse 1.6s ease-in-out infinite" }}>Putting together a starting list for {chosen}…</div>}
        {starter.error && <div style={{ color: "var(--danger)" }}>{starter.error}</div>}
        {starter.plan && <WizardPlan plan={starter.plan} building={building} buildError={buildError} onBuild={buildStarter} />}
      </div>
    );
  }

  const stage = build?.stage ?? "intro";
  const phases = build?.plan?.phases ?? [];
  const current = phases.find((p) => p.id === build?.current);
  const phaseIndex = current ? phases.indexOf(current) : -1;
  const spoken = (key: string) => animate(key);

  const states = {
    brief: build ? "done" : "current",
    commander: !build ? "todo" : stage === "reading" || stage === "commander" ? "current" : "done",
    plan: !build || stage === "reading" || stage === "commander" ? "todo" : stage === "planning" || stage === "plan" ? "current" : "done",
    review: stage === "review" ? "current" : stage === "done" ? "done" : "todo",
  } as const;

  const rail: RailItem[] = [
    { key: "brief", label: "Your brief", weight: 7, state: states.brief },
    { key: "commander", label: "Commander", weight: 7, state: states.commander },
    { key: "plan", label: "Plan", weight: 7, state: states.plan },
    ...(phases.length
      ? phases.map((p) => ({
          key: p.id,
          label: `${p.label} · ${p.count}`,
          weight: p.count,
          state: (p.status === "locked" ? "done" : build?.current === p.id && stage === "building" ? "current" : "todo") as RailItem["state"],
        }))
      : [{ key: "phases", label: "The phases", weight: 40, state: "todo" as const }]),
    { key: "review", label: "Review", weight: 7, state: states.review },
  ];
  const railLabel =
    stage === "intro"
      ? "Step 1 of 3 · Your brief"
      : stage === "reading" || stage === "commander"
        ? "Step 2 of 3 · The commander"
        : stage === "planning" || stage === "plan"
          ? "Step 3 of 3 · The plan"
          : stage === "building" && current
            ? `Phase ${phaseIndex + 1} of ${phases.length} · ${current.label}`
            : stage === "review"
              ? "Last step · Review"
              : "";

  // A step that failed shows why where it happened, instead of its spinner.
  const errorHere = build?.error ? (
    <ErrorBody key={build.error.detail} error={build.error} acting={acting} onRetry={() => act(() => retryBuild(build.id))} onBack={stage === "reading" || stage === "planning" ? backToBrief : undefined} />
  ) : null;
  const stepsFor = (during: string) => (build?.steps ?? []).filter((s) => s.during === during).map((s) => s.label);
  const phasePrice = (id: string) => build?.deck.cards.filter((c) => c.phase === id).reduce((n, c) => n + c.price * c.qty, 0) ?? 0;
  const phaseCount = (id: string) => build?.deck.cards.filter((c) => c.phase === id).reduce((n, c) => n + c.qty, 0) ?? 0;

  const notice =
    aiProblem && (aiNeedsFixing || aiWait > 0) ? (
      <AiNotice message={aiProblem.message} secondsLeft={aiWait} canCheck={aiNeedsFixing} />
    ) : (
      startError && <AiNotice message={startError} secondsLeft={startWait} canCheck={false} />
    );

  const heading = [colorless ? "Colorless" : hasColors ? colorComboName(letters) : "Any colors", themeStyle?.label, `${BRACKETS.find((b) => b.n === level)!.label} power`].filter(Boolean).join(" · ");
  const keptNames = build?.proposal ? build.proposal.cards.filter((c) => !removed.has(c.name)).map((c) => c.name) : [];
  const steer: CommanderSteer = {
    rejecting,
    liking,
    dropping,
    onReject: (name) => {
      setRejecting((prev) => {
        const next = { ...prev };
        if (name in next) delete next[name];
        else next[name] = "";
        return next;
      });
      setLiking((prev) => {
        const next = new Set(prev);
        next.delete(name);
        return next;
      });
    },
    onReason: (name, reason) => setRejecting((prev) => ({ ...prev, [name]: reason })),
    onLike: (name) => {
      setLiking((prev) => {
        const next = new Set(prev);
        if (!next.delete(name)) next.add(name);
        return next;
      });
      setRejecting((prev) => {
        const next = { ...prev };
        delete next[name];
        return next;
      });
    },
    onDrop: (fact) =>
      setDropping((prev) => {
        const next = new Set(prev);
        if (!next.delete(fact)) next.add(fact);
        return next;
      }),
  };
  const stagedWords = [
    Object.keys(rejecting).length ? `ruling out ${Object.keys(rejecting).length}` : "",
    liking.size ? `more like ${liking.size}` : "",
    dropping.size ? `taking back ${dropping.size} ${dropping.size === 1 ? "fact" : "facts"}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const choosing = stage === "commander" && !!build;
  function lookAgain() {
    if (!build) return;
    act(() =>
      refineBuildCommander(build.id, {
        text: refineText.trim(),
        reject: Object.entries(rejecting).map(([name, reason]) => ({ name, reason: reason.trim() })),
        like: [...liking],
        drop: [...dropping],
      }),
    );
  }
  const proposalReady = stage === "building" && !!build?.proposal && !build.working && !build.error;
  const toggleRemoved = (name: string) =>
    setRemoved((prev) => {
      const next = new Set(prev);
      if (!next.delete(name)) next.add(name);
      return next;
    });

  return (
    <div className="studio">
      <StudioBar title={build?.commander?.name ?? "New deck"} rail={rail} railLabel={railLabel} build={build} onDeck={() => setDeckOpen(true)} onNew={newBrief} />

      <div className="timeline">
        {!build && resume && (
          <div className="panel" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 14, flexWrap: "wrap", marginBottom: 22, borderColor: "var(--accent-gold)" }}>
            <div>
              <div style={{ fontWeight: 600 }}>You have a deck in progress{resume.commander ? `: ${resume.commander.name}` : ""}</div>
              <div className="station-note">{resume.plan ? `${resume.deck.count} of 99 cards chosen.` : "The Doctor is getting started."}</div>
            </div>
            <button className="go" onClick={() => navigate(`/new/${resume.id}`)}>
              Carry on
            </button>
          </div>
        )}

        <Group label="SET UP" />

        <Station
          id="brief"
          state={states.brief}
          node="1"
          kicker="STEP 1"
          title="Your brief"
          note={build ? firstSentence(build.brief.text || "Left to the Doctor.") : "Say what you want and set what you already know."}
        >
          {build ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {build.brief.text && <div style={{ fontSize: 16, lineHeight: 1.6 }}>“{build.brief.text}”</div>}
              <div className="mini-chips" style={{ marginTop: 0 }}>
                {briefChips(build.brief).map((c) => (
                  <span key={c} className="mini-chip">
                    {c}
                  </span>
                ))}
              </div>
              {build.resolved && <div className="station-note">{build.resolved.understood}</div>}
            </div>
          ) : (
            <BriefCard
              ask={ask}
              onAsk={setAsk}
              letters={letters}
              colorless={colorless}
              onToggleColor={(l) => {
                setColorless(false);
                setLetters((prev) => (prev.includes(l) ? prev.filter((x) => x !== l) : [...prev, l]));
              }}
              onColorless={() => {
                setLetters([]);
                setColorless((v) => !v);
              }}
              onClearColors={() => {
                setLetters([]);
                setColorless(false);
              }}
              theme={theme}
              onTheme={setTheme}
              themeCounts={themeCounts}
              lesserKnown={lesserKnown}
              onLesserKnown={setLesserKnown}
              bracket={bracket}
              onBracket={setBracket}
              budget={budget}
              onBudget={setBudget}
              budgetCap={budgetCap}
              spendMode={spendMode}
              spending={spending}
              onSpendMode={(slug, mode) => setSpendMode((m) => ({ ...m, [slug]: mode }))}
              onCap={(slug, cap) => setCapValue((c) => ({ ...c, [slug]: cap }))}
              chosen={chosen}
              onChooseCommander={setChosen}
              onClearCommander={() => setChosen(null)}
              onBrowse={() => setBrowsing(true)}
              locked={startLocked}
              starting={starting}
              notice={notice}
              onStart={start}
              onStarter={showStarter}
              onEmpty={startEmpty}
            />
          )}
        </Station>

        <Station
          id="commander"
          state={states.commander}
          node="2"
          kicker="STEP 2"
          title="Commander"
          note={
            states.commander === "done" && build?.commander
              ? build.commander.name
              : "The Doctor offers a few, and every answer you give sharpens the search."
          }
        >
          {states.commander === "current" && build && (
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              {stage === "reading" && errorHere ? (
                errorHere
              ) : stage === "reading" ? (
                <Thinking steps={stepsFor("start").length ? stepsFor("start") : ["Reading what you asked for…"]} />
              ) : (
                <CommanderBody
                  build={build}
                  animate={spoken(`round:${build.rounds.length}`)}
                  acting={acting}
                  steer={steer}
                  notice={build.error ? errorHere : build.busy ? <Thinking steps={stepsFor("refine").length ? stepsFor("refine") : [build.busy]} /> : null}
                  onChoose={(name) => act(() => chooseBuildCommander(build.id, name))}
                />
              )}
            </div>
          )}
          {states.commander === "done" && build?.commander && (
            <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "flex-start", fontSize: 15, lineHeight: 1.6 }}>
              <div style={{ flex: 1, minWidth: 240 }}>
                <div>{build.commander.why ?? "You chose this commander."}</div>
                {build.facts.length > 0 && (
                  <div className="mini-chips">
                    {build.facts.map((f) => (
                      <span key={f} className="mini-chip">
                        {f}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </Station>

        <Station
          id="plan"
          state={states.plan}
          node="3"
          kicker="STEP 3"
          title="The plan"
          note={states.plan === "done" && build?.plan ? firstSentence(build.plan.strategy) : "The Doctor decides which phases the deck needs, and in what order."}
        >
          {states.plan === "current" && build && (stage === "planning" && errorHere ? errorHere : stage === "planning" ? <Thinking steps={stepsFor("plan").length ? stepsFor("plan") : ["Planning how to build it…"]} /> : build.plan ? <PlanBody build={build} animate={spoken("plan")} /> : null)}
          {states.plan === "done" && build?.plan && <PlanBody build={build} animate={false} />}
        </Station>

        <Group label="BUILD, PHASE BY PHASE" />

        {phases.length === 0 ? (
          <Station id="phases" state="todo" node="•" title="The phases" note="Creatures, ramp, removal, lands… the Doctor chooses which the deck needs and in what order, and you approve each one." />
        ) : (
          phases.map((p, i) => {
            const state = p.status === "locked" ? "done" : stage === "building" && build?.current === p.id ? "current" : "todo";
            return (
              <Station
                key={p.id}
                id={p.id}
                state={state}
                node={String(i + 1)}
                kicker={`PHASE ${i + 1} OF ${phases.length}`}
                title={p.label}
                note={state === "done" ? `${phaseCount(p.id)} cards · ${money(phasePrice(p.id))}${p.summary ? ` — ${firstSentence(p.summary)}` : ""}` : state === "current" ? p.why || p.goal : `${p.count} cards · ${p.why || p.goal}`}
              >
                {state === "current" && build && (build.error ? errorHere : <PhaseBody build={build} phase={p} removed={removed} onToggle={toggleRemoved} animate={spoken(`phase:${p.id}`)} />)}
                {state === "done" && build && <LockedPhaseBody build={build} phase={p} />}
              </Station>
            );
          })
        )}

        <Group label="FINISH" />

        <Station id="review" state={states.review} node="★" kicker="LAST STEP" title="Review" note="Look over the whole deck, then make it.">
          {stage === "review" && build && <ReviewBody build={build} />}
        </Station>

        {(actionError || loadError) && <div style={{ marginLeft: 54, color: "var(--danger)", fontSize: 14 }}>{actionError ?? loadError}</div>}
      </div>

      {choosing && build && !build.busy && (
        <RefineDock text={refineText} onText={setRefineText} staged={stagedWords} round={build.rounds.length} acting={acting} onLook={lookAgain} />
      )}
      {stage === "plan" && build?.plan && (
        <ActionDock
          text={`Next, the Doctor starts on the ${build.plan.phases[0].label.toLowerCase()}.`}
          label={`Start with ${build.plan.phases[0].label.toLowerCase()} →`}
          disabled={acting}
          onClick={() => act(() => beginBuild(build.id))}
        />
      )}
      {proposalReady && current && build && (
        <SteerDock
          phaseLabel={current.label}
          note={note}
          onNote={setNote}
          removed={removed.size}
          kept={keptNames.length}
          acting={acting}
          onRedo={() => {
            act(() => redoBuildPhase(build.id, current.id, [...removed], note));
            setNote("");
          }}
          onLock={() => act(() => lockBuildPhase(build.id, current.id, keptNames))}
        />
      )}
      {stage === "review" && build && (
        <ActionDock text={`${build.deck.count < 99 ? `${build.deck.count} cards chosen, basic lands for the rest.` : "99 cards and the commander."}`} label={acting ? "Making your deck…" : "Make this deck"} disabled={acting} onClick={makeDeck} />
      )}

      {deckOpen && build && <DeckDrawer build={build} onClose={() => setDeckOpen(false)} />}
      {browsing && (
        <CommandersModal
          heading={heading}
          lesserKnown={lesserKnown}
          candidates={candidates}
          level={level}
          themeStyle={themeStyle}
          reasons={reasons}
          explaining={explaining}
          explainError={explainError}
          onExplain={explain}
          onChoose={(name) => {
            setChosen(name);
            setBrowsing(false);
          }}
          onClose={() => setBrowsing(false)}
        />
      )}
    </div>
  );
}
