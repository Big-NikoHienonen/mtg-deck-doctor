"""Live eval for the commander-finding rounds in Deck Studio.

Runs a fixed list of briefs, some with scripted follow-up rounds, through
`deck_builder.create` and `deck_builder.refine_commanders`, and checks what each round
offers. The eval calls the real model, Scryfall, and EDHREC, so it costs API money. It is
not part of the tests or CI. Run it from anywhere in the repository:

    uv run python evals/commander_rounds.py

Builds go to a temporary directory, so `data/builds/` stays as it is. The Scryfall and
EDHREC caches under `data/` are shared with the app.

Each round gets these checks. A check that doesn't apply to a round shows as "-".

- runs: the round finishes without an error and leaves the build at the commander stage.
- colors: when the brief, the player's words, or the facts fix the colors, every offered
  commander has exactly that color identity.
- rejects: a commander the player rejected never comes back.
- facts: at most 8 facts, each at most 80 characters, none of them filler, and none that
  names a color, budget, or power level the player never mentioned.
- options: at least 2 commanders, and each one's `fits` and `misses` come from the facts.
- time: the round finishes within the time limit.

The exit code is 0 when every check passes, 1 when any fails, and 2 when the eval can't start.
"""

import argparse
import os
import re
import sys
import tempfile
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# The app reads context/ and writes data/ relative to the repository root.
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
load_dotenv(ROOT / ".env")
if not os.environ.get("ANTHROPIC_API_KEY"):
    print("ANTHROPIC_API_KEY is not set. Add it to .env and run the eval again.", file=sys.stderr)
    sys.exit(2)

# These imports come after the setup above: tool_loop needs the key when it loads.
import mtg_deck_doctor.deck_builder as B  # noqa: E402
import mtg_deck_doctor.tool_loop as T  # noqa: E402
from mtg_deck_doctor import wizard  # noqa: E402

# -- the cases -----------------------------------------------------------------------------

# The styles the front end sends with every brief (frontend/src/wizardData.ts).
STYLES = [
    "tokens", "aristocrats", "reanimator", "self-mill", "voltron", "spellslinger", "big-mana", "lifegain",
    "artifacts", "equipment", "landfall", "blink", "control", "group-hug",
    "dragons", "zombies", "vampires", "elves", "goblins", "angels", "cats", "dinosaurs",
    "merfolk", "wizards", "pirates", "slivers", "werewolves", "elementals", "knights", "ninjas",
]

# A brief as the front end sends it when the player fills in nothing but the text.
EMPTY_BRIEF = {
    "text": "",
    "styles": STYLES,
    "colors": [],
    "colorless": False,
    "theme": None,
    "bracket": None,
    "budget": None,
    "caps": {},
    "invest": [],
    "lesser_known": False,
    "commander": None,
}

OPEN = "*"  # In `Step.colors`: the player took back the colors.
COLORLESS = "C"


@dataclass
class Step:
    """One scripted follow-up round: what the player does with the last round's offer.

    `reject` is [(position, reason)] and `like` is [position], both positions in the
    options offered last round, counting from 0. `drop` is a regular expression: the first
    fact it matches is taken back (the last fact, if none matches). `colors` is what the
    player's words now fix, if they change it: letters, COLORLESS, or OPEN.
    """

    said: str = ""
    reject: list[tuple[int, str]] = field(default_factory=list)
    like: list[int] = field(default_factory=list)
    drop: str | None = None
    colors: str | None = None


@dataclass
class Case:
    """A brief, the form answers that go with it, and the rounds the player plays after it.

    `colors` is what the brief fixes as letters ("BR" for Rakdos), COLORLESS, or None when it
    leaves the colors open.
    """

    name: str
    text: str
    form: dict = field(default_factory=dict)
    colors: str | None = None
    steps: list[Step] = field(default_factory=list)


CASES = [
    Case("rakdos", "I want to build a rakdos deck", colors="BR"),
    Case("treasure-aggro", "a treasure deck with high aggression"),
    Case("mono-red", "a mono red deck that attacks every turn", colors="R"),
    Case("esper", "I'm in the mood for esper, something that controls the game", colors="WUB"),
    Case(
        "form-fields",
        "elves that make a lot of mana",
        form={"colors": ["G"], "theme": "elves", "bracket": 3, "budget": 100.0},
        colors="G",
    ),
    Case("niche", "lesser-known commanders"),
    Case("vague", "something my friends have never seen", steps=[Step(like=[0])]),
    Case(
        "multi-round",
        "a rakdos treasure deck that attacks a lot",
        colors="BR",
        steps=[
            Step(reject=[(0, "too slow for me")]),
            Step(drop="attack|aggress"),
            Step(said="actually mono red", colors="R"),
        ],
    ),
]

