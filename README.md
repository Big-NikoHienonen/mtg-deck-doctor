# MTG Deck Doctor

An AI-assisted deck builder and tuner for Magic: The Gathering's Commander format. You build the deck yourself, and the Doctor (Claude) suggests cards and answers questions about the list. It also reviews decks you already have.

The backend is FastAPI (Python, managed with uv). The front end is React and TypeScript (Vite). Card data comes from [Scryfall](https://scryfall.com) and [EDHREC](https://edhrec.com), and the model is called through the Anthropic API.

## What it does

**New deck** is a button in the app bar. It opens a window where you give the deck a name and search for a commander. Both are optional. **Create deck** takes you to the deck page. The "Start a deck with…" button on a new-commander suggestion does the same with that commander already set.

**Deck view** (`/decks/:id`) works on any deck, built here or imported:

- Deckbuilder: the list, grouped and sorted as you choose, with a card preview. Select a card, or the commander, to see its details, rulings, and printings, and to use it as a foil.
- Insights: EDHREC's top includes for your commander, a health check, cut suggestions, and swaps.
- Correspondence: a chat with the Doctor about the deck. The Doctor only suggests. It shows each card it wants to add or cut, or a commander it wants you to use, as a button under its reply, and nothing changes until you click it. The rules check every suggestion first: legality, color identity, the singleton rule, and the 99-card limit.
- Import and export decklists, pick printings (kept with the deck, so visitors see them), and track which cards you own.
- Public view: anyone can open a deck's address to look at the list, with no chat, insights, or editing. Sign in at the same address to edit. See [Sign in and public decks](#sign-in-and-public-decks).

**Home** (`/`) is the landing page: new cards and new commanders from recent sets that are worth a look, with a link to every new card. **My decks** (`/decks`) lists your decks, and holds the swaps the Doctor has worked out. **Card search** (`/search`) searches Scryfall.

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
| `MTG_DECK_DOCTOR_AUTH` | Optional. `off` runs the app with no sign-in while there is no account, which `./dev-backend.sh` does. An account turns the sign-in on whatever this says. See [Sign in and public decks](#sign-in-and-public-decks). |
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

Open http://localhost:5173. The front end calls the backend at `/api`, and Vite sends that to the backend on port 8000. `./dev-backend.sh` runs the backend without the login, so there is nothing to sign in to.

## Run it for other people

The backend can serve the whole app on one address: the API under `/api`, and the built front end for every other path. One address means the login cookie is first-party, there are no cross-origin requests, and the app works behind any host or tunnel with no extra settings.

Make an account first (see [Accounts](#accounts)), then run:

```bash
./serve.sh
```

It builds the front end and starts the backend on `127.0.0.1:8000`. Set `HOST` and `PORT` to change that. Run the app through HTTPS, so the login cookie is marked secure. Behind a proxy or tunnel that ends HTTPS, `serve.sh` already passes `--proxy-headers`, so the backend sees the visitor's address and the real scheme.

A deck's address, `<address>/decks/<id>`, then opens a read-only view of the list for anyone who can reach it. For a quick test from your own machine, point a tunnel at port 8000. To host it, you need a disk that persists, because decks, your collection, and the caches are files under `data/`, and `data/session_secret` signs the login cookie.

## Deploy on Fly.io

The `Dockerfile` builds the front end and runs the backend, which serves it and the API (see [Run it for other people](#run-it-for-other-people)). `fly.toml` runs it as one Machine (`shared-cpu-1x`, 512 MB) in Stockholm (`arn`) with a 1 GB volume at `/app/data`. The decks are files on that volume, and a volume attaches to one Machine, so don't scale the app past one. Install [flyctl](https://fly.io/docs/flyctl/install/) and sign in with `fly auth login`, then, from the project root, create the app without deploying it:

```bash
fly launch --no-deploy --copy-config --ha=false
```

Set the API key as a secret:

```bash
fly secrets set ANTHROPIC_API_KEY=<your key>
```

Deploy. The first deploy creates the volume:

```bash
fly deploy --ha=false
```

The app is closed until it has an account, so it shows only the landing page and refuses everything else. That is the state to copy your data into.

To bring your local data along, copy it to the volume once the Machine is running. Decks and your collection can't be rebuilt, and the saved AI results (`suggestions`, `cuts`, `discoveries`, `new_commanders.json`) cost tokens to regenerate. The caches (about 12 MB) do rebuild by themselves, but from empty, so the first visitors to a deck would wait on Scryfall and EDHREC. Copying them starts the app warm:

```bash
fly ssh sftp put -R data/decks /app/data/decks
fly ssh sftp put data/collection.json /app/data/collection.json
fly ssh sftp put -R data/suggestions /app/data/suggestions
fly ssh sftp put -R data/cuts /app/data/cuts
fly ssh sftp put -R data/discoveries /app/data/discoveries
fly ssh sftp put data/new_commanders.json /app/data/new_commanders.json
for f in card_cache printings_cache rulings_cache edhrec_cache new_cards_cache game_changers_cache; do
  fly ssh sftp put data/$f.json /app/data/$f.json
done
fly ssh console -C "ls /app/data"
```

Don't copy `data/session_secret` or `data/users`. The server makes its own.

Then make your account on the Machine. The first account takes the decks that have no owner, so make it after the copy. `fly ssh console` opens a shell on the Machine, and the command asks for a password of at least 10 characters:

```bash
fly ssh console
mtg-deck-doctor create-user you@example.com
```

Open the app with `fly open` and sign in. A deck's address is `https://<app>.fly.dev/decks/<id>`.

`fly.toml` caps the Doctor at `AI_DAILY_BUDGET_USD = "5"` dollars a day. To change it, edit the number and run `fly deploy --ha=false` again. The cap is an estimate from token counts, so also set a spend limit on the key's workspace in the Anthropic console.

To run the image locally, with Docker running, then make an account in the running container:

```bash
docker build -t mtg-deck-doctor .
docker run -d --name mtg-deck-doctor -p 8080:8080 -e ANTHROPIC_API_KEY=<your key> -v mtg-data:/app/data mtg-deck-doctor
docker exec -it mtg-deck-doctor mtg-deck-doctor create-user you@example.com
```

## AI usage and limits

The Doctor's model calls are the app's only real running cost, so they are metered:

- **Admin page.** Open **Admin** in the app bar (`/admin`) to see what the Doctor has used: cost and tokens today and over the last 7, 14 or 30 days, a chart per day, a split by feature, and the latest calls. It refreshes every 15 seconds. The numbers come from `GET /usage`.
- **Usage log.** Every call is recorded in `data/usage.jsonl` with its feature, model, token counts, and an estimated cost. The estimate comes from token counts and published rates, so it tracks the invoice but is not the invoice.
- **Daily budget (optional).** Nothing is held back by default. Set `AI_DAILY_BUDGET_USD` and, once a day's estimated cost reaches it, the next call is refused with a 429 (`ai_budget`) until midnight UTC. It is meant for when other people use the app. For a hard stop on your account, set a spend limit in the Anthropic console.

What keeps each call small:

- **Tool calls per message.** A chat message makes at most `CHAT_MAX_TOOL_ROUNDS` model calls. Real messages take 2 to 7, so the cap only catches a loop that never ends. The last call gets no tools and has to say what it did and what is left, so you can ask it to continue.
- **Chat history.** The model sees the current turn in full. From earlier turns it sees what was said and the 12 most recent card lookups, and at most the last 20 turns. The stored conversation, and what you see in Correspondence, are unchanged.
- **Prompt caching.** The instructions and tool list are cached across messages, and the conversation so far is cached within a turn, so repeated calls pay a tenth of the input price for what hasn't changed.
- **Effort.** Chat and card suggestions run at `medium` effort (`ANTHROPIC_CHAT_EFFORT` sets chat's).

On a copy of a 41-message conversation, these changes cut what each call sends from about 32,000 tokens to about 5,600, and a two-call message cost about 3.5 cents.

## Sign in and public decks

The backend is closed to everyone, except for a deck's list. Once an account exists, every route refuses a browser that hasn't signed in, except the login routes and the public deck routes below. With no account, every route refuses every request (503) unless `MTG_DECK_DOCTOR_AUTH=off` says to run open, which `./dev-backend.sh` does. An account always turns the sign-in on, whatever `MTG_DECK_DOCTOR_AUTH` says, so a stray setting can't leave a server open.

- **Sign in.** Anyone who isn't signed in sees a landing page with the app's name and a short description, and nothing else, at every address except a deck's. The **Sign in** link in the app bar opens the sign-in page (`/login`), which brings you back to the page you were on once you're in. It asks for an email and a password, with a show/hide toggle for the password and a Caps Lock warning. A wrong email and a wrong password get the same answer, and take the same time. The backend then sets a signed, HTTP-only cookie that lasts 30 days and is marked secure over HTTPS. **Sign out** is in the app bar.
- **Wrong passwords are throttled.** After 8 failures from one address in 10 minutes, that address gets a 429 until the window moves on. Behind a reverse proxy, `--proxy-headers` (which `serve.sh` passes) makes the address the visitor's, not the proxy's.
- **A new route is closed by default.** Mark a route `@public` (in `auth.py`) to open it. `tests/test_auth.py` fails if the list of open routes changes.

### Accounts

There is no sign-up page. You make an account on the machine that holds the data, with a command that asks for the password without showing it. It never takes the password as an argument, because that would stay in the shell's history. Locally:

```bash
uv run mtg-deck-doctor create-user you@example.com
```

On Fly.io, run the same command in `fly ssh console`. The other commands:

| Command | What it does |
| --- | --- |
| `create-user EMAIL` | Makes an account. The first account takes every deck that has no owner. |
| `set-password EMAIL` | Sets a new password, which also signs the user out of every browser. |
| `revoke-sessions EMAIL` | Signs the user out of every browser, keeping the password. |
| `claim-decks EMAIL` | Gives every deck that has no owner to the account. |
| `list-users` | Lists the accounts, with when each was made and last signed in. |

`create-user` and `set-password` also take `--password-stdin`, which reads the password from standard input, for a script.

- **Passwords** are stored as salted scrypt hashes (`data/users/<id>.json`, readable by its owner only), never as text. The cost is kept with each hash, so it can be raised and an account's hash is upgraded at its next sign-in. A password needs at least 10 characters.
- **The login cookie** holds the user's id, a session version, an expiry and a signature made with a random secret in `data/session_secret`, which the backend creates on first use. Raising the session version ends every cookie the user has. Keep the secret with `data/`.
- **Each deck belongs to one account.** A signed-in user sees only their own decks, and another user's deck is a 404, the same as no deck. The public deck page is the one thing that reads any deck. While accounts exist, a deck with no owner belongs to no one until `claim-decks` gives it to one.
- **Not per account yet:** your collection, the card caches and the Doctor's usage numbers are shared by every account.

**Every deck's page is public to read.** Open `/decks/<id>` without signing in and you get the list, card details, rulings, stats and Export, and nothing else: no chat with the Doctor, no insights, no editing, no collection toggle, and no printing choices. Nothing a visitor can reach calls the model. Signed in, the same address is the whole deck page. The home page, search, your collection and Admin need the sign-in, so nobody can find a deck's address from the app. Send someone the address in your browser's address bar.

These routes answer without a sign-in: `GET /public/decks/{id}`, `POST /public/decks/{id}/cards`, and `GET /public/decks/{id}/rulings`. The first returns the name, commander, colors, cards, the printings you picked and the last-updated date, and never the conversation or the keep list. The other two answer only for cards in that deck, so they can't be used to look up other cards through your server. A deck's id is 8 random hex characters, so an address can be guessed in principle. The printings you pick (and whether a card is a foil) are kept with the deck, so a visitor sees the same art and prices as you do.

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
| `Dockerfile`, `fly.toml` | The image, and its Fly.io config. |
| `src/mtg_deck_doctor/server.py` | Serves the API under `/api` and the built front end, for running the app on one address. |
| `src/mtg_deck_doctor/auth.py` | Signing in: the session cookie, who is signed in on a request, and the throttle. |
| `src/mtg_deck_doctor/users.py`, `cli.py` | The accounts (files, password hashes), and the commands that make them. |
| `src/mtg_deck_doctor/tool_loop.py` | Every model call, with prompts, the chat's tools, and checks on what the model returns. |
| `src/mtg_deck_doctor/edhrec.py`, `card_cache.py`, `game_changers.py` | EDHREC and Scryfall clients with local caches. |
| `frontend/src/DeckView.tsx` | The deck page. |
| `frontend/src/ChatSuggestions.tsx`, `chatMessages.ts` | The Doctor's suggested changes, shown as buttons under its replies. |
| `context/` | Notes the model reads. |
| `tests/` | The test suite. |

## Data

Decks, your collection, and API caches are stored as JSON files under `data/`. The folder is git-ignored and is created as you use the app. There is no database, so the app is for one person. Keep `data/` on a disk that persists.

## Limits

- The Doctor's descriptions of what a card does come from the card's rules text, and can still be wrong.
