"""
Tests for caching behaviour in src/tools/api.py.

AC-0301: search_line_items returns cached result on second call (no second HTTP request)
AC-0302: get_prices for yfinance tickers caches result; yf_api not called again on hit
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_START = "2025-01-01"
_END   = "2025-06-01"

_LINE_ITEMS_BODY = ["free_cash_flow", "net_income"]

_FAKE_SEARCH_RESPONSE = {
    "search_results": [
        {
            "ticker": "AAPL",
            "report_period": "2024-12-31",
            "period": "ttm",
            "currency": "USD",
            "free_cash_flow": 100_000,
            "net_income": 80_000,
        }
    ]
}

_FAKE_PRICE = MagicMock(
    open=100.0, high=110.0, low=95.0, close=105.0, volume=1_000_000,
    time="2025-01-02T00:00:00",
)
_FAKE_PRICE.model_dump.return_value = {
    "open": 100.0, "high": 110.0, "low": 95.0, "close": 105.0,
    "volume": 1_000_000, "time": "2025-01-02T00:00:00",
}


def _reset_cache():
    from src.data.cache import get_cache
    c = get_cache()
    c._prices_cache.clear()
    c._line_items_cache.clear()


# ---------------------------------------------------------------------------
# AC-0301: search_line_items caching
# ---------------------------------------------------------------------------

class TestSearchLineItemsCache:
    def setup_method(self):
        _reset_cache()

    def test_second_call_uses_cache_not_http(self):
        """AC-0301: same args → cache hit on second call; requests.post called once."""
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = _FAKE_SEARCH_RESPONSE

        with patch("src.tools.api._make_api_request", return_value=fake_response) as mock_req:
            from src.tools.api import search_line_items

            first  = search_line_items("AAPL", _LINE_ITEMS_BODY, _END, "ttm", 10)
            second = search_line_items("AAPL", _LINE_ITEMS_BODY, _END, "ttm", 10)

        assert len(first) == 1
        assert len(second) == 1
        # HTTP called exactly once — second call served from cache
        assert mock_req.call_count == 1

    def test_different_line_items_miss_cache(self):
        """Different line_items produce a different cache key → two HTTP calls."""
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = _FAKE_SEARCH_RESPONSE

        with patch("src.tools.api._make_api_request", return_value=fake_response) as mock_req:
            from src.tools.api import search_line_items

            search_line_items("AAPL", ["free_cash_flow"], _END, "ttm", 10)
            search_line_items("AAPL", ["net_income"], _END, "ttm", 10)

        assert mock_req.call_count == 2


# ---------------------------------------------------------------------------
# AC-0302: yfinance price caching
# ---------------------------------------------------------------------------

class TestYfinancePriceCache:
    def setup_method(self):
        _reset_cache()
        # Reset Kite singleton so .BO fallback doesn't try Kite
        import src.tools.api as api_mod
        api_mod._kite_client = None
        api_mod._kite_token_lookup = None

    def test_second_yf_call_uses_cache(self):
        """AC-0302: .BO ticker → yf_api called once; second call from cache."""
        with patch("src.tools.yf_api.get_prices", return_value=[_FAKE_PRICE]) as mock_yf:
            from src.tools.api import get_prices

            first  = get_prices("INFY.BO", _START, _END)
            second = get_prices("INFY.BO", _START, _END)

        assert len(first) == 1
        assert len(second) == 1
        assert mock_yf.call_count == 1
