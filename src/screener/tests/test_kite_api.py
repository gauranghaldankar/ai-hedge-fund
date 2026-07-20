"""
Tests for src/tools/kite_api.py — mocked, zero network calls.

AC-SCR-203c: returns None on token not found
AC-SCR-203d: returns None on historical_data error
AC-SCR-203e: importable without kiteconnect installed
AC-SCR-203f: build_token_lookup returns {} on any exception
AC-0118: Kite is primary price data source
AC-0119: yfinance is fallback when Kite fails
AC-0121: rate limit sleep applied per call
"""

from __future__ import annotations

import sys
import types
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_kite_stub(instruments=None, candles=None, raise_instruments=False, raise_historical=False):
    """Return a minimal mock KiteConnect instance."""
    kite = MagicMock()

    if raise_instruments:
        kite.instruments.side_effect = RuntimeError("network error")
    else:
        kite.instruments.return_value = instruments or []

    if raise_historical:
        kite.historical_data.side_effect = RuntimeError("API error")
    else:
        kite.historical_data.return_value = candles or []

    return kite


_SAMPLE_INSTRUMENTS = [
    {"tradingsymbol": "RELIANCE", "instrument_token": 738561, "instrument_type": "EQ"},
    {"tradingsymbol": "TCS", "instrument_token": 2953217, "instrument_type": "EQ"},
    {"tradingsymbol": "NIFTY25JUL24FUT", "instrument_token": 12345, "instrument_type": "FUT"},  # should be excluded
]

_SAMPLE_CANDLES = [
    {"date": date(2025, 1, 2), "open": 100.0, "high": 105.0, "low": 99.0, "close": 103.0, "volume": 1_000_000},
    {"date": date(2025, 1, 3), "open": 103.0, "high": 107.0, "low": 102.0, "close": 106.0, "volume": 1_200_000},
]


# ---------------------------------------------------------------------------
# build_token_lookup tests
# ---------------------------------------------------------------------------

def test_build_token_lookup_returns_eq_only():
    """build_token_lookup filters to EQ instrument_type only (AC-SCR-203e)."""
    from src.tools.kite_api import build_token_lookup

    kite = _make_kite_stub(instruments=_SAMPLE_INSTRUMENTS)
    lookup = build_token_lookup(kite)

    assert "RELIANCE" in lookup
    assert "TCS" in lookup
    assert "NIFTY25JUL24FUT" not in lookup
    assert lookup["RELIANCE"] == 738561


def test_build_token_lookup_returns_empty_on_exception():
    """Returns {} on any exception from kite.instruments (AC-SCR-203f)."""
    from src.tools.kite_api import build_token_lookup

    kite = _make_kite_stub(raise_instruments=True)
    lookup = build_token_lookup(kite)

    assert lookup == {}


# ---------------------------------------------------------------------------
# get_price_data_kite tests
# ---------------------------------------------------------------------------

def test_get_price_data_kite_returns_dataframe():
    """Returns a DataFrame with correct columns and ascending index (AC-0118)."""
    from src.tools.kite_api import get_price_data_kite

    kite = _make_kite_stub(candles=_SAMPLE_CANDLES)
    token_lookup = {"RELIANCE": 738561}

    with patch("time.sleep"):
        df = get_price_data_kite("RELIANCE", "2025-01-01", "2025-01-10",
                                  token_lookup=token_lookup, kite=kite)

    assert df is not None
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 2
    # Verify ascending sort
    assert df.index[0] < df.index[1]


def test_get_price_data_kite_returns_none_on_unknown_symbol():
    """Returns None when symbol is not in token_lookup (AC-SCR-203c)."""
    from src.tools.kite_api import get_price_data_kite

    kite = _make_kite_stub(candles=_SAMPLE_CANDLES)
    token_lookup = {"TCS": 2953217}

    with patch("time.sleep"):
        df = get_price_data_kite("RELIANCE", "2025-01-01", "2025-01-10",
                                  token_lookup=token_lookup, kite=kite)

    assert df is None


def test_get_price_data_kite_returns_none_on_historical_error():
    """Returns None when historical_data raises (AC-SCR-203d)."""
    from src.tools.kite_api import get_price_data_kite

    kite = _make_kite_stub(raise_historical=True)
    token_lookup = {"RELIANCE": 738561}

    with patch("time.sleep"):
        df = get_price_data_kite("RELIANCE", "2025-01-01", "2025-01-10",
                                  token_lookup=token_lookup, kite=kite)

    assert df is None


def test_get_price_data_kite_returns_none_on_empty_candles():
    """Returns None when historical_data returns an empty list."""
    from src.tools.kite_api import get_price_data_kite

    kite = _make_kite_stub(candles=[])
    token_lookup = {"RELIANCE": 738561}

    with patch("time.sleep"):
        df = get_price_data_kite("RELIANCE", "2025-01-01", "2025-01-10",
                                  token_lookup=token_lookup, kite=kite)

    assert df is None


def test_get_price_data_kite_applies_rate_limit_sleep():
    """time.sleep(0.35) is called before each historical_data call (AC-0121)."""
    from src.tools.kite_api import get_price_data_kite

    kite = _make_kite_stub(candles=_SAMPLE_CANDLES)
    token_lookup = {"RELIANCE": 738561}

    with patch("time.sleep") as mock_sleep:
        get_price_data_kite("RELIANCE", "2025-01-01", "2025-01-10",
                             token_lookup=token_lookup, kite=kite)
        mock_sleep.assert_called_once_with(0.35)


def test_get_price_data_kite_returns_none_without_kite_and_no_env():
    """Returns None gracefully when kite=None and env vars are not set (AC-SCR-203d)."""
    from src.tools.kite_api import get_price_data_kite

    # Patch get_kite_config to return empty credentials so no real API call is made
    with patch("src.config.kite_config.get_kite_config", return_value={"api_key": None, "access_token": ""}):
        df = get_price_data_kite("RELIANCE", "2025-01-01", "2025-01-10")

    assert df is None
