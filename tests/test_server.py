"""Tests for serving the whole app from one address: the API under /api, the built front end for
everything else, and no way out of the front end's folder. No network and no model. Run with

    uv run python tests/test_server.py
"""

import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

import mtg_deck_doctor.deck as D
from mtg_deck_doctor import server

results: list[bool] = []


def check(name: str, ok: object, detail: str = "") -> None:
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


tmp = Path(tempfile.mkdtemp())
dist = tmp / "dist"
(dist / "assets").mkdir(parents=True)
(dist / "index.html").write_text("<!doctype html><title>shell</title>")
(dist / "assets" / "app-abc123.js").write_text("console.log(1)")
(dist / "favicon.svg").write_text("<svg/>")
(tmp / "secret.txt").write_text("outside the front end")

D.DECKS_DIR = tmp / "decks"
os.environ.pop("MTG_DECK_DOCTOR_PASSWORD", None)  # Whatever .env sets.
os.environ["MTG_DECK_DOCTOR_AUTH"] = "off"
c = TestClient(server.app, raise_server_exceptions=False)

# --- not built --------------------------------------------------------------------------------------

server.DIST = tmp / "nothing-here"
check("without a build the page says so", c.get("/").status_code == 503 and "npm run build" in c.get("/").json()["detail"])
check("...and the API still answers", c.get("/api/auth/status").status_code == 200)

# --- built ------------------------------------------------------------------------------------------

server.DIST = dist
res = c.get("/")
check("the home page is the page shell, never cached", res.status_code == 200 and "shell" in res.text and res.headers["cache-control"] == "no-cache")
for route in ["/decks/aaaa1111", "/admin", "/search/results"]:
    check(f"a link straight to {route.split('/')[1]} opens the shell", c.get(route).text == res.text)
res = c.get("/assets/app-abc123.js")
check("a built file is served, and kept for good when its name has a hash", res.status_code == 200 and "immutable" in res.headers["cache-control"])
check("a file in the root is served, not cached for good", c.get("/favicon.svg").text == "<svg/>" and c.get("/favicon.svg").headers["cache-control"] == "no-cache")
check("a missing file is a 404, not the shell", c.get("/assets/missing.js").status_code == 404 and c.get("/nope.png").status_code == 404)

for attempt in ["/../secret.txt", "/%2e%2e/secret.txt", "/..%2fsecret.txt", "/assets/../../secret.txt", "/%2e%2e%2fsecret.txt"]:
    body = c.get(attempt).text
    check(f"{attempt} can't reach a file outside the front end", "outside the front end" not in body)

# --- the API ----------------------------------------------------------------------------------------

check("the API is under /api", c.get("/api/decks").status_code == 200)
check("the API isn't also at the root, where the front end's routes are", c.get("/decks").text == res.text or "shell" in c.get("/decks").text)
check("an unknown API path is the API's own 404", c.get("/api/nothing").status_code == 404 and "shell" not in c.get("/api/nothing").text)

os.environ["MTG_DECK_DOCTOR_PASSWORD"] = "correct horse"
check("the login still guards the API from here", c.get("/api/decks").status_code == 401)
check("...and the page shell needs no login", c.get("/").status_code == 200)
signed_in = c.post("/api/auth/login", json={"password": "correct horse"})
check("signing in works under /api", signed_in.status_code == 200 and c.get("/api/decks").status_code == 200)
check("...with a cookie for the whole address", "path=/" in signed_in.headers["set-cookie"].lower())
os.environ.pop("MTG_DECK_DOCTOR_PASSWORD")

print(f"\n{sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
