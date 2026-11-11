# MTG Deck Doctor

An AI-assisted deck builder and tuner for Magic: The Gathering's Commander format. You build the deck yourself, and the Doctor (Claude) suggests cards and answers questions about the list. It also reviews decks you already have.

The backend is FastAPI (Python, managed with uv). The front end is React and TypeScript (Vite). Card data comes from [Scryfall](https://scryfall.com) and [EDHREC](https://edhrec.com), and the model is called through the Anthropic API.

## What it does

**New deck** is a button on the home page. It opens a window where you give the deck a name and search for a commander. Both are optional. **Create deck** takes you to the deck page. The "Start a deck with…" button on a new-commander suggestion does the same with that commander already set.

**Deck view** (`/decks/:id`) works on any deck, built here or imported:

- Deckbuilder: the list, grouped and sorted as you choose, with a card preview. Select a card, or the commander, to see its details, rulings, and printings, and to use it as a foil.
- Insights: EDHREC's top includes for your commander, a health check, cut suggestions, and swaps.
- Correspondence: a chat with the Doctor about the deck. The Doctor only suggests. It shows each card it wants to add or cut, or a commander it wants you to use, as a button under its reply, and nothing changes until you click it. The rules check every suggestion first: legality, color identity, the singleton rule, and the 99-card limit.
- Import and export decklists, pick printings, and track which cards you own.

**Home** (`/`) lists your decks, and shows new cards and new commanders from recent sets that are worth a look. **Card search** (`/search`) searches Scryfall.

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
| `AI_DAILY_BUDGET_USD` | Optional, and off unless set. The most the Doctor may spend in a UTC day, as estimated from token counts. See [AI usage and limits](#ai-usage-and-limits). |
| `ANTHROPIC_CHAT_EFFORT` | Optional. How hard the model thinks in chat: `low`, `medium`, `high` or `max`. Defaults to `medium`. |
| `CHAT_MAX_TOOL_ROUNDS` | Optional. The most model calls one chat message may make. Defaults to `20`. |

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

## AI usage and limits

The Doctor's model calls are the app's only real running cost, so they are metered:

- **Admin page.** Open **Admin** on the home page (`/admin`) to see what the Doctor has used: cost and tokens today and over the last 7, 14 or 30 days, a chart per day, a split by feature, and the latest calls. It refreshes every 15 seconds. The numbers come from `GET /usage`.
- **Usage log.** Every call is recorded in `data/usage.jsonl` with its feature, model, token counts, and an estimated cost. The estimate comes from token counts and published rates, so it tracks the invoice but is not the invoice.
- **Daily budget (optional).** Nothing is held back by default. Set `AI_DAILY_BUDGET_USD` and, once a day's estimated cost reaches it, the next call is refused with a 429 (`ai_budget`) until midnight UTC. It is meant for when other people use the app. For a hard stop on your account, set a spend limit in the Anthropic console.

What keeps each call small:

- **Tool calls per message.** A chat message makes at most `CHAT_MAX_TOOL_ROUNDS` model calls. Real messages take 2 to 7, so the cap only catches a loop that never ends. The last call gets no tools and has to say what it did and what is left, so you can ask it to continue.
- **Chat history.** The model sees the current turn in full. From earlier turns it sees what was said and the 12 most recent card lookups, and at most the last 20 turns. The stored conversation, and what you see in Correspondence, are unchanged.
- **Prompt caching.** The instructions and tool list are cached across messages, and the conversation so far is cached within a turn, so repeated calls pay a tenth of the input price for what hasn't changed.
- **Effort.** Chat and card suggestions run at `medium` effort (`ANTHROPIC_CHAT_EFFORT` sets chat's).

On a copy of a 41-message conversation, these changes cut what each call sends from about 32,000 tokens to about 5,600, and a two-call message cost about 3.5 cents.

## Test

The tests stub the model, EDHREC, and Scryfall, so they need no network or API key. Run them all:

```bash
for t in tests/test_*.py; do uv run python "$t" || break; done
```

Each file is a script that prints one line per check and exits with 1 if any fails, so you can also run one on its own, for example `uv run python tests/test_chat.py`.

Check the front end's types and lint:

```bash
cd frontend && npx tsc -b && npm run lint
```

## Project layout

| Path | Contents |
| --- | --- |
| `src/mtg_deck_doctor/api.py` | The FastAPI app and its routes. |
| `src/mtg_deck_doctor/tool_loop.py` | Every model call, with prompts, the chat's tools, and checks on what the model returns. |
| `src/mtg_deck_doctor/edhrec.py`, `card_cache.py`, `game_changers.py` | EDHREC and Scryfall clients with local caches. |
| `frontend/src/DeckView.tsx` | The deck page. |
| `frontend/src/ChatSuggestions.tsx`, `chatMessages.ts` | The Doctor's suggested changes, shown as buttons under its replies. |
| `context/` | Notes the model reads. |
| `tests/` | The test suite. |

## Data

Decks, your collection, and API caches are stored as JSON files under `data/`. The folder is git-ignored and is created as you use the app. There is no database and no authentication, so the app is for one person on one machine.

## Limits

- The Doctor's descriptions of what a card does come from the card's rules text, and can still be wrong.