# -- reading colors, budgets, and power levels out of text -------------------------------------

_COLOR_WORDS = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}
_COLOR_NAMES = {v: k for k, v in _COLOR_WORDS.items()}
_COMBOS = {
    "azorius": "WU", "dimir": "UB", "rakdos": "BR", "gruul": "RG", "selesnya": "GW",
    "orzhov": "WB", "izzet": "UR", "golgari": "BG", "boros": "RW", "simic": "GU",
    "bant": "GWU", "esper": "WUB", "grixis": "UBR", "jund": "BRG", "naya": "RGW",
    "abzan": "WBG", "jeskai": "URW", "sultai": "BGU", "mardu": "RWB", "temur": "GUR",
}


def canon(letters: str) -> str:
    return wizard.canonical_colors(letters)


def named_colors(text: str) -> set[str]:
    """The colors `text` names, as letters: color words, guild, shard, and wedge names, and
    letter codes such as "BR"."""
    out: set[str] = set()
    for word in re.findall(r"[a-z]+", text.lower()):
        out |= set(_COLOR_WORDS[word]) if word in _COLOR_WORDS else set(_COMBOS.get(word, ""))
    for code in re.findall(r"\b[WUBRG]{2,5}\b", text):
        out |= set(code)
    return out


def describe_colors(letters: str) -> str:
    return f"{letters} ({', '.join(_COLOR_NAMES[c] for c in letters)})" if letters else "colorless"


# What a fact that is only about colors can be made of. Anything else in it, and it isn't one.
_COLOR_FILLER = {
    "mono", "colour", "colours", "color", "colors", "identity", "only", "exactly",
    "deck", "commander", "and", "in", "is", "are", "must", "be", "the", "a",
}


def fact_colors(fact: str) -> str | None:
    """The exact color identity a fact fixes ("Black-red", "Mono-red", "Rakdos colours"), or
    None when it says anything besides colors or leaves them open ("red or black")."""
    letters: set[str] = set()
    for word in re.findall(r"[a-z]+", fact.lower()):
        if word in _COLOR_WORDS:
            letters.add(_COLOR_WORDS[word])
        elif word in _COMBOS:
            letters |= set(_COMBOS[word])
        elif word in ("colorless", "colourless"):
            letters.add(COLORLESS)
        elif word not in _COLOR_FILLER:
            return None
    if not letters or (COLORLESS in letters and len(letters) > 1):
        return None
    return "" if COLORLESS in letters else canon("".join(letters))


# Facts the prompt forbids: they restate what the player left open.
_FILLER = re.compile(
    r"colou?rs?\s+(?:are\s+|is\s+)?(?:open|flexible|unspecified|any)\b"
    r"|\b(?:open|any|flexible)\s+colou?rs?\b"
    r"|\bno\s+(?:\w+\s+)?budget\b"
    r"|\bunlimited\s+budget\b"
    r"|\bbudget\s+(?:is\s+)?(?:open|flexible|unspecified|unlimited|any)\b"
    r"|\b(?:any|open|no)\s+(?:\w+\s+)?power\s+level\b"
    r"|\bpower\s+level\s+(?:is\s+)?(?:open|flexible|unspecified|any)\b",
    re.I,
)
# A fact names a budget or a power level when it matches these, and the player did when
# their words match the broader ones. "Cheap" and "power" alone are left out of the first two:
# they also describe mana costs and creature stats.
_BUDGET_IN_FACT = re.compile(r"\bbudget|\$\s?\d|\b\d+\s*(?:dollars|usd|bucks)\b|\baffordab|\binexpensive|\bexpensive|\bpricey|\bprice", re.I)
_BUDGET_IN_WORDS = re.compile(r"budget|cheap|afford|pric|expens|money|\$|dollar|usd|buck|spend|cost|poor|broke", re.I)
_POWER_IN_FACT = re.compile(
    r"power\s+level|\bbracket|\bcasual|\bcompetitive|\bcedh|\boptimi[sz]ed|\bprecon|\btuned\b|\bjank"
    r"|\b(?:high|low|mid|medium)[- ]power\s+(?:deck|game|play|table)",
    re.I,
)
_POWER_IN_WORDS = re.compile(
    r"power|bracket|casual|chill|relax|competit|cedh|optimi|tuned|precon|jank|strong|silly|fun\b|friendly|serious", re.I
)


