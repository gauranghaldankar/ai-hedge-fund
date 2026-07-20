"""
Tests for Kite Connect integration inside src/tools/api.py.

All Kite network calls are mocked — zero real HTTP traffic.
Pattern mirrors src/screener/tests/test_kite_api.py.

AC-0229: _init_kite() called once across two get_prices() calls (singleton)
AC-0230: ImportError during kiteconnect import leaves _kite_client=None, no raise
AC-0231: Valid Kite candles → list[Price] returned; yf_api NOT called
AC-0232: Kite returns None → fallback to yf_api.get_prices
AC-0233: .BO and US tickers bypass _init_kite() entirely
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_START = "2025-01-01"
_END = "2025-06-01"

_SAMPLE_DF = pd.DataFrame(
    {
        "open": [100.0, 101.0],
        "high": [105.0, 106.0],
        "low": [99.0, 100.0],
        "close": [103.0, 104.0],
        "volume": [1_000_000, 1_100_000],
    },
    index=pd.DatetimeIndex([datetime(2025, 1, 2), datetime(2025, 1, 3)], name="Date"),
)


def _reset_kite_globals():
    """Reset module-level Kite globals between tests."""
    import src.tools.api as api_mod
    api_mod._kite_client = None
    api_mod._kite_token_lookup = None


def _reset_cache():
    """Clear the in-process price cache between tests."""
    from src.data.cache import get_cache
    cache = get_cache()
    cache._prices_cache = {}


# ---------------------------------------------------------------------------
# AC-0229 — singleton: _init_kite called once, not twice
# ---------------------------------------------------------------------------

def test_init_kite_called_once_across_two_get_prices_calls():
    """AC-0229: Second get_prices() call reuses _kite_client without re-importing kiteconnect."""
    _reset_kite_globals()
    _reset_cache()

    mock_kite = MagicMock()
    mock_kite_cls = MagicMock(return_value=mock_kite)

    with patch.dict("sys.modules", {"kiteconnect": MagicMock(KiteConnect=mock_kite_cls)}), \
         patch("src.config.kite_config.get_kite_config", return_value={"api_key": "key", "access_token": "tok"}), \
         patch("src.tools.kite_api.build_token_lookup", return_value={"SGFIN": 123456}), \
         patch("src.tools.kite_api.get_price_data_kite", return_value=_SAMPLE_DF), \
         patch("time.sleep"):

        from src.tools.api import get_prices
        get_prices("SGFIN.NS", _START, _END)
        _reset_cache()
        get_prices("SGFIN.NS", _START, _END)

    # KiteConnect() constructor called exactly once across both get_prices() calls
    assert mock_kite_cls.call_count == 1


# ---------------------------------------------------------------------------
# AC-0230 — ImportError leaves _kite_client None, no raise
# ---------------------------------------------------------------------------

def test_init_kite_tolerates_missing_kiteconnect_package():
    """AC-0230: ImportError from kiteconnect leaves _kite_client=None; no exception raised.

    sys.modules[name] = None is the standard Python way to make `import name` raise ImportError.
    """
    import src.tools.api as api_mod
    _reset_kite_globals()

    # None entry in sys.modules causes `import kiteconnect` to raise ImportError
    with patch.dict("sys.modules", {"kiteconnect": None}):
        api_mod._init_kite()  # must not raise

    assert api_mod._kite_client is None


# ---------------------------------------------------------------------------
# AC-0231 — valid Kite candles → list[Price]; yf_api NOT called
# ---------------------------------------------------------------------------

def test_get_prices_ns_uses_kite_when_available():
    """AC-0231: When Kite returns valid candles, get_prices returns list[Price] without calling yf_api."""
    _reset_kite_globals()
    _reset_cache()

    mock_kite = MagicMock()
    mock_kite_cls = MagicMock(return_value=mock_kite)

    with patch.dict("sys.modules", {"kiteconnect": MagicMock(KiteConnect=mock_kite_cls)}), \
         patch("src.config.kite_config.get_kite_config", return_value={"api_key": "key", "access_token": "tok"}), \
         patch("src.tools.kite_api.build_token_lookup", return_value={"SGFIN": 123456}), \
         patch("src.tools.kite_api.get_price_data_kite", return_value=_SAMPLE_DF) as mock_kite_fetch, \
         patch("src.tools.yf_api.get_prices") as mock_yf, \
         patch("time.sleep"):

        from src.tools.api import get_prices
        prices = get_prices("SGFIN.NS", _START, _END)

    assert len(prices) == 2
    assert prices[0].open == 100.0
    assert prices[0].close == 103.0
    assert "2025-01-02" in prices[0].time
    mock_yf.assert_not_called()


# ---------------------------------------------------------------------------
# AC-0232 — Kite returns None → fallback to yf_api
# ---------------------------------------------------------------------------

def test_get_prices_ns_falls_back_to_yfinance_when_kite_returns_none():
    """AC-0232: When get_price_data_kite returns None, yf_api.get_prices is called exactly once."""
    import src.tools.api as api_mod
    _reset_kite_globals()
    _reset_cache()

    # Pre-seed Kite globals directly so _init_kite() is a no-op
    api_mod._kite_client = MagicMock()
    api_mod._kite_token_lookup = {"SGFIN": 123456}

    with patch("src.tools.kite_api.get_price_data_kite", return_value=None), \
         patch("src.tools.yf_api.get_prices", return_value=[]) as mock_yf:

        from src.tools.api import get_prices
        get_prices("SGFIN.NS", _START, _END)

    mock_yf.assert_called_once_with("SGFIN.NS", _START, _END)


# ---------------------------------------------------------------------------
# AC-0233 — .BO and US tickers bypass _init_kite entirely
# ---------------------------------------------------------------------------

def test_bo_ticker_bypasses_kite():
    """AC-0233: .BO ticker routes to yf_api without calling _init_kite."""
    _reset_kite_globals()
    _reset_cache()

    with patch("src.tools.yf_api.get_prices", return_value=[]) as mock_yf, \
         patch("src.tools.api._init_kite") as mock_init:

        from src.tools.api import get_prices
        get_prices("INFY.BO", _START, _END)

    mock_init.assert_not_called()
    mock_yf.assert_called_once()


def test_us_ticker_bypasses_kite_and_yfinance():
    """AC-0233: US ticker (no .NS/.BO suffix) goes to financialdatasets, not Kite or yfinance."""
    _reset_kite_globals()
    _reset_cache()

    with patch("src.tools.api._init_kite") as mock_init, \
         patch("src.tools.yf_api.get_prices") as mock_yf, \
         patch("src.tools.api._make_api_request") as mock_req:

        mock_req.return_value = MagicMock(status_code=200, json=lambda: {"ticker": "AAPL", "prices": []})

        from src.tools.api import get_prices
        get_prices("AAPL", _START, _END)

    mock_init.assert_not_called()
    mock_yf.assert_not_called()
