"""
P&L Summary endpoint.

GET /pnl/summary
  Returns all completed flow runs across all flows, with:
  - Flow name, run date, tickers analyzed
  - Per-ticker: action, confidence, price at run time, current price, % change
  - Analyst consensus signal per ticker
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.backend.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pnl", tags=["pnl"])


def _fetch_current_price(ticker: str) -> float | None:
    """Get latest price: Kite LTP for .NS tickers, then yfinance for everything else."""
    try:
        from src.tools.api import get_current_price_ltp
        import yfinance as yf

        # Try live LTP first for NSE tickers
        ltp = get_current_price_ltp(ticker)
        if ltp:
            return ltp

        # yfinance fallback — works for US tickers (AAPL, NVDA…) and .NS when Kite LTP fails
        hist = yf.Ticker(ticker).history(period="5d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as exc:
        logger.debug("Price fetch failed for %s: %s", ticker, exc)
    return None


def _analyst_consensus(analyst_signals: dict, ticker: str) -> str:
    """Derive overall consensus (bullish/bearish/neutral) from analyst signals for a ticker."""
    scores = {"bullish": 0, "bearish": 0, "neutral": 0}
    count = 0
    for _agent, agent_signals in analyst_signals.items():
        if not isinstance(agent_signals, dict):
            continue
        sig = agent_signals.get(ticker)
        if not sig or not isinstance(sig, dict):
            continue
        signal = sig.get("signal", "neutral").lower()
        confidence = sig.get("confidence", 50)
        if signal in scores:
            scores[signal] += confidence
            count += 1
    if not count:
        return "neutral"
    return max(scores, key=lambda k: scores[k])


@router.get("/summary")
def get_pnl_summary(db: Session = Depends(get_db)) -> dict[str, Any]:
    """
    Aggregate all completed runs across all flows.
    Returns per-run, per-ticker: price_then, price_now, pct_change, action, consensus.
    """
    rows = db.execute(
        text("""
            SELECT
                r.id          AS run_id,
                r.flow_id,
                f.name        AS flow_name,
                r.created_at,
                r.results
            FROM hedge_fund_flow_runs r
            JOIN hedge_fund_flows f ON f.id = r.flow_id
            WHERE r.status = 'COMPLETE' AND r.results IS NOT NULL
            ORDER BY r.created_at DESC
            LIMIT 100
        """)
    ).fetchall()

    # Collect all unique tickers to batch-fetch prices once
    all_tickers: set[str] = set()
    parsed: list[dict] = []
    for row in rows:
        import json
        try:
            results = json.loads(row.results) if isinstance(row.results, str) else row.results
        except Exception:
            continue
        decisions = results.get("decisions") or {}
        prices_then = results.get("current_prices") or {}
        analyst_signals = results.get("analyst_signals") or {}
        if not decisions:
            continue
        parsed.append({
            "run_id": row.run_id,
            "flow_id": row.flow_id,
            "flow_name": row.flow_name,
            "created_at": row.created_at.isoformat() if hasattr(row.created_at, "isoformat") else str(row.created_at),
            "decisions": decisions,
            "prices_then": prices_then,
            "analyst_signals": analyst_signals,
        })
        all_tickers.update(decisions.keys())

    # Fetch current prices for all tickers
    prices_now: dict[str, float | None] = {}
    for ticker in all_tickers:
        prices_now[ticker] = _fetch_current_price(ticker)

    # Build response
    runs_out = []
    for p in parsed:
        tickers_out = []
        for ticker, decision in p["decisions"].items():
            price_then = p["prices_then"].get(ticker) or 0.0
            price_now = prices_now.get(ticker)
            pct_change = None
            if price_then and price_then > 0 and price_now and price_now > 0:
                pct_change = round((price_now - price_then) / price_then * 100, 2)
            consensus = _analyst_consensus(p["analyst_signals"], ticker)
            tickers_out.append({
                "ticker": ticker,
                "action": decision.get("action", "hold"),
                "confidence": decision.get("confidence", 0),
                "price_then": round(price_then, 2) if price_then else None,
                "price_now": round(price_now, 2) if price_now else None,
                "pct_change": pct_change,
                "consensus": consensus,
            })
        runs_out.append({
            "run_id": p["run_id"],
            "flow_id": p["flow_id"],
            "flow_name": p["flow_name"],
            "created_at": p["created_at"],
            "tickers": tickers_out,
        })

    return {"runs": runs_out, "total": len(runs_out)}