def form_words(form: dict) -> str:
    """The form's answers as words, to read next to what the player wrote."""
    parts = []
    if form.get("colors"):
        parts.append("colors " + " ".join(_COLOR_NAMES[c] for c in form["colors"]))
    if form.get("colorless"):
        parts.append("colorless")
    if form.get("theme"):
        parts.append(f"style {form['theme']}")
    if form.get("bracket"):
        parts.append(f"power level {form['bracket']}")
    if form.get("budget") is not None:
        parts.append("budget " + ("no limit" if form["budget"] == "none" else f"${form['budget']}"))
    if form.get("lesser_known"):
        parts.append("lesser-known commanders")
    return "; ".join(parts)


# -- the checks ------------------------------------------------------------------------------

OK, FAIL, NA = "ok", "FAIL", "-"
CHECKS = ("runs", "colors", "rejects", "facts", "options", "time")


@dataclass
class Check:
    status: str = NA
    detail: list[str] = field(default_factory=list)


@dataclass
class RoundResult:
    label: str
    action: str
    seconds: float
    checks: dict[str, Check]
    facts: list[str] = field(default_factory=list)
    options: list[dict] = field(default_factory=list)
    search: dict = field(default_factory=dict)

    @property
    def failed(self) -> list[str]:
        return [name for name, c in self.checks.items() if c.status == FAIL]


def _verdict(problems: list[str]) -> Check:
    return Check(FAIL if problems else OK, problems)


def check_colors(expected: str | None, source: str, options: list[dict], search: dict) -> Check:
    if expected is None:
        return Check()
    wrong = [f"{o['name']} is {describe_colors(canon(o['colors']))}" for o in options if canon(o["colors"]) != expected]
    if not wrong:
        return Check(OK)
    return Check(FAIL, [f"expected exactly {describe_colors(expected)}, from {source}", *wrong, f"the search fixed: {search.get('colors') or 'no colors'}"])


def check_rejects(rejected: list[str], options: list[dict]) -> Check:
    if not rejected:
        return Check()
    return _verdict([f"{o['name']} came back after it was rejected" for o in options if o["name"] in rejected])


def check_facts(facts: list[str], words: str) -> Check:
    problems = []
    if len(facts) > T.MAX_FACTS:
        problems.append(f"{len(facts)} facts, at most {T.MAX_FACTS}")
    for fact in facts:
        if len(fact) > 80:
            problems.append(f"{len(fact)} characters, at most 80: {fact!r}")
        if _FILLER.search(fact):
            problems.append(f"filler: {fact!r}")
        invented = []
        if named_colors(fact) - named_colors(words):
            invented.append("color " + ", ".join(sorted(_COLOR_NAMES[c] for c in named_colors(fact) - named_colors(words))))
        if _BUDGET_IN_FACT.search(fact) and not _BUDGET_IN_WORDS.search(words):
            invented.append("a budget")
        if _POWER_IN_FACT.search(fact) and not _POWER_IN_WORDS.search(words):
            invented.append("a power level")
        if invented:
            problems.append(f"invented, the player never mentioned {' or '.join(invented)}: {fact!r}")
    return _verdict(problems)


def check_options(options: list[dict], facts: list[str]) -> Check:
    problems = []
    if len(options) < 2:
        problems.append(f"{len(options)} option(s) offered, at least 2 needed")
    for o in options:
        stray = [f for f in [*o["fits"], *o["misses"]] if f not in facts]
        if stray:
            problems.append(f"{o['name']}: fits or misses not in the facts: {stray}")
    return _verdict(problems)


def facts_fix_colors(facts: list[str]) -> str | None:
    """The colors the facts fix, when they agree on one identity."""
    found = {c for c in map(fact_colors, facts) if c is not None}
    return found.pop() if len(found) == 1 else None


# -- running a case --------------------------------------------------------------------------


def wait_for(build_id: str, deadline: float) -> dict | None:
    """The build once the Doctor stops working on it; None if `deadline` (monotonic) passes first."""
    while time.monotonic() < deadline:
        session = B.load(build_id)
        if session is not None and not session["busy"]:
            return session
        time.sleep(0.25)
    return None


def expected_colors(letters: str | None) -> str | None:
    if letters in (None, OPEN):
        return None
    return "" if letters == COLORLESS else canon(letters)


