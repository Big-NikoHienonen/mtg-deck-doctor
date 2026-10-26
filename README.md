# MTG Deck Doctor

An AI-assisted deck builder and tuner for Magic: The Gathering's Commander format. You describe the deck you want, the Doctor (Claude) finds a commander with you and builds the 99 cards one phase at a time, and you keep or replace what it picks. It also reviews decks you already have.

The backend is FastAPI (Python, managed with uv). The front end is React and TypeScript (Vite). Card data comes from [Scryfall](https://scryfall.com) and [EDHREC](https://edhrec.com), and the model is called through the Anthropic API.

## What it does

**Deck Studio** (`/new`) builds a deck as one timeline from your first sentence to the finished list:

1. **Brief.** Describe the deck in your own words. You can also set a commander, colors, style, power level, budget, and per-area spending (for example, "at most $30 on lands"). Every part is optional.
2. **Commander.** The Doctor finds a commander in rounds. It keeps a short list of facts about what you want, searches Scryfall for commanders that match, and checks them against EDHREC. After each round you can tell it more, rule a commander out with a reason, ask for more like one, or take a fact back. Each round sharpens the search.
3. **Plan.** The Doctor decides which phases the deck needs and in what order. A creature deck starts with creatures; a spells deck starts with spells.
4. **Phases.** For each phase, the Doctor picks cards from EDHREC's data for your commander. You click cards out, ask for replacements, and lock the phase in. The next phase is prepared while you review the current one.
5. **Review.** You look over the whole list and make the deck. The Doctor's reasoning for each phase becomes the start of the deck's chat.

The model proposes and the code decides. Every card the model names must be on a candidate list that is already limited to legal cards in your commander's colors. The singleton rule, Game Changer limits per power level, and the budget are enforced in code, not left to the model.

**Deck view** (`/decks/:id`) works on any deck, built here or imported:

- Insights: EDHREC's top includes for your commander, a health check, cut suggestions, and swaps.
- Correspondence: a chat with the Doctor about the deck.
- Import and export decklists, pick printings, and track which cards you own.

**Home** (`/`) lists your decks, and shows new cards and new commanders from recent sets that are worth a look. **Card search** (`/search`) searches Scryfall. A no-AI path builds a plain starting list for a commander from EDHREC's data.

## Requirements

- Python 3.12 or later and [uv](https://docs.astral.sh/uv/)
- Node.js 22 or later
- An [Anthropic API key](https://console.anthropic.com)

## Set up

Install the backend and front end dependencies:

```bash
uv sync
```

```bash
cd frontend && npm install
```

Create your environment file and add your API key:

```bash
cp .env.example .env
```

| Variable | Description |
| --- | --- |
| `ANTHROPIC_API_KEY` | Your Anthropic API key. Required for everything the Doctor does. |
| `ANTHROPIC_MODEL` | Optional. The model to use. Defaults to `claude-sonnet-5`. |

`.env` is git-ignored. Don't commit it.

## Run

Start the backend on port 8000:

```bash
./dev-backend.sh
```

Start the front end on port 5173, in a second terminal:

```bash
cd frontend && npm run dev
```

Open http://localhost:5173. The front end calls the backend at `http://localhost:8000`, and the backend allows requests from localhost.

## Test

The tests stub the model, EDHREC, and Scryfall, so they need no network or API key:

```bash
uv run python tests/test_deck_with_the_doctor.py
```

Check the front end's types and lint:

```bash
cd frontend && npx tsc -b && npm run lint
```

## Evals

The stubbed tests can't catch a model that behaves differently after a prompt change. The evals run the real thing instead. `evals/commander_rounds.py` plays a fixed list of briefs through the commander rounds, some with scripted follow-ups (reject a commander with a reason, like one, take a fact back, change the colors), and checks what each round offers.

**Each run costs API money.** It calls the real model, Scryfall, and EDHREC. Nothing runs it for you: it isn't part of the tests or CI. Run it after you change a prompt in `tool_loop.py` or the commander rounds in `deck_builder.py`. A full run makes about 30 model calls (roughly 85,000 input and 15,000 output tokens) and takes about two minutes.

```bash
uv run python evals/commander_rounds.py
```

The script reads `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` from `.env`. It writes builds to a temporary directory, so `data/builds/` stays as it is. It shares the Scryfall and EDHREC caches under `data/` with the app.

| Flag | Description |
| --- | --- |
| `--only CASE [CASE ...]` | Runs only the named cases. Use it to keep a run cheap while you iterate. |
| `--timeout SECONDS` | Sets the time limit for one round. Defaults to 120. |
| `--workers N` | Sets how many cases run at once. Defaults to 4. |
| `--verbose` | Prints each round's facts and offered commanders. |

Each round gets these checks:

| Check | Passes when |
| --- | --- |
| `runs` | The round finishes without an error and leaves the build at the commander stage. |
| `colors` | The brief, the player's words, or the facts fix the colors, and every offered commander has exactly that color identity. |
| `rejects` | A rejected commander doesn't come back. |
| `facts` | There are at most 8 facts of at most 80 characters, none of them filler such as "colours open" or "no budget", and none naming a color, budget, or power level the player never mentioned. |
| `options` | At least 2 commanders are offered, and each one's `fits` and `misses` come only from the facts. |
| `time` | The round finishes within the time limit. |

The script prints each round as it finishes, then the offending values for every failed check, then a table of cases by check. It exits with 1 if any check failed. A check that doesn't apply to a round shows as `-`.

To add a case, append a `Case` to `CASES` in the script. Give it the brief's text, any form answers, the colors the brief fixes, and the follow-up `Step`s.

## Project layout

| Path | Contents |
| --- | --- |
| `src/mtg_deck_doctor/api.py` | The FastAPI app and its routes. |
| `src/mtg_deck_doctor/deck_builder.py` | Build sessions: brief, commander rounds, plan, phases, and the rules that limit them. |
| `src/mtg_deck_doctor/commander_search.py` | Scryfall searches for commanders, checked against EDHREC. |
| `src/mtg_deck_doctor/tool_loop.py` | Every model call, with prompts and checks on what the model returns. |
| `src/mtg_deck_doctor/wizard.py` | Power levels, spending areas, and the no-AI starting list. |
| `src/mtg_deck_doctor/edhrec.py`, `card_cache.py` | EDHREC and Scryfall clients with local caches. |
| `frontend/src/DeckStudio.tsx` | The Deck Studio page. `Studio*.tsx` hold its parts. |
| `frontend/src/DeckView.tsx` | The deck page. |
| `context/` | Notes the model reads. |
| `tests/` | The test suite. |
| `evals/` | Live evals that call the real model. They cost API money. |

## Data

Decks, build sessions, your collection, and API caches are stored as JSON files under `data/`. The folder is git-ignored and is created as you use the app. There is no database and no authentication, so the app is for one person on one machine.

## Limits

- The Doctor's descriptions of what a card does come from the card's rules text, and can still be wrong.
- Commander search depends on the Scryfall searches the model writes, so relevance varies from run to run.
- Builds that you never finish stay in `data/builds/`.
