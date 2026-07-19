"""Google Gemini API rate limiter — 15 RPM, 1500 req/day (free-tier limits).

Daily count persists to .agentco/google_rate.json so it survives restarts
within the same calendar day.
"""
import json
import threading
import time
from datetime import date
from pathlib import Path

RPM_LIMIT = 15
DAILY_LIMIT = 1500
# Minimum gap between consecutive requests = 60s / RPM.
# Enforcing this prevents concurrent agents from bursting all 15 slots
# simultaneously and triggering the API's own rate limiter.
_MIN_INTERVAL = 60.0 / RPM_LIMIT  # 4.0 seconds

_STATE = Path(".agentco/google_rate.json")
_LOCK = threading.Lock()
_window: list[float] = []        # monotonic timestamps in the last 60 s
_last_sent: float | None = None  # monotonic time of the most recent request


def _load() -> int:
    try:
        d = json.loads(_STATE.read_text())
        if d.get("date") == str(date.today()):
            return int(d.get("count", 0))
    except Exception:
        pass
    return 0


def _save(count: int) -> None:
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    _STATE.write_text(json.dumps({"date": str(date.today()), "count": count}))


def daily_used() -> int:
    """Return how many Google requests have been made today."""
    with _LOCK:
        return _load()


def acquire() -> bool:
    """Claim one Google API slot.

    - Enforces a minimum 4-second gap between consecutive requests so that
      concurrent agents cannot burst all 15 slots simultaneously and trigger
      the API's own server-side rate limiter.
    - Blocks further when the full 60-second RPM window fills up.
    - Returns False immediately when the daily quota is exhausted.
    - Returns True once the slot is reserved and recorded.
    """
    global _window, _last_sent
    with _LOCK:
        count = _load()
        if count >= DAILY_LIMIT:
            return False

        now = time.monotonic()

        # Enforce minimum inter-request spacing (prevents burst)
        if _last_sent is not None:
            gap = now - _last_sent
            if gap < _MIN_INTERVAL:
                time.sleep(_MIN_INTERVAL - gap)
                now = time.monotonic()

        # Safety net: if the full RPM window is still saturated, wait it out
        _window = [t for t in _window if now - t < 60.0]
        if len(_window) >= RPM_LIMIT:
            wait = 60.0 - (now - _window[0]) + 0.1
            if wait > 0:
                time.sleep(wait)
            now = time.monotonic()
            _window = [t for t in _window if now - t < 60.0]

        _last_sent = time.monotonic()
        _window.append(_last_sent)
        _save(count + 1)
        return True
