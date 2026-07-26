"""Tests for src/tools/trading_calendar.py"""
from datetime import date
import pytest

from src.tools.trading_calendar import is_trading_day, last_trading_day, last_trading_day_str


# ── is_trading_day ──────────────────────────────────────────────────────────

class TestIsTradingDay:
    def test_normal_weekday_is_trading(self):
        assert is_trading_day(date(2026, 7, 24), "NSE") is True   # Friday

    def test_saturday_is_not_trading(self):
        assert is_trading_day(date(2026, 7, 25), "NSE") is False  # Saturday

    def test_sunday_is_not_trading(self):
        assert is_trading_day(date(2026, 7, 26), "NSE") is False  # Sunday

    def test_republic_day_is_not_trading(self):
        assert is_trading_day(date(2026, 1, 26), "NSE") is False  # Monday, Republic Day

    def test_good_friday_is_not_trading_nse(self):
        assert is_trading_day(date(2026, 4, 3), "NSE") is False

    def test_christmas_is_not_trading_nse(self):
        assert is_trading_day(date(2026, 12, 25), "NSE") is False

    def test_christmas_is_not_trading_us(self):
        assert is_trading_day(date(2026, 12, 25), "US") is False

    def test_us_independence_day_observed(self):
        # July 4, 2026 is Saturday; July 3 is the observed holiday
        assert is_trading_day(date(2026, 7, 3), "US") is False

    def test_unknown_exchange_treats_weekdays_as_trading(self):
        assert is_trading_day(date(2026, 7, 24), "UNKNOWN") is True


# ── last_trading_day ─────────────────────────────────────────────────────────

class TestLastTradingDay:
    # --- weekends ---
    def test_saturday_returns_preceding_friday(self):
        assert last_trading_day(date(2026, 7, 25)) == date(2026, 7, 24)

    def test_sunday_returns_preceding_friday(self):
        assert last_trading_day(date(2026, 7, 26)) == date(2026, 7, 24)

    def test_regular_friday_returns_itself(self):
        assert last_trading_day(date(2026, 7, 24)) == date(2026, 7, 24)

    def test_regular_monday_returns_itself(self):
        assert last_trading_day(date(2026, 7, 27)) == date(2026, 7, 27)

    # --- single holiday ---
    def test_republic_day_monday_returns_preceding_friday(self):
        # Jan 26, 2026 is Monday (Republic Day) → last trading = Jan 23 (Fri)
        assert last_trading_day(date(2026, 1, 26)) == date(2026, 1, 23)

    def test_maharashtra_day_friday_returns_thursday(self):
        # May 1, 2026 is Friday (Maharashtra Day) → last trading = Apr 30 (Thu)
        assert last_trading_day(date(2026, 5, 1)) == date(2026, 4, 30)

    def test_gandhi_jayanti_friday_returns_thursday(self):
        # Oct 2, 2026 is Friday → last trading = Oct 1 (Thu)
        assert last_trading_day(date(2026, 10, 2)) == date(2026, 10, 1)

    def test_christmas_friday_returns_thursday(self):
        # Dec 25, 2026 is Friday → Dec 24 (Thu)
        assert last_trading_day(date(2026, 12, 25)) == date(2026, 12, 24)

    # --- holiday chains ---
    def test_good_friday_plus_ram_navami_chain(self):
        # Apr 3 = Good Friday, Apr 2 = Ram Navami → last trading = Apr 1 (Wed)
        assert last_trading_day(date(2026, 4, 3)) == date(2026, 4, 1)

    def test_saturday_after_christmas_skips_two_holidays(self):
        # Dec 26 = Saturday, Dec 25 = Friday holiday → last trading = Dec 24 (Thu)
        assert last_trading_day(date(2026, 12, 26)) == date(2026, 12, 24)

    # --- string input ---
    def test_accepts_iso_string(self):
        assert last_trading_day("2026-07-26") == date(2026, 7, 24)

    # --- last_trading_day_str ---
    def test_returns_iso_string(self):
        result = last_trading_day_str("2026-07-26", exchange="NSE")
        assert result == "2026-07-24"
        assert isinstance(result, str)

    # --- US exchange ---
    def test_us_independence_day_observed_skips_to_wednesday(self):
        # Jul 3 = observed US holiday (Fri), Jul 4 = Sat → last trading = Jul 2 (Thu)
        assert last_trading_day(date(2026, 7, 4), exchange="US") == date(2026, 7, 2)

    def test_us_regular_monday(self):
        assert last_trading_day(date(2026, 7, 6), exchange="US") == date(2026, 7, 6)

    def test_us_thanksgiving_thursday(self):
        # Nov 26, 2026 is Thanksgiving → Nov 25 (Wed)
        assert last_trading_day(date(2026, 11, 26), exchange="US") == date(2026, 11, 25)
