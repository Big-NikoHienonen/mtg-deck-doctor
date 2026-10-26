"""What went wrong when a call to the model failed, in words the player can act on.

Every model call can fail for reasons that have nothing to do with the request:
the account is out of credits, the key was rejected, the API is rate-limiting or
overloaded, or the network dropped. `describe` sorts those into a short code the
frontend can branch on, a plain message, and whether waiting helps.
"""

import anthropic

# Codes whose cause only a person can fix — retrying changes nothing until they do.
PERSISTENT = {"ai_credits", "ai_auth"}

_DEFAULT_WAIT = {"ai_rate_limited": 30, "ai_busy": 15, "ai_offline": 10, "ai_error": 10}


def _retry_after(err: anthropic.APIError, default: int) -> int:
    """Seconds to wait: the API's own Retry-After when it sends one, within sane bounds."""
    response = getattr(err, "response", None)
    try:
        wait = int(float(response.headers.get("retry-after", ""))) if response is not None else default
    except ValueError:
        wait = default
    return max(1, min(wait, 120))


def describe(err: anthropic.APIError) -> tuple[int, dict]:
    """(HTTP status, JSON body) for a failed model call. The body has `detail`
    (the message), `code`, and `retry_after` in seconds — None when only a
    person can fix the cause."""
    if isinstance(err, anthropic.APIConnectionError):  # includes timeouts
        code, status = "ai_offline", 503
        detail = "Couldn't reach the Anthropic API. Check the internet connection, then try again."
    elif isinstance(err, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
        code, status = "ai_auth", 503
        detail = "Anthropic rejected the API key. Check ANTHROPIC_API_KEY in the backend's environment, then restart it."
    elif isinstance(err, anthropic.RateLimitError):
        code, status = "ai_rate_limited", 429
        detail = "The Anthropic API is rate-limiting requests right now."
    elif isinstance(err, anthropic.APIStatusError) and "credit balance" in str(err).lower():
        code, status = "ai_credits", 503
        detail = "The Anthropic account behind the Doctor is out of credits. Add credits under Plans & Billing at console.anthropic.com, then check again."
    elif isinstance(err, anthropic.APIStatusError) and err.status_code >= 500:
        code, status = "ai_busy", 503
        detail = "The Anthropic API is overloaded or having trouble right now."
    else:
        code, status = "ai_error", 502
        detail = "The Doctor hit an unexpected error talking to the model."
    wait = None if code in PERSISTENT else _retry_after(err, _DEFAULT_WAIT[code])
    if wait is not None:
        detail += f" Try again in {wait} seconds."
    return status, {"detail": detail, "code": code, "retry_after": wait}
