#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# The backend is closed unless an owner password is set. For local work it runs open, so there is
# nothing to sign in to. A password in .env or the environment still wins, to try the login.
export MTG_DECK_DOCTOR_AUTH=off
uv run uvicorn mtg_deck_doctor.api:app --port 8000 --reload
