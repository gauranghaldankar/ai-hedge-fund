"""
Unit tests for src/screener/scorer.py — all pure functions, no network calls.

AC-0101 (zero LLM), AC-0102 (sub-scores 0–100)
"""

import pytest
import pandas as pd

from src.screener.scorer import (
    _safe_float,
    _clamp,
    score_valuation,
    score_fundamentals,
    score_jhunjhunwala,
    score_growth,
    score_insider,
    score_technical,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ticker_data(**kwargs):
    """Build minimal ticker_data dict with overrides."""
    base = {"ticker": "TEST.NS", "financial_metrics": [], "prices_df": None, "insider_trades": []}
    base.update(kwargs)
    return base


def _metrics(**kwargs):
    """Build a financial metrics dict."""
    return {**kwargs}


# ---------------------------------------------------------------------------
# _safe_float
# ---------------------------------------------------------------------------

def test_safe_float_none():
    assert _safe_float(None) == 0.0


def test_safe_float_nan():
    import math
    assert _safe_float(float("nan")) == 0.0


def test_safe_float_normal():
    assert _safe_float("3.14") == pytest.approx(3.14)


# ---------------------------------------------------------------------------
# _clamp
# ---------------------------------------------------------------------------

def test_clamp_within():
    assert _clamp(50.0) == 50.0


def test_clamp_above():
    assert _clamp(150.0) == 100.0


def test_clamp_below():
    assert _clamp(-10.0) == 0.0


# ---------------------------------------------------------------------------
# score_valuation
# ---------------------------------------------------------------------------

def test_valuation_no_data_returns_neutral():
    assert score_valuation(_ticker_data()) == pytest.approx(50.0)


def test_valuation_undervalued():
    # intrinsic_value >> price → high margin of safety → score > 50
    m = _metrics(intrinsic_value=200.0, price=100.0)
    result = score_valuation(_ticker_data(financial_metrics=[m]))
    assert result > 50.0


def test_valuation_overvalued():
    # price >> intrinsic_value → negative margin of safety → score < 50
    m = _metrics(intrinsic_value=50.0, price=200.0)
    result = score_valuation(_ticker_data(financial_metrics=[m]))
    assert result < 50.0


def test_valuation_always_in_range():
    for intrinsic in [0, 50, 100, 500]:
        for price in [1, 50, 100, 300]:
            m = _metrics(intrinsic_value=float(intrinsic), price=float(price))
            result = score_valuation(_ticker_data(financial_metrics=[m]))
            assert 0.0 <= result <= 100.0, f"Out of range for intrinsic={intrinsic}, price={price}"


# ---------------------------------------------------------------------------
# score_fundamentals
# ---------------------------------------------------------------------------

def test_fundamentals_no_data_returns_neutral():
    assert score_fundamentals(_ticker_data()) == pytest.approx(50.0)


def test_fundamentals_strong_company():
    m = _metrics(
        return_on_equity=0.30,    # > 15% target
        net_margin=0.20,          # > 15% target
        debt_to_equity=0.2,       # low debt
        current_ratio=2.5,        # healthy
        operating_margin=0.25,    # > 20% target
    )
    result = score_fundamentals(_ticker_data(financial_metrics=[m]))
    assert result > 70.0


def test_fundamentals_weak_company():
    m = _metrics(
        return_on_equity=0.02,
        net_margin=0.02,
        debt_to_equity=2.5,
        current_ratio=0.5,
        operating_margin=0.02,
    )
    result = score_fundamentals(_ticker_data(financial_metrics=[m]))
    assert result < 30.0


def test_fundamentals_always_in_range():
    for roe in [-0.2, 0, 0.15, 0.5]:
        for de in [0, 0.5, 2.0, 5.0]:
            m = _metrics(return_on_equity=roe, debt_to_equity=de)
            result = score_fundamentals(_ticker_data(financial_metrics=[m]))
            assert 0.0 <= result <= 100.0


# ---------------------------------------------------------------------------
# score_growth
# ---------------------------------------------------------------------------

def test_growth_no_data_returns_neutral():
    assert score_growth(_ticker_data()) == pytest.approx(50.0)


def test_growth_high_revenue():
    m = _metrics(revenue_growth=0.30, earnings_growth=0.30)
    result = score_growth(_ticker_data(financial_metrics=[m]))
    assert result > 90.0


def test_growth_negative():
    m = _metrics(revenue_growth=-0.30, earnings_growth=-0.30)
    result = score_growth(_ticker_data(financial_metrics=[m]))
    assert result < 20.0


def test_growth_always_in_range():
    for g in [-0.5, -0.1, 0, 0.1, 0.5, 1.0]:
        m = _metrics(revenue_growth=g)
        result = score_growth(_ticker_data(financial_metrics=[m]))
        assert 0.0 <= result <= 100.0


# ---------------------------------------------------------------------------
# score_insider
# ---------------------------------------------------------------------------

def test_insider_no_trades_returns_neutral():
    assert score_insider(_ticker_data()) == pytest.approx(50.0)


def test_insider_all_buys():
    trades = [
        {"transaction_shares": 1000.0},
        {"transaction_shares": 500.0},
    ]
    result = score_insider(_ticker_data(insider_trades=trades))
    assert result == pytest.approx(100.0)


def test_insider_all_sells():
    trades = [
        {"transaction_shares": -1000.0},
    ]
    result = score_insider(_ticker_data(insider_trades=trades))
    assert result == pytest.approx(0.0)


def test_insider_mixed():
    trades = [
        {"transaction_shares": 500.0},   # buy
        {"transaction_shares": -500.0},   # sell
    ]
    result = score_insider(_ticker_data(insider_trades=trades))
    assert result == pytest.approx(50.0)


def test_insider_type_field_buy():
    trades = [{"transaction_type": "Purchase", "transaction_shares": 100.0}]
    result = score_insider(_ticker_data(insider_trades=trades))
    assert result == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# score_technical
# ---------------------------------------------------------------------------

def test_technical_no_prices_returns_neutral():
    assert score_technical(_ticker_data()) == pytest.approx(50.0)


def test_technical_insufficient_prices_returns_neutral():
    tiny_df = pd.DataFrame({"Close": [100.0] * 10})
    assert score_technical(_ticker_data(prices_df=tiny_df)) == pytest.approx(50.0)


def test_technical_always_in_range():
    # Build a minimal OHLCV dataframe with 60 rows
    n = 60
    import numpy as np
    prices = 100 + np.cumsum(np.random.randn(n))
    df = pd.DataFrame({
        "Open": prices * 0.99,
        "High": prices * 1.01,
        "Low": prices * 0.98,
        "Close": prices,
        "Volume": [1_000_000] * n,
    })
    result = score_technical(_ticker_data(prices_df=df))
    assert 0.0 <= result <= 100.0


# ---------------------------------------------------------------------------
# score_jhunjhunwala (fallback path — no agent import needed)
# ---------------------------------------------------------------------------

def test_jhunjhunwala_no_data_returns_neutral():
    assert score_jhunjhunwala(_ticker_data()) == pytest.approx(50.0)


def test_jhunjhunwala_always_in_range():
    m = _metrics(
        return_on_equity=0.25,
        net_margin=0.20,
        revenue_growth=0.20,
        debt_to_equity=0.3,
        free_cash_flow=100_000_000,
    )
    result = score_jhunjhunwala(_ticker_data(financial_metrics=[m]))
    assert 0.0 <= result <= 100.0
