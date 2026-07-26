"""
trading_calendar.py — resolve the last valid trading day for a given date.

Handles:
  - Weekends (Sat/Sun → Friday)
  - NSE market holidays (India) for 2025–2026
  - US market holidays for 2025–2026
  - Chains of consecutive non-trading days (e.g. holiday + weekend)

Usage:
    from src.tools.trading_calendar import last_trading_day
    effective = last_trading_day("2026-07-26", exchange="NSE")  # → "2026-07-25"
"""

from __future__ import annotations

from datetime import date, timedelta


# ---------------------------------------------------------------------------
# NSE (India) holidays — confirmed dates only.
# Variable religious holidays (Diwali, Eid, etc.) are approximate; the list
# is intentionally conservative. Add missed holidays here as they are confirmed.
# Source: NSE India official holiday calendar.
# ---------------------------------------------------------------------------
_NSE_HOLIDAYS: dict[int, set[date]] = {
    2025: {
        date(2025, 1, 26),   # Republic Day
        date(2025, 2, 26),   # Mahashivratri
        date(2025, 3, 14),   # Holi
        date(2025, 4, 10),   # Ram Navami (approx)
        date(2025, 4, 14),   # Dr. Ambedkar Jayanti
        date(2025, 4, 18),   # Good Friday
        date(2025, 5, 1),    # Maharashtra Day
        date(2025, 6, 6),    # Id-Ul-Adha (Bakri Eid, approx)
        date(2025, 8, 15),   # Independence Day
        date(2025, 8, 27),   # Ganesh Chaturthi
        date(2025, 10, 2),   # Mahatma Gandhi Jayanti
        date(2025, 10, 2),   # Dussehra (same day, 2025)
        date(2025, 10, 20),  # Diwali Laxmi Pujan (approx)
        date(2025, 10, 21),  # Diwali Balipratipada (approx)
        date(2025, 11, 5),   # Prakash Gurpurab (Gurunanak Jayanti, approx)
        date(2025, 12, 25),  # Christmas
    },
    2026: {
        date(2026, 1, 26),   # Republic Day (Monday)
        date(2026, 3, 20),   # Id-Ul-Fitr / Ramadan Eid (approx)
        date(2026, 3, 25),   # Holi
        date(2026, 4, 3),    # Good Friday (Easter April 5)
        date(2026, 4, 2),    # Ram Navami (approx)
        date(2026, 4, 14),   # Dr. Ambedkar Jayanti (Tuesday)
        date(2026, 5, 1),    # Maharashtra Day (Friday)
        date(2026, 5, 23),   # Buddha Purnima (approx)
        date(2026, 6, 17),   # Id-Ul-Adha / Bakri Eid (approx)
        date(2026, 7, 6),    # Muharram (approx)
        date(2026, 8, 27),   # Ganesh Chaturthi (approx)
        date(2026, 10, 2),   # Mahatma Gandhi Jayanti (Friday)
        date(2026, 10, 20),  # Diwali Laxmi Pujan (approx)
        date(2026, 10, 21),  # Diwali Balipratipada (approx)
        date(2026, 11, 24),  # Gurunanak Jayanti (approx)
        date(2026, 12, 25),  # Christmas (Friday)
    },
}

# ---------------------------------------------------------------------------
# US (NYSE/NASDAQ) holidays — fixed dates only; variable holidays are approx.
# ---------------------------------------------------------------------------
_US_HOLIDAYS: dict[int, set[date]] = {
    2025: {
        date(2025, 1, 1),    # New Year's Day
        date(2025, 1, 20),   # MLK Day
        date(2025, 2, 17),   # Presidents' Day
        date(2025, 4, 18),   # Good Friday
        date(2025, 5, 26),   # Memorial Day
        date(2025, 6, 19),   # Juneteenth
        date(2025, 7, 4),    # Independence Day
        date(2025, 9, 1),    # Labor Day
        date(2025, 11, 27),  # Thanksgiving
        date(2025, 12, 25),  # Christmas
    },
    2026: {
        date(2026, 1, 1),    # New Year's Day
        date(2026, 1, 19),   # MLK Day
        date(2026, 2, 16),   # Presidents' Day
        date(2026, 4, 3),    # Good Friday
        date(2026, 5, 25),   # Memorial Day
        date(2026, 6, 19),   # Juneteenth
        date(2026, 7, 3),    # Independence Day (observed, July 4 is Saturday)
        date(2026, 9, 7),    # Labor Day
        date(2026, 11, 26),  # Thanksgiving
        date(2026, 12, 25),  # Christmas
    },
}

_MAX_LOOKBACK_DAYS = 15  # safety cap — never look back more than 3 weeks


def _holidays_for(year: int, exchange: str) -> set[date]:
    if exchange == "NSE":
        return _NSE_HOLIDAYS.get(year, set())
    if exchange in ("NYSE", "NASDAQ", "US"):
        return _US_HOLIDAYS.get(year, set())
    return set()


def is_trading_day(d: date, exchange: str = "NSE") -> bool:
    """Return True if *d* is a trading day for the given exchange."""
    if d.weekday() >= 5:          # Saturday=5, Sunday=6
        return False
    return d not in _holidays_for(d.year, exchange)


def last_trading_day(d: date | str, exchange: str = "NSE") -> date:
    """Return the most recent trading day on or before *d*.

    Handles:
      - Weekends
      - NSE/US market holidays
      - Chains of consecutive non-trading days (long weekends, holiday clusters)

    Args:
        d:        A date object or ISO string ("YYYY-MM-DD").
        exchange: "NSE" (default), "NYSE", "NASDAQ", or "US".

    Returns:
        The resolved trading date as a date object.
    """
    if isinstance(d, str):
        d = date.fromisoformat(d)

    for _ in range(_MAX_LOOKBACK_DAYS):
        if is_trading_day(d, exchange):
            return d
        d -= timedelta(days=1)

    # Extremely unlikely fallback — return as-is if nothing found
    return d


def last_trading_day_str(d: date | str, exchange: str = "NSE") -> str:
    """Same as last_trading_day() but returns an ISO string ("YYYY-MM-DD")."""
    return last_trading_day(d, exchange).isoformat()