def grade(label: str, action: str, session: dict | None, seconds: float, limit: float, ctx: dict) -> RoundResult:
    """Applies the checks to one finished round. `ctx` holds what the player has said and asked for so far."""
    checks = {name: Check() for name in CHECKS}
    result = RoundResult(label, action, seconds, checks)
    if session is None:
        checks["time"] = Check(FAIL, [f"not finished after {limit:.0f} s"])
        return result
    checks["time"] = _verdict([f"took {seconds:.0f} s, limit {limit:.0f} s"] if seconds > limit else [])
    problems = []
    if session["error"]:
        problems.append(f"{session['error'].get('status')}: {session['error'].get('detail')}")
    elif session["stage"] != "commander":
        problems.append(f"stage is {session['stage']!r}, expected 'commander'")
    checks["runs"] = _verdict(problems)
    if problems:
        return result

    options, facts = session["commander_options"], session["facts"]
    search = session["rounds"][-1]
    result.facts, result.options, result.search = facts, options, search
    expected, source = ctx["colors"], "the brief or the player's words"
    if expected is None:
        expected, source = facts_fix_colors(facts), "the facts"
    checks["colors"] = check_colors(expected, source, options, search)
    checks["rejects"] = check_rejects(ctx["rejected"], options)
    checks["facts"] = check_facts(facts, " ".join(ctx["words"]))
    checks["options"] = check_options(options, facts)
    return result


def pick(position: int, items: list) -> object:
    """The item at `position`, or the last one when the round offered fewer."""
    return items[min(position, len(items) - 1)]


def play(case: Case, limit: float, announce) -> list[RoundResult]:
    """Plays a case from its brief through its follow-up rounds. Stops at a round that fails to finish."""
    ctx = {
        "colors": expected_colors(case.colors),
        "words": [case.text, form_words(case.form)],
        "rejected": [],
    }
    rounds: list[RoundResult] = []

    def finish(label: str, action: str, started: float, session: dict | None) -> dict | None:
        result = grade(label, action, session, time.monotonic() - started, limit, ctx)
        rounds.append(result)
        announce(case.name, result)
        return session if result.checks["runs"].status == OK and session is not None else None

    started = time.monotonic()
    build_id = B.create({**EMPTY_BRIEF, "text": case.text, **case.form})
    session = finish("round 1", "brief", started, wait_for(build_id, started + limit))

    for number, step in enumerate(case.steps, 2):
        if session is None or not session["commander_options"]:
            break
        names = [o["name"] for o in session["commander_options"]]
        reject = [{"name": pick(i, names), "reason": reason} for i, reason in step.reject]
        like = [pick(i, names) for i in step.like]
        drop = []
        if step.drop and session["facts"]:
            drop = [next((f for f in session["facts"] if re.search(step.drop, f, re.I)), session["facts"][-1])]
        action = "; ".join(
            [*([f"said {step.said!r}"] if step.said else []), *[f"rejected {r['name']} ({r['reason']})" for r in reject],
             *[f"liked {n}" for n in like], *[f"dropped {f!r}" for f in drop]]
        )
        ctx["words"] += [step.said, *[r["reason"] for r in reject]]
        ctx["rejected"] += [r["name"] for r in reject]
        if step.colors is not None:
            ctx["colors"] = expected_colors(step.colors)

        started = time.monotonic()
        try:
            B.refine_commanders(build_id, step.said, reject, like, drop)
        except B.BuildError as err:
            session = finish(f"round {number}", action, started, {**session, "error": {"status": err.status, "detail": err.detail}})
            continue
        session = finish(f"round {number}", action, started, wait_for(build_id, started + limit))
    return rounds


def play_safely(case: Case, limit: float, announce) -> list[RoundResult]:
    """`play`, with a crash in the eval itself reported as a failed round, not a lost case."""
    try:
        return play(case, limit, announce)
    except Exception:
        detail = traceback.format_exc().strip().splitlines()[-1]
        result = RoundResult("harness", "", 0.0, {name: Check() for name in CHECKS})
        result.checks["runs"] = Check(FAIL, [f"the eval crashed: {detail}"])
        announce(case.name, result)
        return [result]


# -- reporting -------------------------------------------------------------------------------


def paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if sys.stdout.isatty() else text


def mark(status: str) -> str:
    return paint(status, "31;1") if status.startswith(FAIL) else paint(status, "32") if status == OK else status


def print_failures(results: dict[str, list[RoundResult]]) -> None:
    printed = False
    for name, rounds in results.items():
        for r in rounds:
            for check in r.failed:
                if not printed:
                    print("\nFailures")
                    printed = True
                print(f"\n  {paint(name, '1')} · {r.label} · {paint(check, '31;1')}" + (f"  [{r.action}]" if r.action else ""))
                for line in r.checks[check].detail:
                    print(f"      {line}")


