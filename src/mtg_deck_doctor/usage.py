"""What the Doctor's model calls use and cost, and the daily limit on spending.

Every call to the model goes through `tool_loop.create_message`, which asks
`check_budget` first and `record`s what the call used afterwards. One JSON line per
call goes to `data/usage.jsonl`: when, which feature, the model, the tokens, and an
estimated cost. The estimate is the sum of token counts times the published rates, so
it tracks the invoice closely but is not the invoice.

The daily budget is optional and off by default. Set `AI_DAILY_BUDGET_USD` to a dollar
amount and, once a UTC day's estimated cost reaches it, the next call raises
`AiBudgetExceeded` until the day rolls over. It is for when other people use the app.
The running total lives in memory, so this assumes one backend process.
"""

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

USAGE_PATH = Path("data/usage.jsonl")

DEFAULT_DAILY_BUDGET_USD = 0.0

# Dollars per million tokens: (input, output). Cached input is read at a tenth of the input
# rate and written at 1.25 times it. A model not listed is charged at Sonnet's rate.
PRICES = {
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
}
_DEFAULT_PRICE = (2.0, 10.0)
_CACHE_READ = 0.1
_CACHE_WRITE = 1.25

_lock = threading.Lock()
_today = {"day": None, "usd": 0.0}


class AiBudgetExceeded(Exception):
    """Today's estimated spending has reached the daily limit."""

    def __init__(self, spent: float, limit: float, resets_in: int):
        super().__init__(f"daily AI budget reached: ${spent:.2f} of ${limit:.2f}")
        self.spent, self.limit, self.resets_in = spent, limit, resets_in


def daily_budget() -> float:
    """The daily limit in dollars; 0 or less, unset or blank, means no limit."""
    try:
        return float(os.environ.get("AI_DAILY_BUDGET_USD", "").strip() or DEFAULT_DAILY_BUDGET_USD)
    except ValueError:
        return DEFAULT_DAILY_BUDGET_USD


def _now() -> datetime:
    return datetime.now(timezone.utc)


def seconds_until_reset() -> int:
    now = _now()
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((midnight - now).total_seconds()))


def cost_usd(model: str, usage) -> float:
    """The estimated cost of one response, from its `usage` block."""
    rate_in, rate_out = PRICES.get(model, _DEFAULT_PRICE)
    fresh = usage.input_tokens or 0
    read = getattr(usage, "cache_read_input_tokens", 0) or 0
    write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    return (fresh * rate_in + read * rate_in * _CACHE_READ + write * rate_in * _CACHE_WRITE + (usage.output_tokens or 0) * rate_out) / 1_000_000


def _entries() -> list[dict]:
    if not USAGE_PATH.exists():
        return []
    out = []
    for line in USAGE_PATH.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue  # a half-written line is not worth failing for
    return out


def spent_today() -> float:
    day = _now().strftime("%Y-%m-%d")
    with _lock:
        if _today["day"] != day:
            _today["day"] = day
            _today["usd"] = sum(e.get("usd", 0.0) for e in _entries() if str(e.get("at", "")).startswith(day))
        return _today["usd"]


def check_budget() -> None:
    """Raises AiBudgetExceeded if today's limit is already spent."""
    limit = daily_budget()
    if limit <= 0:
        return
    spent = spent_today()
    if spent >= limit:
        raise AiBudgetExceeded(spent, limit, seconds_until_reset())


def record(feature: str, model: str, usage, stop_reason: str | None = None, seconds: float | None = None) -> float:
    """Writes one call's usage to the log and the day's total; returns its estimated cost.
    Never raises: a failure to log must not fail the call it describes."""
    if usage is None:
        return 0.0
    try:
        usd = cost_usd(model, usage)
        entry = {
            "at": _now().isoformat(timespec="seconds"),
            "feature": feature,
            "model": model,
            "input": usage.input_tokens or 0,
            "output": usage.output_tokens or 0,
            "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
            "cache_write": getattr(usage, "cache_creation_input_tokens", 0) or 0,
            "usd": round(usd, 6),
            "stop": stop_reason,
            "seconds": round(seconds, 2) if seconds is not None else None,
        }
        spent_today()  # load the day's total before adding to it
        with _lock:
            USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with USAGE_PATH.open("a") as f:
                f.write(json.dumps(entry) + "\n")
            _today["usd"] += usd
        return usd
    except Exception:
        logger.warning("couldn't record model usage", exc_info=True)
        return 0.0


_ZERO = {"calls": 0, "usd": 0.0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0}


def _add(total: dict, entry: dict) -> None:
    total["calls"] += 1
    total["usd"] += entry.get("usd", 0.0)
    for field in ("input", "output", "cache_read", "cache_write"):
        total[field] += entry.get(field, 0)


def _rounded(total: dict) -> dict:
    return {**total, "usd": round(total["usd"], 4)}


def summary(days: int = 7, recent: int = 50) -> dict:
    """What the model calls used over the last `days` UTC days, by day and by feature, today's
    totals, the newest `recent` calls, and the daily limit if one is set."""
    today = _now().date()
    wanted = {(today - timedelta(days=i)).isoformat() for i in range(days)}
    entries = _entries()
    by_day: dict[str, dict] = {}
    by_feature: dict[str, dict] = {}
    for e in entries:
        day = str(e.get("at", ""))[:10]
        if day not in wanted:
            continue
        _add(by_day.setdefault(day, dict(_ZERO)), e)
        _add(by_feature.setdefault(e.get("feature", "?"), dict(_ZERO)), e)
    limit = daily_budget()
    today_totals = _rounded(by_day.get(today.isoformat(), dict(_ZERO)))
    return {
        "today_usd": today_totals["usd"],
        "today": today_totals,
        "daily_budget_usd": limit if limit > 0 else None,
        "resets_in_seconds": seconds_until_reset(),
        "by_day": {k: _rounded(v) for k, v in sorted(by_day.items())},
        "by_feature": {k: _rounded(v) for k, v in sorted(by_feature.items(), key=lambda kv: -kv[1]["usd"])},
        "recent": [
            {k: e.get(k) for k in ("at", "feature", "model", "input", "output", "cache_read", "cache_write", "usd", "seconds", "stop")}
            for e in reversed(entries[-recent:] if recent > 0 else [])
        ],
    }
