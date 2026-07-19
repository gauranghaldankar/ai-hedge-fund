"""
Six pure scoring functions for the deterministic screener.

Each function:
  - Accepts a ticker_data dict built by run_screener._fetch_ticker_data()
  - Returns a float in [0, 100]
  - Makes no network calls, no LLM calls, no side effects
  - Handles missing data gracefully (returns 50.0 as neutral)

Keys available in ticker_data:
  financial_metrics  : list[dict]  — from yf_api / api.get_financial_metrics()
  prices_df          : pd.DataFrame — OHLCV with columns Open/High/Low/Close/Volume
  insider_trades     : list[dict]
  ticker             : str
"""

from __future__ import annotations

import logging
import math
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

_NEUTRAL = 50.0
_MIN_METRICS = 1  # minimum records needed to score


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert to float, returning default on None/NaN/error."""
    try:
        v = float(value)
        return default if math.isnan(v) or math.isinf(v) else v
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# 1. Valuation score
# ---------------------------------------------------------------------------

def score_valuation(ticker_data: dict[str, Any]) -> float:
    """
    Blended: 60% DCF margin of safety (MoS) + 40% Graham Number MoS.
    MoS > 50% → 100.  MoS = 0% → 50.  Premium > 50% → 0.
    Linear interpolation between these anchors.

    AC-0102 (valuation sub-score)
    """
    metrics_list: list[dict] = ticker_data.get("financial_metrics", [])
    if not metrics_list:
        return _NEUTRAL

    m = metrics_list[0]

    # --- DCF margin of safety ---
    intrinsic_value = _safe_float(m.get("intrinsic_value") or m.get("dcf_value"), 0.0)
    price = _safe_float(m.get("price") or m.get("current_price"), 0.0)

    dcf_mos: float
    if intrinsic_value > 0 and price > 0:
        dcf_mos = (intrinsic_value - price) / intrinsic_value  # can be negative
    else:
        # Try computing a rough DCF from FCF if explicit value is missing
        fcf = _safe_float(m.get("free_cash_flow"), 0.0)
        market_cap = _safe_float(m.get("market_cap"), 0.0)
        if fcf > 0 and market_cap > 0:
            # Simplistic P/FCF: <15 = undervalued, >30 = overvalued
            pfcf = market_cap / fcf
            # Map: pfcf=7.5 → MoS=0.5, pfcf=15 → MoS=0, pfcf=30 → MoS=-0.5
            dcf_mos = (15.0 - pfcf) / 30.0
        else:
            dcf_mos = 0.0  # neutral

    # --- Graham Number margin of safety ---
    eps = _safe_float(m.get("earnings_per_share"), 0.0)
    book_value_per_share = _safe_float(m.get("book_value_per_share"), 0.0)
    graham_mos: float
    if eps > 0 and book_value_per_share > 0 and price > 0:
        graham_number = math.sqrt(22.5 * eps * book_value_per_share)
        graham_mos = (graham_number - price) / graham_number
    else:
        # Fallback: use P/E and P/B ratios if available
        pe = _safe_float(m.get("price_to_earnings_ratio") or m.get("pe_ratio"), 0.0)
        pb = _safe_float(m.get("price_to_book_ratio") or m.get("pb_ratio"), 0.0)
        if pe > 0 and pb > 0:
            # Lower P/E and P/B = more margin of safety
            # Graham target: P/E < 15, P/B < 1.5
            pe_mos = (15.0 - pe) / 30.0
            pb_mos = (1.5 - pb) / 3.0
            graham_mos = (pe_mos + pb_mos) / 2.0
        else:
            graham_mos = 0.0

    blended_mos = 0.60 * dcf_mos + 0.40 * graham_mos

    # Map MoS to [0, 100]:  MoS=0.5 → 100, MoS=0 → 50, MoS=-0.5 → 0
    score = 50.0 + blended_mos * 100.0
    return _clamp(score)


# ---------------------------------------------------------------------------
# 2. Fundamentals quality score
# ---------------------------------------------------------------------------

def score_fundamentals(ticker_data: dict[str, Any]) -> float:
    """
    Profitability + balance sheet health + margin quality.
    Extracted from fundamentals_analyst scoring logic.

    Sub-components (each 0–1, weighted equally):
      - ROE > 15% → 1, 0–15% → proportional, <0 → 0
      - Net margin > 15% → 1, else proportional
      - Debt/Equity < 0.5 → 1, > 2.0 → 0, linear between
      - Current ratio > 2 → 1, < 1 → 0, linear between
      - Operating margin > 20% → 1, else proportional

    AC-0102 (fundamentals sub-score)
    """
    metrics_list: list[dict] = ticker_data.get("financial_metrics", [])
    if not metrics_list:
        return _NEUTRAL

    m = metrics_list[0]

    roe = _safe_float(m.get("return_on_equity"), -999)
    net_margin = _safe_float(m.get("net_margin"), -999)
    de_ratio = _safe_float(m.get("debt_to_equity"), -999)
    current_ratio = _safe_float(m.get("current_ratio"), -999)
    op_margin = _safe_float(m.get("operating_margin"), -999)

    scores: list[float] = []

    if roe != -999:
        scores.append(_clamp(roe / 0.15))  # 15% target
    if net_margin != -999:
        scores.append(_clamp(net_margin / 0.15))
    if de_ratio != -999 and de_ratio >= 0:
        # Lower is better: D/E=0 → 1, D/E=2 → 0
        scores.append(_clamp(1.0 - de_ratio / 2.0))
    if current_ratio != -999 and current_ratio >= 0:
        # Higher is better: CR=2 → 1, CR=1 → 0.5, CR<1 → <0.5
        scores.append(_clamp(current_ratio / 2.0))
    if op_margin != -999:
        scores.append(_clamp(op_margin / 0.20))  # 20% target

    if not scores:
        return _NEUTRAL

    return _clamp(sum(scores) / len(scores) * 100.0)


# ---------------------------------------------------------------------------
# 3. Jhunjhunwala score
# ---------------------------------------------------------------------------

def score_jhunjhunwala(ticker_data: dict[str, Any]) -> float:
    """
    Calls analyze_rakesh_jhunjhunwala_style() directly.
    total_score 0–24 → 0–100.

    AC-0102 (jhunjhunwala sub-score)
    """
    try:
        from src.agents.rakesh_jhunjhunwala import analyze_rakesh_jhunjhunwala_style  # type: ignore
    except ImportError:
        logger.warning("rakesh_jhunjhunwala module not importable; returning neutral")
        return _NEUTRAL

    metrics_list: list[dict] = ticker_data.get("financial_metrics", [])
    if not metrics_list:
        return _NEUTRAL

    m = metrics_list[0]

    # Build the data structure the function expects
    # It expects financial_metrics as a list with the first element having the data
    try:
        result = analyze_rakesh_jhunjhunwala_style(
            ticker=ticker_data.get("ticker", ""),
            financial_metrics=[m],
            market_cap=_safe_float(m.get("market_cap"), 0.0),
        )
        total = _safe_float(result.get("total_score", 0), 0.0)
        # Max score is 24 points
        return _clamp(total / 24.0 * 100.0)
    except Exception as exc:
        logger.debug("Jhunjhunwala scoring failed for %s: %s", ticker_data.get("ticker"), exc)
        # Fall back to manual calculation using available metrics
        return _score_jhunjhunwala_manual(m)


def _score_jhunjhunwala_manual(m: dict[str, Any]) -> float:
    """Manual approximation of Jhunjhunwala scoring when direct call fails."""
    score = 0
    max_score = 0

    # Profitability (0–8)
    roe = _safe_float(m.get("return_on_equity"), -1)
    if roe >= 0:
        max_score += 3
        if roe >= 0.25:
            score += 3
        elif roe >= 0.15:
            score += 2
        elif roe >= 0.10:
            score += 1

    net_margin = _safe_float(m.get("net_margin"), -1)
    if net_margin >= 0:
        max_score += 3
        if net_margin >= 0.20:
            score += 3
        elif net_margin >= 0.12:
            score += 2
        elif net_margin >= 0.06:
            score += 1

    # Growth (0–7)
    rev_growth = _safe_float(m.get("revenue_growth"), -999)
    if rev_growth != -999:
        max_score += 3
        if rev_growth >= 0.20:
            score += 3
        elif rev_growth >= 0.12:
            score += 2
        elif rev_growth >= 0.05:
            score += 1

    # Balance sheet (0–4)
    de = _safe_float(m.get("debt_to_equity"), -1)
    if de >= 0:
        max_score += 2
        if de < 0.5:
            score += 2
        elif de < 1.0:
            score += 1

    # FCF (0–3)
    fcf = _safe_float(m.get("free_cash_flow"), 0)
    if fcf > 0:
        max_score += 2
        score += 2
    elif fcf == 0:
        pass
    else:
        max_score += 2

    if max_score == 0:
        return _NEUTRAL
    return _clamp(score / max_score * 100.0)


# ---------------------------------------------------------------------------
# 4. Growth consistency score
# ---------------------------------------------------------------------------

def score_growth(ticker_data: dict[str, Any]) -> float:
    """
    Revenue CAGR (2yr) + Earnings CAGR (2yr) + quarter-on-quarter consistency.
    Negative CAGR → < 50. CAGR > 30% → capped at 100.

    AC-0102 (growth sub-score)
    """
    metrics_list: list[dict] = ticker_data.get("financial_metrics", [])
    if len(metrics_list) < 1:
        return _NEUTRAL

    m = metrics_list[0]

    components: list[float] = []

    # Revenue growth
    rev_growth = _safe_float(m.get("revenue_growth"), -999)
    if rev_growth != -999:
        # 0% → 50, 30% → 100, -30% → 0
        components.append(_clamp(50.0 + rev_growth / 0.30 * 50.0))

    # Earnings growth
    earn_growth = _safe_float(m.get("earnings_growth") or m.get("net_income_growth"), -999)
    if earn_growth != -999:
        components.append(_clamp(50.0 + earn_growth / 0.30 * 50.0))

    # EPS trend if growth metrics not available
    eps_growth = _safe_float(m.get("eps_growth") or m.get("earnings_per_share_growth"), -999)
    if eps_growth != -999 and earn_growth == -999:
        components.append(_clamp(50.0 + eps_growth / 0.30 * 50.0))

    # Consistency bonus: positive FCF growth
    fcf = _safe_float(m.get("free_cash_flow"), 0)
    if fcf > 0:
        components.append(65.0)  # mild bonus for positive FCF
    elif fcf < 0:
        components.append(35.0)  # mild penalty

    if not components:
        return _NEUTRAL

    return _clamp(sum(components) / len(components))


# ---------------------------------------------------------------------------
# 5. Insider sentiment score
# ---------------------------------------------------------------------------

def score_insider(ticker_data: dict[str, Any]) -> float:
    """
    insider_buys / (insider_buys + insider_sells).
    No trades → 50 (neutral). All buys → 100. All sells → 0.

    Buy/sell detected from:
      - transaction_type / type field (if present)
      - transaction_shares sign: positive = buy, negative = sell

    AC-0102 (insider sub-score)
    """
    trades: list[dict] = ticker_data.get("insider_trades", [])

    if not trades:
        return _NEUTRAL

    buys: float = 0.0
    sells: float = 0.0
    for trade in trades:
        # Try explicit type field first
        tx_type = str(trade.get("transaction_type") or trade.get("type") or "").lower()
        shares_raw = trade.get("transaction_shares") or trade.get("shares") or 0
        shares = _safe_float(shares_raw, 0.0)

        if "buy" in tx_type or "purchase" in tx_type or "acqui" in tx_type:
            buys += abs(shares)
        elif "sell" in tx_type or "sale" in tx_type or "dispos" in tx_type:
            sells += abs(shares)
        else:
            # Infer from sign of transaction_shares (positive = buy, negative = sell)
            if shares > 0:
                buys += shares
            elif shares < 0:
                sells += abs(shares)

    total = buys + sells
    if total == 0:
        return _NEUTRAL

    return _clamp(buys / total * 100.0)


# ---------------------------------------------------------------------------
# 6. Technical score
# ---------------------------------------------------------------------------

def score_technical(ticker_data: dict[str, Any]) -> float:
    """
    Uses the technicals.py standalone functions (no LLM).
    Weighted combination: trend 0.25, mean_reversion 0.20, momentum 0.25,
    volatility 0.15, stat_arb 0.15.

    Mapping: bullish + confidence C → 50 + C×50
             bearish + confidence C → 50 - C×50
             neutral              → 50.0

    AC-0102 (technical sub-score, part of weight profiles)
    """
    prices_df: pd.DataFrame | None = ticker_data.get("prices_df")

    if prices_df is None or prices_df.empty or len(prices_df) < 20:
        return _NEUTRAL

    try:
        from src.agents.technicals import (  # type: ignore
            calculate_trend_signals,
            calculate_mean_reversion_signals,
            calculate_momentum_signals,
            calculate_volatility_signals,
            calculate_stat_arb_signals,
            weighted_signal_combination,
        )
    except ImportError:
        logger.warning("technicals module not importable; returning neutral")
        return _NEUTRAL

    try:
        signals = {
            "trend": calculate_trend_signals(prices_df),
            "mean_reversion": calculate_mean_reversion_signals(prices_df),
            "momentum": calculate_momentum_signals(prices_df),
            "volatility": calculate_volatility_signals(prices_df),
            "stat_arb": calculate_stat_arb_signals(prices_df),
        }
        weights = {
            "trend": 0.25,
            "mean_reversion": 0.20,
            "momentum": 0.25,
            "volatility": 0.15,
            "stat_arb": 0.15,
        }
        combined = weighted_signal_combination(signals, weights)
        signal = str(combined.get("signal", "neutral")).lower()
        confidence = _safe_float(combined.get("confidence", 0.0), 0.0)

        if "bullish" in signal:
            return _clamp(50.0 + confidence * 50.0)
        elif "bearish" in signal:
            return _clamp(50.0 - confidence * 50.0)
        else:
            return _NEUTRAL
    except Exception as exc:
        logger.debug("Technical scoring failed: %s", exc)
        return _NEUTRAL