def print_transcript(results: dict[str, list[RoundResult]]) -> None:
    print("\nTranscript")
    for name, rounds in results.items():
        for r in rounds:
            print(f"\n  {paint(name, '1')} · {r.label} · {r.seconds:.0f} s" + (f"  [{r.action}]" if r.action else ""))
            if r.search:
                print(f"      understood: {r.search.get('understood')}")
                print(f"      search fixed {r.search.get('colors') or 'no colors'}; {r.search.get('matched')} matched, topped up from {r.search.get('topped_up') or 'nowhere'}")
            for fact in r.facts:
                print(f"      fact: {fact}")
            for o in r.options:
                print(f"      offered: {o['name']} ({canon(o['colors']) or 'C'}) fits {len(o['fits'])}, misses {len(o['misses'])}")


def cell(rounds: list[RoundResult], check: str) -> str:
    statuses = [r.checks[check].status for r in rounds]
    bad = [str(i) for i, s in enumerate(statuses, 1) if s == FAIL]
    if bad:
        return "FAIL" + (f" r{','.join(bad)}" if len(rounds) > 1 else "")
    return OK if OK in statuses else NA


def print_table(results: dict[str, list[RoundResult]]) -> None:
    print("\nResults\n")
    rows = [(name, str(len(rounds)), *[cell(rounds, c) for c in CHECKS]) for name, rounds in results.items()]
    head = ("case", "rounds", *CHECKS)
    widths = [max(len(row[i]) for row in [head, *rows]) for i in range(len(head))]
    line = lambda row: "  " + "  ".join(mark(v).ljust(w + (len(mark(v)) - len(v))) for v, w in zip(row, widths, strict=True))
    print(line(head))
    print("  " + "  ".join("-" * w for w in widths))
    for row in rows:
        print(line(row))


def summarize(results: dict[str, list[RoundResult]]) -> int:
    statuses = [c.status for rounds in results.values() for r in rounds for c in r.checks.values()]
    passed, failed = statuses.count(OK), statuses.count(FAIL)
    clean = sum(1 for rounds in results.values() if not any(r.failed for r in rounds))
    print(f"\n  {passed} checks passed, {paint(str(failed), '31;1') if failed else failed} failed, {statuses.count(NA)} not applicable; {clean} of {len(results)} cases clean")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Live eval for the commander rounds. Calls the real model, Scryfall, and EDHREC, so it costs API money.")
    parser.add_argument("--timeout", type=float, default=120, metavar="SECONDS", help="time limit for one round (default: 120)")
    parser.add_argument("--workers", type=int, default=4, help="cases to run at once (default: 4)")
    parser.add_argument("--only", nargs="+", metavar="CASE", help="run only these cases: " + ", ".join(c.name for c in CASES))
    parser.add_argument("--verbose", action="store_true", help="print each round's facts and offered commanders")
    args = parser.parse_args()
    known = {c.name for c in CASES}
    if args.only and set(args.only) - known:
        parser.error(f"unknown case {', '.join(sorted(set(args.only) - known))}; known: {', '.join(sorted(known))}")
    cases = [c for c in CASES if not args.only or c.name in args.only]

    usage = {"calls": 0, "input": 0, "output": 0}
    usage_lock = threading.Lock()
    create = T.client.messages.create

    def counting_create(*a, **kw):
        response = create(*a, **kw)
        with usage_lock:
            usage["calls"] += 1
            usage["input"] += response.usage.input_tokens
            usage["output"] += response.usage.output_tokens
        return response

    T.client.messages.create = counting_create

    print_lock = threading.Lock()

    def announce(name: str, r: RoundResult) -> None:
        verdict = paint("FAIL " + ", ".join(r.failed), "31;1") if r.failed else paint("ok", "32")
        with print_lock:
            print(f"  {name:<16} {r.label:<8} {r.seconds:5.1f} s  {verdict}", flush=True)

    print(f"Commander rounds eval · model {T.MODEL} · {len(cases)} cases · {args.workers} at a time · {args.timeout:.0f} s per round\n")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="commander-rounds-") as tmp:
        B.BUILDS_DIR = Path(tmp) / "builds"
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {c.name: pool.submit(play_safely, c, args.timeout, announce) for c in cases}
            results = {name: future.result() for name, future in futures.items()}

    print_failures(results)
    if args.verbose:
        print_transcript(results)
    print_table(results)
    code = summarize(results)
    print(f"  {usage['calls']} model calls, {usage['input']:,} input and {usage['output']:,} output tokens, {time.monotonic() - started:.0f} s")
    return code


if __name__ == "__main__":
    sys.exit(main())
