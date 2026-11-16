"""Two guards that sit around every request: a limit on how large a request body may be, and the
security headers on every response.

Both are plain ASGI middleware, so they see a request before FastAPI reads it and a response after
FastAPI has written it.
"""

from collections.abc import Callable

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# ---- request size ------------------------------------------------------------------------------------

# Most requests are a card name or a short list of them. The largest real ones are a pasted collection
# and a deck's printings, both well under this. Routes a stranger can reach get a much lower limit.
BODY_LIMIT_BYTES = 2 * 1024 * 1024
STRANGER_BODY_LIMIT_BYTES = 64 * 1024
STRANGER_PREFIXES = ("/auth/", "/public/")


def body_limit_for(path: str) -> int:
    return STRANGER_BODY_LIMIT_BYTES if path.startswith(STRANGER_PREFIXES) else BODY_LIMIT_BYTES


class BodyLimitMiddleware:
    """Refuses a request whose body is larger than the limit for its route, with a 413. It checks the
    declared length first, so an honest oversized request is turned away without being read, and counts
    the bytes as they arrive, so a request that lies about its length or sends no length is cut off too."""

    def __init__(self, app: ASGIApp, limit_for: Callable[[str], int] = body_limit_for) -> None:
        self.app = app
        self.limit_for = limit_for

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        # Under a mount, the path still starts with the mount's prefix; the routes are named without it.
        path = scope["path"].removeprefix(scope.get("root_path", ""))
        limit = self.limit_for(path)
        refusal = JSONResponse(status_code=413, content={"detail": "That request is too large."})

        for name, value in scope["headers"]:
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    return await JSONResponse(status_code=400, content={"detail": "Bad Content-Length."})(scope, receive, send)
                if declared > limit:
                    return await refusal(scope, receive, send)

        received = 0

        async def counted_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise HTTPException(status_code=413, detail="That request is too large.")
            return message

        await self.app(scope, counted_receive, send)


# ---- response headers --------------------------------------------------------------------------------

# What the page may load. Scripts only from this server. Styles from this server, from Google Fonts, and
# inline (React sets style attributes). Images from this server and from Scryfall's image hosts. The page
# itself calls Scryfall's API for search and autocomplete. Nothing may embed the page in a frame.
CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' data: https://fonts.gstatic.com",
        "img-src 'self' data: https://cards.scryfall.io https://svgs.scryfall.io",
        "connect-src 'self' https://api.scryfall.com",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)

SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}

# Tells a browser to use HTTPS for this host for a year. Sent only over HTTPS, where it means something.
HSTS = "max-age=31536000"


class SecurityHeadersMiddleware:
    """Adds the security headers to every response. `is_https` says whether a request came in over HTTPS,
    which decides whether the response also carries HSTS."""

    def __init__(self, app: ASGIApp, is_https: Callable[[Scope], bool]) -> None:
        self.app = app
        self.is_https = is_https

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        extra = dict(SECURITY_HEADERS)
        if self.is_https(scope):
            extra["Strict-Transport-Security"] = HSTS

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                present = {name.lower() for name, _ in message["headers"]}
                message["headers"] = list(message["headers"]) + [
                    (name.lower().encode("latin-1"), value.encode("latin-1")) for name, value in extra.items() if name.lower().encode("latin-1") not in present
                ]
            await send(message)

        await self.app(scope, receive, send_with_headers)
