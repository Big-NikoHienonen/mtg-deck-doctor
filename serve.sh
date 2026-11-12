#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# The whole app on one address: builds the front end, then serves it and the API (under /api) from the
# backend. Set MTG_DECK_DOCTOR_PASSWORD first (in .env or the environment); without one the backend
# refuses every request. Behind a proxy or tunnel, --proxy-headers makes the throttle and the cookie's
# secure flag see the visitor and the real scheme.
(cd frontend && npm ci --silent && npm run build --silent)
exec uv run uvicorn mtg_deck_doctor.server:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}" --proxy-headers
