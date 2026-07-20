"""
Screener orchestrator — scores a list of tickers deterministically (zero LLM calls).

Usage:
    from src.screener.run_screener import run_screener, ScreenerResult

    for result in run_screener(tickers, on_progress=callback):
        ...

Concurrency: ThreadPoolExecutor(max_workers=10) for data fetching.
Price/OHLCV data: Kite Connect (primary, AC-0118) → yfinance (fallback, AC-0119).
Fundamentals and insider data: yfinance only (Kite has no fundamental API).
Each ticker is scored independently; errors are captured per-ticker.

AC-0101, AC-0116, AC-0117, AC-0118, AC-0119, AC-0120
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable

import pandas as pd

from src.screener.scorer import (
    score_fundamentals,
    score_growth,
    score_insider,
    score_jhunjhunwala,
    score_technical,
    score_valuation,
)
from src.screener.composite import WeightProfile, MEDIUM_LONG, compute_composite

logger = logging.getLogger(__name__)

MAX_WORKERS = 10


@dataclass
class ScreenerResult:
    ticker: str
    company_name: str = ""
    industry: str = ""
    rank: int = 0
    composite_score: float = 0.0
    valuation_score: float = 0.0
    fundamentals_score: float = 0.0
    jhunjhunwala_score: float = 0.0
    growth_score: float = 0.0
    insider_score: float = 0.0
    technical_score: float = 0.0
    is_shortlisted: bool = False
    key_metrics: dict[str, Any] = field(default_factory=dict)
    scored_at: datetime = field(default_factory=datetime.utcnow)
    error: str | None = None


def _date_minus_days(date_str: str, days: int) -> str:
    d = datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=days)
    return d.strftime("%Y-%m-%d")


def _fetch_ticker_data(
    ticker: str,
    end_date: str,
    kite_token_lookup: dict[str, int] | None = None,
    kite_client=None,
) -> dict[str, Any]:
    """
    Fetch all data needed for scoring a single ticker.

    Price/OHLCV: Kite Connect first (AC-0118); yfinance fallback (AC-0119).
    Fundamentals + insider: yfinance only (Kite has no fundamental API).

    Returns a dict with keys: ticker, financial_metrics (list[dict]),
    prices_df (pd.DataFrame|None), insider_trades (list[dict]).
    Never raises — returns partial data on error.
    """
    data: dict[str, Any] = {
        "ticker": ticker,
        "financial_metrics": [],
        "prices_df": None,
        "insider_trades": [],
    }
    start_date = _date_minus_days(end_date, 365)

    # --- Financial metrics (yfinance only — Kite has no fundamentals API) ---
    try:
        from src.tools.yf_api import get_financial_metrics

        metrics = get_financial_metrics(ticker, end_date=end_date, period="ttm", limit=1)
        if metrics:
            data["financial_metrics"] = [m.model_dump() for m in metrics]
    except Exception as exc:
        logger.debug("get_financial_metrics failed for %s: %s", ticker, exc)

    # Augment with free_cash_flow from search_line_items
    if data["financial_metrics"]:
        try:
            from src.tools.yf_api import search_line_items

            line_items = search_line_items(ticker, ["free_cash_flow"], end_date=end_date, period="ttm", limit=1)
            if line_items:
                fcf = getattr(line_items[0], "free_cash_flow", None)
                if fcf is not None:
                    data["financial_metrics"][0]["free_cash_flow"] = fcf
        except Exception as exc:
            logger.debug("search_line_items(free_cash_flow) failed for %s: %s", ticker, exc)

    # --- Price data (for technical scoring) ---
    # Try Kite first; fall back to yfinance if Kite is not configured or fails (AC-0118, AC-0119)
    kite_succeeded = False
    if kite_token_lookup is not None and kite_client is not None:
        try:
            from src.tools.kite_api import get_price_data_kite

            symbol = ticker.removesuffix(".NS").removesuffix(".BO")
            prices_df = get_price_data_kite(
                symbol, start_date, end_date,
                token_lookup=kite_token_lookup, kite=kite_client,
            )
            if prices_df is not None and not prices_df.empty:
                data["prices_df"] = prices_df
                kite_succeeded = True
        except Exception as exc:
            logger.debug("Kite price fetch failed for %s: %s", ticker, exc)

    if not kite_succeeded:
        # yfinance primary fallback
        try:
            from src.tools.yf_api import get_price_data

            prices_df = get_price_data(ticker, start_date=start_date, end_date=end_date)
            if prices_df is not None and not prices_df.empty:
                data["prices_df"] = prices_df
        except Exception as exc:
            logger.debug("get_price_data failed for %s: %s", ticker, exc)

        # yfinance secondary fallback: get_prices + prices_to_df
        if data["prices_df"] is None or (isinstance(data["prices_df"], pd.DataFrame) and data["prices_df"].empty):
            try:
                from src.tools.yf_api import get_prices, prices_to_df

                prices = get_prices(ticker, start_date=start_date, end_date=end_date)
                if prices:
                    data["prices_df"] = prices_to_df(prices)
            except Exception as exc:
                logger.debug("get_prices fallback failed for %s: %s", ticker, exc)

    # --- Insider trades (yfinance only) ---
    try:
        from src.tools.yf_api import get_insider_trades

        trades = get_insider_trades(ticker, end_date=end_date, limit=50)
        if trades:
            data["insider_trades"] = [t.model_dump() for t in trades]
    except Exception as exc:
        logger.debug("get_insider_trades failed for %s: %s", ticker, exc)

    return data


def _extract_key_metrics(ticker_data: dict[str, Any]) -> dict[str, Any]:
    """Extract the key metrics card fields for the UI drawer."""
    m = (ticker_data.get("financial_metrics") or [{}])[0]
    return {
        "pe_ratio": m.get("price_to_earnings_ratio"),
        "pb_ratio": m.get("price_to_book_ratio"),
        "roe": m.get("return_on_equity"),
        "de_ratio": m.get("debt_to_equity"),
        "free_cash_flow": m.get("free_cash_flow"),
        "revenue_growth": m.get("revenue_growth"),
        "market_cap": m.get("market_cap"),
        "net_margin": m.get("net_margin"),
        "operating_margin": m.get("operating_margin"),
    }


def _score_ticker(
    ticker: str,
    company_name: str,
    industry: str,
    profile: WeightProfile,
    end_date: str,
    kite_token_lookup: dict[str, int] | None = None,
    kite_client=None,
) -> ScreenerResult:
    """Score a single ticker. Captures all errors per-ticker; run continues (AC-0117)."""
    result = ScreenerResult(ticker=ticker, company_name=company_name, industry=industry)

    try:
        ticker_data = _fetch_ticker_data(ticker, end_date, kite_token_lookup, kite_client)

        result.valuation_score = score_valuation(ticker_data)
        result.fundamentals_score = score_fundamentals(ticker_data)
        result.jhunjhunwala_score = score_jhunjhunwala(ticker_data)
        result.growth_score = score_growth(ticker_data)
        result.insider_score = score_insider(ticker_data)
        result.technical_score = score_technical(ticker_data)

        result.composite_score = compute_composite(
            valuation=result.valuation_score,
            fundamentals=result.fundamentals_score,
            jhunjhunwala=result.jhunjhunwala_score,
            growth=result.growth_score,
            insider=result.insider_score,
            technical=result.technical_score,
            profile=profile,
        )
        result.key_metrics = _extract_key_metrics(ticker_data)
        result.scored_at = datetime.utcnow()

    except Exception as exc:
        logger.warning("Scoring failed for %s: %s", ticker, exc, exc_info=True)
        result.error = str(exc)

    return result


def run_screener(
    tickers: list[str],
    company_info: dict[str, tuple[str, str]] | None = None,
    profile: WeightProfile | None = None,
    end_date: str | None = None,
    on_progress: Callable[[int, int, ScreenerResult], None] | None = None,
) -> list[ScreenerResult]:
    """
    Score a list of tickers with ThreadPoolExecutor(max_workers=10).

    Args:
        tickers:      e.g. ["RELIANCE.NS", "TCS.NS"]
        company_info: optional {ticker: (company_name, industry)}
        profile:      WeightProfile — defaults to MEDIUM_LONG
        end_date:     YYYY-MM-DD; None = today (for historical backfill)
        on_progress:  callback(done, total, result) fired after each ticker

    Returns:
        list[ScreenerResult] sorted composite_score desc, with rank assigned.

    AC-0101 (zero LLM), AC-0116 (<10 min for 500), AC-0117 (errors captured)
    """
    info = company_info or {}
    p = profile or MEDIUM_LONG
    ed = end_date or date.today().strftime("%Y-%m-%d")
    total = len(tickers)
    results: list[ScreenerResult] = []
    done_count = 0

    # Build Kite context once per run; shared (read-only) across all worker threads (AC-0120)
    kite_token_lookup: dict[str, int] = {}
    kite_client = None
    try:
        from src.config.kite_config import get_kite_config
        from src.tools.kite_api import build_token_lookup
        from kiteconnect import KiteConnect  # noqa: PLC0415

        cfg = get_kite_config()
        if cfg["api_key"] and cfg["access_token"]:
            kite_client = KiteConnect(api_key=cfg["api_key"])
            kite_client.set_access_token(cfg["access_token"])
            kite_token_lookup = build_token_lookup(kite_client)
            logger.info("Kite initialized: %d instruments in token lookup", len(kite_token_lookup))
        else:
            logger.info("Kite credentials not configured; price data will use yfinance")
    except Exception as exc:
        logger.warning("Kite initialization failed; price data will use yfinance: %s", exc)

    start_time = time.time()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_ticker = {
            executor.submit(
                _score_ticker,
                ticker,
                info.get(ticker, ("", ""))[0],
                info.get(ticker, ("", ""))[1],
                p,
                ed,
                kite_token_lookup if kite_token_lookup else None,
                kite_client,
            ): ticker
            for ticker in tickers
        }

        for future in as_completed(future_to_ticker):
            result = future.result()
            results.append(result)
            done_count += 1
            if on_progress:
                try:
                    on_progress(done_count, total, result)
                except Exception:
                    pass

    # Rank by composite score; errors go to the bottom
    results.sort(key=lambda r: (r.error is not None, -r.composite_score))
    for rank, r in enumerate(results, start=1):
        r.rank = rank

    elapsed = time.time() - start_time
    logger.info(
        "Screener complete: %d tickers in %.1fs (%.1f tickers/s)",
        total,
        elapsed,
        total / elapsed if elapsed > 0 else 0,
    )
    return results
