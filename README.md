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

## Data

Decks, build sessions, your collection, and API caches are stored as JSON files under `data/`. The folder is git-ignored and is created as you use the app. There is no database and no authentication, so the app is for one person on one machine.

## Limits

- The Doctor's descriptions of what a card does come from the card's rules text, and can still be wrong.
- Commander search depends on the Scryfall searches the model writes, so relevance varies from run to run.
- Builds that you never finish stay in `data/builds/`.
