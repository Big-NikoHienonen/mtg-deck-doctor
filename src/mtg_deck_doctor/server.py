"""The whole app on one address: the API under /api, and the built front end for everything else.

    uv run uvicorn mtg_deck_doctor.server:app --port 8000 --proxy-headers

One address means the login cookie is first-party and no cross-origin requests happen, so the app can
sit behind any host or tunnel without extra settings. Build the front end first (`cd frontend && npm run
build`); see `serve.sh`. In development the front end runs on Vite's server instead, which sends /api to
the backend on port 8000 (see `frontend/vite.config.ts`), so `api:app` still runs on its own there.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from starlette.types import Scope

from mtg_deck_doctor import auth
from mtg_deck_doctor.api import app as api_app
from mtg_deck_doctor.hardening import RateLimitMiddleware, SecurityHeadersMiddleware

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

app = FastAPI(title="MTG Deck Doctor", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/api", api_app)


# The last middleware added is the outermost, so the security headers go on a 429 too.
app.add_middleware(RateLimitMiddleware, begin=auth.count_request)
app.add_middleware(SecurityHeadersMiddleware, is_https=auth.is_https)

# The page shell must never be served from a cache, or a new build isn't picked up. The files in
# /assets have a content hash in their names, so those can be kept for good.
_NO_CACHE = {"Cache-Control": "no-cache"}
_FOREVER = {"Cache-Control": "public, max-age=31536000, immutable"}


@app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
def front_end(path: str) -> FileResponse:
    """A built file if there is one, and the page shell for everything else, so that a link straight to
    /decks/abc or /search/results opens the app, which then shows that route."""
    if not (DIST / "index.html").is_file():
        raise HTTPException(status_code=503, detail="The front end isn't built. Run `npm run build` in frontend/.")
    try:
        target = (DIST / path).resolve()
    except (ValueError, OSError):  # A path with a NUL byte in it, or one the system can't read.
        raise HTTPException(status_code=404, detail="Not found.")
    if path and target.is_file() and DIST.resolve() in target.parents:
        return FileResponse(target, headers=_FOREVER if target.parent.name == "assets" else _NO_CACHE)
    # A path that looks like a file but isn't there is a missing file, not a route of the app.
    if Path(path).suffix:
        raise HTTPException(status_code=404, detail="Not found.")
    return FileResponse(DIST / "index.html", headers=_NO_CACHE)
