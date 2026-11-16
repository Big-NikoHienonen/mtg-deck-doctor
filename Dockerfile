# The whole app in one image: the built front end, and the backend that serves it and the API.
# Build:  docker build -t mtg-deck-doctor .
# Run:    docker run -p 8080:8080 -e ANTHROPIC_API_KEY=... -v mtg-data:/app/data mtg-deck-doctor
# Account: docker exec -it -u app <container> mtg-deck-doctor create-user <email>

# --- The front end ---------------------------------------------------------------------------------
FROM node:22-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- The backend, with the front end inside it -----------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app

# Use the image's Python, never download another. The project installs in editable mode from /app/src,
# which is where server.py looks for frontend/dist.
ENV UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Dependencies first, so a code change doesn't reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY context ./context
RUN uv sync --frozen --no-dev
COPY --from=frontend /build/frontend/dist ./frontend/dist

# The server runs as `app`, not root, so a flaw in it can't change the image. The entrypoint starts as
# root only to hand the data volume to `app` (a new volume is owned by root), then drops root.
RUN useradd --system --create-home --uid 10001 --shell /bin/sh app \
    && mkdir -p /app/data \
    && chown app:app /app/data
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh

# Decks, your collection, the card caches and the login secret are files under /app/data. Mount a
# volume there, or they are lost when the container is replaced.
VOLUME /app/data

EXPOSE 8080

# Behind Fly's proxy, MTG_DECK_DOCTOR_PROXY=fly (set in fly.toml) tells the app to read the visitor's address
# and scheme from the headers Fly sets. Without it those headers are ignored, because anyone can send them.
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "mtg_deck_doctor.server:app", "--host", "0.0.0.0", "--port", "8080"]
