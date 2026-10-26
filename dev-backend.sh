#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
uv run uvicorn mtg_deck_doctor.api:app --port 8000 --reload
