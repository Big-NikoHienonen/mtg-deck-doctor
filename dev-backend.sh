#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# The backend is closed until an account exists. For local work it runs open, so there is nothing to sign
# in to. Once you make an account (`uv run mtg-deck-doctor create-user <email>`), the sign-in is on.
export MTG_DECK_DOCTOR_AUTH=off
uv run uvicorn mtg_deck_doctor.api:app --port 8000 --reload
