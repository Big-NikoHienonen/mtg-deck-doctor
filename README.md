# MTG Deck Doctor

An AI-assisted deck builder and tuner for Magic: The Gathering's Commander format. You build the deck yourself, and the Doctor (Claude) suggests cards and answers questions about the list. It also reviews decks you already have.

The backend is FastAPI (Python, managed with uv). The front end is React and TypeScript (Vite). Card data comes from [Scryfall](https://scryfall.com) and [EDHREC](https://edhrec.com), and the model is called through the Anthropic API.

## What it does

**New deck** is a button in the app bar. It opens a window where you give the deck a name and search for a commander. Both are optional. **Create deck** takes you to the deck page. The "Start a deck with…" button on a new-commander suggestion does the same with that commander already set.

**Deck view** (`/decks/:id`) works on any deck, built here or imported:

- Deckbuilder: the list, grouped and sorted as you choose, with a card preview. Select a card, or the commander, to see its details, rulings, and printings, and to use it as a foil.
- Insights: EDHREC's top includes for your commander, a health check, cut suggestions, and swaps.
- Manalytics, under the list: the mana curve, the average and median mana value, how the colored symbols in the costs split between the colors, and a chart that sets each color's symbols beside the cards that make it. A color is flagged when its share of the sources is at least ten points below its share of the symbols, or when it has symbols and no source at all. A source is a land or other permanent that taps for the color, counted by copy and limited to the commander's colors. Fetch lands and cards that make Treasures aren't counted yet. Visitors to a public deck see it too.
- Correspondence: a chat with the Doctor about the deck, in a panel over the right side of the deck page. The deck stays in view beside it, and a click outside the panel or Esc closes it. It opens on the latest message, and "Show earlier" brings back the rest. A dot on the button says the Doctor is writing an answer, or has one waiting, while the panel is closed. The Doctor only suggests. It shows each card it wants to add or cut, or a commander it wants you to use, as a button under its reply, and nothing changes until you click it. The rules check every suggestion first: legality, color identity, the singleton rule, and the 99-card limit.
- Import and export decklists, pick printings (kept with the deck, so visitors see them), and track which cards you own.
- Public and private decks: each deck is public (the default) or private. Anyone can browse the public ones at `/browse` without signing in, and open one to look at the list, with no chat, insights, or editing. A private deck is its owner's alone. Decks show their builder's username, never an email. See [Public and private decks](#public-and-private-decks).

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
| `MTG_DECK_DOCTOR_PROXY` | Optional. `fly` when the app runs behind Fly.io's proxy, which `fly.toml` sets. The app then reads the visitor's address and scheme from the proxy's headers. Without it those headers are ignored, because anyone can send them. |
| `MTG_DECK_DOCTOR_REQUESTS_PER_HOUR` | Optional. The most requests one address may make in an hour, files included, when it isn't signed in. Defaults to `2000`; `0` turns the limit off. See [Sign in and public decks](#sign-in-and-public-decks). |
| `MTG_DECK_DOCTOR_ACCOUNT_REQUESTS_PER_HOUR` | Optional. The most requests one signed-in account may make in an hour. Defaults to `20000`; `0` turns the limit off. See [Sign in and public decks](#sign-in-and-public-decks). |
| `MTG_DECK_DOCTOR_AI_REQUESTS_PER_HOUR` | Optional. The most model calls one account may start in an hour. Defaults to `100`; `0` turns the limit off. See [AI usage and limits](#ai-usage-and-limits). |
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

A public deck's address, `<address>/decks/<id>`, opens a read-only view of the list for anyone who can reach it, and the deck is listed on the browse page (`/browse`). A private deck's address shows no deck to anyone but its owner. For a quick test from your own machine, point a tunnel at port 8000. To host it, you need a disk that persists, because decks, your collection, and the caches are files under `data/`, and `data/session_secret` signs the login cookie.

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

The server runs as the unprivileged user `app`, and the copy is made as root, so hand the files to `app`:

```bash
fly ssh console -C "chown -R app:app /app/data"
```

Then make your account on the Machine. The first account takes every deck that has no owner here, which includes the decks you copied, since each carries your local account's id and that account doesn't exist on the server. So make it after the copy. Open a shell as `app`, and the command asks for a password of at least 10 characters:

```bash
fly ssh console -u app
/app/.venv/bin/mtg-deck-doctor create-user you@example.com --username YourName
```

Open the app with `fly open` and sign in. A deck's address is `https://<app>.fly.dev/decks/<id>`.

Check that Fly passes the visitor's address through as the app expects, which the README can't know in advance. Send nine wrong sign-ins, each claiming a different address in `Fly-Client-IP`. The limit across all addresses (30 in 10 minutes) holds whatever Fly does, but the per-address limit (8) only works if Fly sets that header itself:

```bash
for i in 1 2 3 4 5 6 7 8 9; do
  curl -s -o /dev/null -w "%{http_code} " -H "Fly-Client-IP: 198.51.100.$i" \
    -H 'Content-Type: application/json' -d '{"email":"x@example.com","password":"wrong wrong wrong"}' \
    https://<app>.fly.dev/api/auth/login
done; echo
```

Eight `401`s and then a `429` mean the app counted all nine as one visitor, which is what you want. Nine `401`s mean a client can set `Fly-Client-IP`, so the per-address limit can be bypassed and only the overall limit protects the sign-in. Change `client_key` in `auth.py` to read another header. Wait ten minutes before you sign in, since these count against the overall limit.

`fly.toml` caps the Doctor at `AI_DAILY_BUDGET_USD = "5"` dollars a day. To change it, edit the number and run `fly deploy --ha=false` again. The cap is an estimate from token counts, so also set a spend limit on the key's workspace in the Anthropic console.

To run the image locally, with Docker running, then make an account in the running container:

```bash
docker build -t mtg-deck-doctor .
docker run -d --name mtg-deck-doctor -p 8080:8080 -e ANTHROPIC_API_KEY=<your key> -v mtg-data:/app/data mtg-deck-doctor
docker exec -it -u app mtg-deck-doctor mtg-deck-doctor create-user you@example.com --username YourName
```

## AI usage and limits

The Doctor's model calls are the app's only real running cost, so they are metered:

- **Admin page.** Open **Admin** in the app bar (`/admin`) to see what the Doctor has used: cost and tokens today and over the last 7, 14 or 30 days, a chart per day, a split by feature, and the latest calls. It refreshes every 15 seconds. The numbers come from `GET /usage`.
- **Usage log.** Every call is recorded in `data/usage.jsonl` with its feature, model, token counts, and an estimated cost. The estimate comes from token counts and published rates, so it tracks the invoice but is not the invoice.
- **Daily budget (optional).** Nothing is held back by default. Set `AI_DAILY_BUDGET_USD` and, once a day's estimated cost reaches it, the next call is refused with a 429 (`ai_budget`) until midnight UTC. It is meant for when other people use the app. For a hard stop on your account, set a spend limit in the Anthropic console.

- **Hourly limit per account.** One account may start 100 model calls an hour: a chat message, or a refresh of suggestions, cut reviews, new cards or new commanders. Reading a stored result doesn't count, and neither does a request that is refused before it reaches the model. Past the limit, the next call is refused with a 429 (`ai_account_limit`) and a `Retry-After`, and the page counts down to when you can ask again. It keeps one account from spending the whole day's budget in a stuck loop; the daily budget is the cap that counts. `MTG_DECK_DOCTOR_AI_REQUESTS_PER_HOUR` changes it, and `0` turns it off. The count is in memory, so a restart clears it.

What keeps each call small:

- **Tool calls per message.** A chat message makes at most `CHAT_MAX_TOOL_ROUNDS` model calls. Real messages take 2 to 7, so the cap only catches a loop that never ends. The last call gets no tools and has to say what it did and what is left, so you can ask it to continue.
- **Chat history.** The model sees the current turn in full. From earlier turns it sees what was said and the 12 most recent card lookups, and at most the last 20 turns. The stored conversation, and what you see in Correspondence, are unchanged.
- **Prompt caching.** The instructions and tool list are cached across messages, and the conversation so far is cached within a turn, so repeated calls pay a tenth of the input price for what hasn't changed.
- **Effort.** Chat and card suggestions run at `medium` effort (`ANTHROPIC_CHAT_EFFORT` sets chat's).

On a copy of a 41-message conversation, these changes cut what each call sends from about 32,000 tokens to about 5,600, and a two-call message cost about 3.5 cents.

## Sign in and public decks

The backend is closed to everyone, except for public decks. Once an account exists, every route refuses a browser that hasn't signed in, except the login routes and the public deck routes below. With no account, every route refuses every request (503) unless `MTG_DECK_DOCTOR_AUTH=off` says to run open, which `./dev-backend.sh` does. An account always turns the sign-in on, whatever `MTG_DECK_DOCTOR_AUTH` says, so a stray setting can't leave a server open.

- **Sign in.** Anyone who isn't signed in sees a landing page with the app's name, a short description and a Browse link, at every address except the browse page and a public deck's. The **Sign in** link in the app bar opens the sign-in page (`/login`), which brings you back to the page you were on once you're in. It asks for an email and a password, with a show/hide toggle for the password and a Caps Lock warning. A wrong email and a wrong password get the same answer, and take the same time. The backend then sets a signed, HTTP-only cookie that lasts 30 days and is marked secure over HTTPS. **Sign out** is in the app bar.
- **Sign-in attempts are limited.** Each attempt counts before the password is checked, so a burst can't all get through. One address gets 8 attempts in 10 minutes and then a 429 until the window moves on, and all addresses together get 30. The overall limit holds even if an attacker makes up addresses; it also means a flood of guesses can lock you out of the sign-in page for up to 10 minutes. A browser that is already signed in isn't affected. A right password gives that address its attempts back. An IPv6 visitor counts as one address per `/64`. Behind Fly.io, `MTG_DECK_DOCTOR_PROXY=fly` makes the address the one Fly's proxy saw; behind a proxy on the same machine, `--proxy-headers` (which `serve.sh` passes) does that.
- **Signing out ends every cookie the account has.** The cookie is a signed statement the server can't take back, so signing out raises the account's session version, which also ends a copy of the cookie and signs the account out of its other browsers. The cookie lasts 30 days otherwise.
- **A private deck can't be found.** Its public address answers 404, the same as an address with no deck, so its existence isn't revealed. A new deck's id is also 16 random hex digits (64 bits), so a public address can't be guessed either. Ids made before that have 8 and still work. A client that asks for 20 public addresses with no deck behind them in 10 minutes gets a 429 on every public deck route until the window moves on.
- **Requests and inputs have limits.** A request body over 64 KB on a route a stranger can reach, or 2 MB on any other, gets a 413 without being read in full. A card name is at most 200 characters, a deck name 100, a chat message 8,000, a count or quantity 99, and a list 1,000 entries (20,000 for a collection import). `api.py` names them at the top of the request models.
- **Requests per hour are limited.** A request without a sign-in is counted against its address: 2,000 an hour, files and API calls alike. A page load is about ten requests, so the limit stops a script and not a person. A request with a genuine sign-in cookie is counted against its account instead, with a limit of 20,000 an hour that stops a page stuck in a loop and no person. Accounts are made by the owner, so sharing an address with a stranger or a scripted visitor can't lock a signed-in person out. A forged or expired cookie counts as no cookie. Past a limit, the request gets a 429 with a `Retry-After` until the count falls. The window slides, so waiting out the `Retry-After` works and a burst at the top of an hour doesn't double the limit. The address is the one the sign-in limit uses, so the `Fly-Client-IP` check in [Deploy on Fly.io](#deploy-on-flyio) applies to the address limit too. Everyone without a sign-in behind one shared address, such as an office, shares one count. The counts are in memory, so a restart clears them, and they assume one Machine. `MTG_DECK_DOCTOR_REQUESTS_PER_HOUR` and `MTG_DECK_DOCTOR_ACCOUNT_REQUESTS_PER_HOUR` change the limits, and `0` turns one off. Fly's health check, every 30 seconds, uses 120 of its own address's hour.
- **Security headers.** Every response carries a Content-Security-Policy that allows scripts only from this server and the page's own hosts (Scryfall's API and images, Google Fonts), `X-Frame-Options: DENY`, `nosniff`, a referrer policy and a permissions policy, and HSTS over HTTPS. `hardening.py` holds the list. If the page needs a new outside host, add it to the policy there.
- **No API docs.** `/docs`, `/redoc` and the OpenAPI schema are off.
- **The server runs as `app`, not root.** The image's entrypoint hands `/app/data` to `app` and drops root before it starts. `mtg-deck-doctor` run as root acts as the owner of `data/` for the same reason.
- **A new route is closed by default.** Mark a route `@public` (in `auth.py`) to open it. `tests/test_auth.py` fails if the list of open routes changes.

### Accounts

There is no sign-up page. You make an account on the machine that holds the data, with a command that asks for the password without showing it. It never takes the password as an argument, because that would stay in the shell's history. Locally:

```bash
uv run mtg-deck-doctor create-user you@example.com --username YourName
```

On Fly.io, run the same command in `fly ssh console`. The other commands:

| Command | What it does |
| --- | --- |
| `create-user EMAIL` | Makes an account, with `--username NAME` if you want one now. The first account takes every deck that has no owner here: none, or an owner with no account on this machine. |
| `set-username EMAIL NAME` | Gives an account a username, or a new one. |
| `set-password EMAIL` | Sets a new password, which also signs the user out of every browser. |
| `revoke-sessions EMAIL` | Signs the user out of every browser, keeping the password. |
| `claim-decks EMAIL` | Gives every deck that has no owner here to the account. A deck owned by an account here is left alone. |
| `list-users` | Lists the accounts, with when each was made and last signed in. |

`create-user` and `set-password` also take `--password-stdin`, which reads the password from standard input, for a script.

- **Passwords** are stored as salted scrypt hashes (`data/users/<id>.json`, readable by its owner only), never as text. The cost is kept with each hash, so it can be raised and an account's hash is upgraded at its next sign-in. A password needs at least 10 characters.
- **The login cookie** holds the user's id, a session version, an expiry and a signature made with a random secret in `data/session_secret`, which the backend creates on first use. Raising the session version ends every cookie the user has. Keep the secret with `data/`.
- **Each deck belongs to one account.** A signed-in user sees only their own decks, and another user's deck is a 404, the same as no deck. The public deck routes are the one thing that reads any public deck. While accounts exist, a deck with no owner belongs to no one until `claim-decks` gives it to one.
- **Not per account yet:** your collection, the card caches and the Doctor's usage numbers are shared by every account.

### Public and private decks

Every deck is **public** or **private**. A new deck is public unless you choose otherwise, in the New deck window or with the **Public/Private** button on the deck's page, which you can press any time. Decks made before there was a choice are public.

- **Browse** (`/browse`, in the app bar and on the front door) lists public decks that have a commander, newest first or by name, with a search over the deck's title, its commander and its builder's username. It needs no sign-in. A deck made private leaves it at once.
- **A public deck's page** (`/decks/<id>`) shows anyone, signed in or not, the list, card details, rulings, stats and Export, and who built it. There is no chat with the Doctor, no insights, no editing, no collection toggle and no printing choices. Nothing a visitor can reach calls the model. Its owner gets the whole deck page at the same address.
- **A private deck** is visible to its owner alone. Every public route answers 404 for it, for strangers and for other signed-in users alike, so it looks the same as a deck that doesn't exist.
- **Usernames.** What people see beside a public deck is the builder's username, never their email. Set one on your profile (your name in the app bar, `/profile`), or with `create-user --username` or `set-username` on the server. It is 3 to 24 letters, numbers, hyphens and underscores, can't be taken by two accounts (capitals don't count), can't be a reserved name like `admin`, and has to pass the profanity check. Until an account has a username, its decks are listed as "by an anonymous builder".
- **Profanity check.** Usernames and deck names are checked when they are set, and a name that fails is refused without saying which word. `moderation.py` holds a short, strict list of strong profanity, sexual terms and slurs, and leaves mild words (damn, hell, crap) alone on purpose, because deck names are often card names and puns: "Hell's Caretaker", "Cockatrice" and "Assassin's Trophy" all pass. It sees through common disguises (`sh1t`, `f.u.c.k`, `fuuuck`, look-alike letters) but not everything. A name saved before the check, or before the list grew, is shown to strangers as the commander's name instead.

These routes answer without a sign-in: `GET /public/decks` (the browse list, 120 requests a minute per address), `GET /public/decks/{id}`, `POST /public/decks/{id}/cards`, and `GET /public/decks/{id}/rulings`. A deck's page returns the name, commander, colors, cards, the printings you picked, the builder's username and the last-updated date, and never the conversation, the keep list, the owner's id or email. The cards and rulings routes answer only for cards in that deck, so they can't be used to look up other cards through your server. The printings you pick (and whether a card is a foil) are kept with the deck, so a visitor sees the same art and prices as you do.

## Test

The tests stub the model, EDHREC, and Scryfall, so they need no network or API key. Run them all:

```bash
for t in tests/test_*.py; do uv run python "$t" || break; done
```

Each file is a script that prints one line per check and exits with 1 if any fails, so you can also run one on its own, for example `uv run python tests/test_chat.py`.

The one front-end test, for the Manalytics comparison of symbols with sources, is TypeScript that Node runs as it is (Node 22.18 or later): `node tests/test_mana_balance.ts`.

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
| `src/mtg_deck_doctor/auth.py` | Signing in: the session cookie, who is signed in on a request, and the limits on guessing and on request volume. |
| `src/mtg_deck_doctor/hardening.py` | The request volume limit, the request size limit and the security headers. |
| `src/mtg_deck_doctor/moderation.py` | The profanity check for usernames and deck names. |
| `docker-entrypoint.sh` | Starts the container as root only to hand `data/` to `app`, then drops root. |
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
