"""NSE trading holidays and trading-day helpers."""

from datetime import date, timedelta

# NSE trading holidays for 2025 and 2026
# Source: NSE official calendar
NSE_HOLIDAYS: set[date] = {
    # 2025
    date(2025, 1, 26),   # Republic Day
    date(2025, 2, 26),   # Mahashivratri
    date(2025, 3, 14),   # Holi
    date(2025, 3, 31),   # Id-Ul-Fitr (Ramzan Eid)
    date(2025, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti / Ram Navami
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 1),    # Maharashtra Day
    date(2025, 8, 15),   # Independence Day
    date(2025, 8, 27),   # Ganesh Chaturthi
    date(2025, 10, 2),   # Gandhi Jayanti
    date(2025, 10, 2),   # Dussehra
    date(2025, 10, 20),  # Diwali (Laxmi Pujan)
    date(2025, 10, 21),  # Diwali (Balipratipada)
    date(2025, 11, 5),   # Prakash Gurpurb
    date(2025, 12, 25),  # Christmas
    # 2026
    date(2026, 1, 26),   # Republic Day
    date(2026, 2, 26),   # Mahashivratri
    date(2026, 3, 20),   # Holi
    date(2026, 3, 20),   # Id-Ul-Fitr
    date(2026, 4, 3),    # Good Friday
    date(2026, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 8, 15),   # Independence Day
    date(2026, 9, 19),   # Ganesh Chaturthi (Saturday - exchange may trade)
    date(2026, 10, 2),   # Gandhi Jayanti
    date(2026, 10, 8),   # Dussehra
    date(2026, 10, 27),  # Diwali (Laxmi Pujan)
    date(2026, 10, 28),  # Diwali (Balipratipada)
    date(2026, 11, 25),  # Gurunanak Jayanti
    date(2026, 12, 25),  # Christmas
}


def is_trading_day(d: date) -> bool:
    """Return True if the date is an NSE trading day (Mon–Fri, not a holiday)."""
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    return d not in NSE_HOLIDAYS


def last_n_trading_days(n: int, reference: date | None = None) -> list[date]:
    """Return the last n trading days ending on or before reference date (default today)."""
    from datetime import date as date_type
    ref = reference or date_type.today()
    result: list[date] = []
    current = ref
    while len(result) < n:
        if is_trading_day(current):
            result.append(current)
        current -= timedelta(days=1)
    return result
