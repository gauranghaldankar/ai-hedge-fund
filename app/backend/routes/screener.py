"""
Screener API routes.

Endpoints:
  GET  /screener/runs                        List past runs
  POST /screener/run                         Trigger run — SSE stream
  GET  /screener/runs/{id}/results           Full ranked table for one run
  GET  /screener/runs/{id}/results/{ticker}  Detail for one stock in a run
  POST /screener/ticker                      On-demand score for any ticker
  GET  /screener/constituents                Current Nifty 500 list
  POST /screener/constituents/refresh        Trigger monthly constituent refresh
"""

from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.backend.database import get_db
from app.backend.database.models import NiftyConstituent, ScreenerRun, ScreenerResult as ScreenerResultDB

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/screener")

_executor = ThreadPoolExecutor(max_workers=2)  # screener runs are heavy; limit to 2 concurrent


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------

class RunRequest(BaseModel):
    threshold_mode: str = "top25"    # "top25" | "top5pct" | "score60"
    weight_profile: str = "medium_long"  # "medium_long" | "short_term" | "custom"
    custom_weights: dict[str, float] | None = None
    run_date: str | None = None       # YYYY-MM-DD; None = today


class CustomTickerRequest(BaseModel):
    ticker: str
    weight_profile: str = "medium_long"
    custom_weights: dict[str, float] | None = None


class BackfillRequest(BaseModel):
    force: bool = False  # if True, re-run dates that already have a COMPLETE run


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_profile(weight_profile: str, custom_weights: dict[str, float] | None):
    from src.screener.composite import PROFILES, WeightProfile, MEDIUM_LONG

    if weight_profile == "custom" and custom_weights:
        w = custom_weights
        total = sum(w.values())
        try:
            return WeightProfile(
                name="custom",
                valuation=w.get("valuation", 0) / total,
                fundamentals=w.get("fundamentals", 0) / total,
                jhunjhunwala=w.get("jhunjhunwala", 0) / total,
                growth=w.get("growth", 0) / total,
                insider=w.get("insider", 0) / total,
                technical=w.get("technical", 0) / total,
            )
        except Exception:
            return MEDIUM_LONG

    return PROFILES.get(weight_profile, MEDIUM_LONG)


def _result_to_dict(r: ScreenerResultDB) -> dict[str, Any]:
    return {
        "id": r.id,
        "run_id": r.run_id,
        "ticker": r.ticker,
        "company_name": r.company_name,
        "industry": r.industry,
        "rank": r.rank,
        "composite_score": r.composite_score,
        "valuation_score": r.valuation_score,
        "fundamentals_score": r.fundamentals_score,
        "jhunjhunwala_score": r.jhunjhunwala_score,
        "growth_score": r.growth_score,
        "insider_score": r.insider_score,
        "technical_score": r.technical_score,
        "is_shortlisted": r.is_shortlisted,
        "key_metrics": r.key_metrics,
        "scored_at": r.scored_at.isoformat() if r.scored_at else None,
        "error": r.error,
    }


# ---------------------------------------------------------------------------
# GET /screener/runs — list past runs
# ---------------------------------------------------------------------------

@router.get("/runs")
def list_runs(limit: int = 30, db: Session = Depends(get_db)):
    """List last N screener runs. AC-0113"""
    runs = (
        db.query(ScreenerRun)
        .order_by(ScreenerRun.run_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "run_at": r.run_at.isoformat() if r.run_at else None,
            "universe": r.universe,
            "threshold_mode": r.threshold_mode,
            "weight_profile": r.weight_profile,
            "stocks_screened": r.stocks_screened,
            "shortlisted_count": r.shortlisted_count,
            "duration_seconds": r.duration_seconds,
            "status": r.status,
            "source": r.source,
            "run_date": r.run_date,
        }
        for r in runs
    ]


# ---------------------------------------------------------------------------
# POST /screener/run — trigger a run with SSE progress stream
# ---------------------------------------------------------------------------

@router.post("/run")
async def trigger_run(req: RunRequest, db: Session = Depends(get_db)):
    """
    Trigger a full Nifty 500 screener run.
    Streams SSE events: progress, complete, error.
    AC-0105, AC-0106
    """
    # Create run record
    run_record = ScreenerRun(
        status="IN_PROGRESS",
        threshold_mode=req.threshold_mode,
        weight_profile=req.weight_profile,
        source="manual",
        run_date=req.run_date,
    )
    db.add(run_record)
    db.commit()
    db.refresh(run_record)
    run_id = run_record.id

    async def event_generator():
        from src.screener.constituents import get_nifty500_constituents
        from src.screener.run_screener import run_screener, ScreenerResult
        from src.screener.composite import apply_threshold

        constituents = get_nifty500_constituents()
        tickers = [c["ticker"] for c in constituents]
        company_info = {
            c["ticker"]: (c["company_name"], c["industry"])
            for c in constituents
        }
        profile = _make_profile(req.weight_profile, req.custom_weights)
        total = len(tickers)

        progress_queue: asyncio.Queue = asyncio.Queue()
        start_time = asyncio.get_event_loop().time()

        def on_progress(done: int, total_count: int, result: ScreenerResult):
            event = {
                "type": "progress",
                "ticker": result.ticker,
                "done": done,
                "total": total_count,
                "score": round(result.composite_score, 2),
                "error": result.error,
            }
            progress_queue.put_nowait(event)

        # Run screener in thread pool (CPU + network bound)
        loop = asyncio.get_event_loop()
        run_future = loop.run_in_executor(
            _executor,
            lambda: run_screener(
                tickers=tickers,
                company_info=company_info,
                profile=profile,
                end_date=req.run_date,
                on_progress=on_progress,
            ),
        )

        done_count = 0
        results_list: list[ScreenerResult] | None = None

        try:
            while True:
                if results_list is not None and progress_queue.empty():
                    break
                try:
                    event = await asyncio.wait_for(progress_queue.get(), timeout=0.5)
                    done_count = event["done"]
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    if run_future.done():
                        results_list = run_future.result()
                        # Drain remaining queue
                        while not progress_queue.empty():
                            event = progress_queue.get_nowait()
                            yield f"data: {json.dumps(event)}\n\n"
                        break

            if results_list is None:
                results_list = await run_future

            # Apply threshold shortlisting
            result_dicts = [
                {
                    "ticker": r.ticker,
                    "composite_score": r.composite_score,
                    "is_shortlisted": False,
                }
                for r in results_list
            ]
            apply_threshold(result_dicts, req.threshold_mode)
            shortlisted_map = {d["ticker"]: d["is_shortlisted"] for d in result_dicts}

            # Persist results to DB
            duration = asyncio.get_event_loop().time() - start_time
            shortlisted_count = sum(1 for v in shortlisted_map.values() if v)

            for r in results_list:
                db_result = ScreenerResultDB(
                    run_id=run_id,
                    ticker=r.ticker,
                    company_name=r.company_name,
                    industry=r.industry,
                    rank=r.rank,
                    composite_score=r.composite_score,
                    valuation_score=r.valuation_score,
                    fundamentals_score=r.fundamentals_score,
                    jhunjhunwala_score=r.jhunjhunwala_score,
                    growth_score=r.growth_score,
                    insider_score=r.insider_score,
                    technical_score=r.technical_score,
                    is_shortlisted=shortlisted_map.get(r.ticker, False),
                    key_metrics=r.key_metrics,
                    scored_at=r.scored_at,
                    error=r.error,
                )
                db.add(db_result)

            db.query(ScreenerRun).filter(ScreenerRun.id == run_id).update(
                {
                    "status": "COMPLETE",
                    "stocks_screened": len(results_list),
                    "shortlisted_count": shortlisted_count,
                    "duration_seconds": round(duration, 1),
                }
            )
            db.commit()

            complete_event = {
                "type": "complete",
                "run_id": run_id,
                "shortlisted": shortlisted_count,
                "duration_seconds": round(duration, 1),
                "stocks_screened": len(results_list),
            }
            yield f"data: {json.dumps(complete_event)}\n\n"

        except Exception as exc:
            logger.error("Screener run %d failed: %s", run_id, exc, exc_info=True)
            db.query(ScreenerRun).filter(ScreenerRun.id == run_id).update(
                {"status": "ERROR", "error_message": str(exc)}
            )
            db.commit()
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# POST /screener/backfill — run last 7 trading days sequentially
# ---------------------------------------------------------------------------

@router.post("/backfill")
async def trigger_backfill(req: BackfillRequest, db: Session = Depends(get_db)):
    """
    Backfill the last 7 NSE trading days.
    Skips dates that already have a COMPLETE run (unless force=True).
    Streams SSE: backfill_start → [backfill_day_start → progress* → backfill_day_complete]* → backfill_complete
    AC-0115
    """
    async def event_generator():
        from src.screener.holidays import last_n_trading_days
        from src.screener.constituents import get_nifty500_constituents
        from src.screener.run_screener import run_screener, ScreenerResult
        from src.screener.composite import apply_threshold, MEDIUM_LONG

        # Oldest → newest so history builds chronologically
        trading_days = list(reversed(last_n_trading_days(7)))
        date_strs = [d.strftime("%Y-%m-%d") for d in trading_days]

        # Skip dates that already have a completed run (unless force)
        if not req.force:
            existing = {
                r.run_date
                for r in db.query(ScreenerRun)
                .filter(ScreenerRun.status == "COMPLETE", ScreenerRun.run_date.in_(date_strs))
                .all()
                if r.run_date
            }
            dates_to_run = [d for d in date_strs if d not in existing]
        else:
            dates_to_run = date_strs

        skipped = len(date_strs) - len(dates_to_run)
        yield f"data: {json.dumps({'type': 'backfill_start', 'dates': dates_to_run, 'total_days': len(dates_to_run), 'skipped': skipped})}\n\n"

        if not dates_to_run:
            yield f"data: {json.dumps({'type': 'backfill_complete', 'days_run': 0, 'skipped': skipped})}\n\n"
            return

        # Fetch constituents once; reuse across days
        constituents = get_nifty500_constituents()
        tickers = [c["ticker"] for c in constituents]
        company_info = {c["ticker"]: (c["company_name"], c["industry"]) for c in constituents}

        for day_idx, date_str in enumerate(dates_to_run, start=1):
            yield f"data: {json.dumps({'type': 'backfill_day_start', 'date': date_str, 'day': day_idx, 'total_days': len(dates_to_run)})}\n\n"

            run_record = ScreenerRun(
                status="IN_PROGRESS",
                threshold_mode="top25",
                weight_profile="medium_long",
                source="backfill",
                run_date=date_str,
            )
            db.add(run_record)
            db.commit()
            db.refresh(run_record)
            run_id = run_record.id

            progress_queue: asyncio.Queue = asyncio.Queue()
            start_time = asyncio.get_event_loop().time()

            def on_progress(done: int, total_count: int, result: ScreenerResult, _q=progress_queue):
                _q.put_nowait({
                    "type": "progress",
                    "ticker": result.ticker,
                    "done": done,
                    "total": total_count,
                    "score": round(result.composite_score, 2),
                    "error": result.error,
                })

            loop = asyncio.get_event_loop()
            run_future = loop.run_in_executor(
                _executor,
                lambda ds=date_str: run_screener(
                    tickers=tickers,
                    company_info=company_info,
                    profile=MEDIUM_LONG,
                    end_date=ds,
                    on_progress=on_progress,
                ),
            )

            try:
                results_list = None
                while True:
                    if results_list is not None and progress_queue.empty():
                        break
                    try:
                        event = await asyncio.wait_for(progress_queue.get(), timeout=0.5)
                        yield f"data: {json.dumps(event)}\n\n"
                    except asyncio.TimeoutError:
                        if run_future.done():
                            results_list = run_future.result()
                            while not progress_queue.empty():
                                event = progress_queue.get_nowait()
                                yield f"data: {json.dumps(event)}\n\n"
                            break

                if results_list is None:
                    results_list = await run_future

                result_dicts = [
                    {"ticker": r.ticker, "composite_score": r.composite_score, "is_shortlisted": False}
                    for r in results_list
                ]
                apply_threshold(result_dicts, "top25")
                shortlisted_map = {d["ticker"]: d["is_shortlisted"] for d in result_dicts}

                duration = asyncio.get_event_loop().time() - start_time
                shortlisted_count = sum(1 for v in shortlisted_map.values() if v)

                for r in results_list:
                    db.add(ScreenerResultDB(
                        run_id=run_id,
                        ticker=r.ticker,
                        company_name=r.company_name,
                        industry=r.industry,
                        rank=r.rank,
                        composite_score=r.composite_score,
                        valuation_score=r.valuation_score,
                        fundamentals_score=r.fundamentals_score,
                        jhunjhunwala_score=r.jhunjhunwala_score,
                        growth_score=r.growth_score,
                        insider_score=r.insider_score,
                        technical_score=r.technical_score,
                        is_shortlisted=shortlisted_map.get(r.ticker, False),
                        key_metrics=r.key_metrics,
                        scored_at=r.scored_at,
                        error=r.error,
                    ))

                db.query(ScreenerRun).filter(ScreenerRun.id == run_id).update({
                    "status": "COMPLETE",
                    "stocks_screened": len(results_list),
                    "shortlisted_count": shortlisted_count,
                    "duration_seconds": round(duration, 1),
                })
                db.commit()

                yield f"data: {json.dumps({'type': 'backfill_day_complete', 'date': date_str, 'day': day_idx, 'total_days': len(dates_to_run), 'run_id': run_id, 'shortlisted': shortlisted_count})}\n\n"

            except Exception as exc:
                logger.error("Backfill day %s failed: %s", date_str, exc, exc_info=True)
                db.query(ScreenerRun).filter(ScreenerRun.id == run_id).update(
                    {"status": "ERROR", "error_message": str(exc)}
                )
                db.commit()
                yield f"data: {json.dumps({'type': 'error', 'message': f'Day {date_str} failed: {exc}', 'date': date_str})}\n\n"

        yield f"data: {json.dumps({'type': 'backfill_complete', 'days_run': len(dates_to_run), 'skipped': skipped})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# GET /screener/runs/{id}/results
# ---------------------------------------------------------------------------

@router.get("/runs/{run_id}/results")
def get_run_results(run_id: int, db: Session = Depends(get_db)):
    """Return full ranked table for one run. AC-0107"""
    run = db.query(ScreenerRun).filter(ScreenerRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    results = (
        db.query(ScreenerResultDB)
        .filter(ScreenerResultDB.run_id == run_id)
        .order_by(ScreenerResultDB.rank.asc())
        .all()
    )
    return {
        "run": {
            "id": run.id,
            "run_at": run.run_at.isoformat() if run.run_at else None,
            "threshold_mode": run.threshold_mode,
            "weight_profile": run.weight_profile,
            "stocks_screened": run.stocks_screened,
            "shortlisted_count": run.shortlisted_count,
            "duration_seconds": run.duration_seconds,
            "status": run.status,
            "run_date": run.run_date,
        },
        "results": [_result_to_dict(r) for r in results],
    }


# ---------------------------------------------------------------------------
# GET /screener/runs/{id}/results/{ticker}
# ---------------------------------------------------------------------------

@router.get("/runs/{run_id}/results/{ticker}")
def get_ticker_result(run_id: int, ticker: str, db: Session = Depends(get_db)):
    """Detail for one stock in one run. AC-0110"""
    result = (
        db.query(ScreenerResultDB)
        .filter(
            ScreenerResultDB.run_id == run_id,
            ScreenerResultDB.ticker == ticker,
        )
        .first()
    )
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    return _result_to_dict(result)


# ---------------------------------------------------------------------------
# POST /screener/ticker — on-demand score for a custom ticker
# ---------------------------------------------------------------------------

@router.post("/ticker")
async def score_custom_ticker(req: CustomTickerRequest, db: Session = Depends(get_db)):
    """On-demand deterministic score for any .NS/.BO ticker. AC-0112"""
    from src.screener.run_screener import run_screener

    profile = _make_profile(req.weight_profile, req.custom_weights)
    ticker = req.ticker.upper()
    if not ticker.endswith((".NS", ".BO", ".BSE")):
        ticker = ticker + ".NS"

    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(
        _executor,
        lambda: run_screener(tickers=[ticker], profile=profile),
    )

    if not results:
        raise HTTPException(status_code=500, detail="Scoring returned no results")

    r = results[0]
    return {
        "ticker": r.ticker,
        "composite_score": r.composite_score,
        "valuation_score": r.valuation_score,
        "fundamentals_score": r.fundamentals_score,
        "jhunjhunwala_score": r.jhunjhunwala_score,
        "growth_score": r.growth_score,
        "insider_score": r.insider_score,
        "technical_score": r.technical_score,
        "key_metrics": r.key_metrics,
        "error": r.error,
    }


# ---------------------------------------------------------------------------
# GET /screener/constituents
# ---------------------------------------------------------------------------

@router.get("/constituents")
def get_constituents(db: Session = Depends(get_db)):
    """Return active Nifty 500 list from DB. AC-0103"""
    rows = (
        db.query(NiftyConstituent)
        .filter(NiftyConstituent.is_active == True)
        .order_by(NiftyConstituent.symbol)
        .all()
    )
    return [
        {
            "symbol": r.symbol,
            "ticker": r.ticker,
            "company_name": r.company_name,
            "industry": r.industry,
            "isin": r.isin,
            "added_at": r.added_at.isoformat() if r.added_at else None,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# POST /screener/constituents/refresh
# ---------------------------------------------------------------------------

@router.post("/constituents/refresh")
async def refresh_constituents(db: Session = Depends(get_db)):
    """
    Fetch latest Nifty 500 list and diff against stored list.
    Logs additions and removals. AC-0104
    """
    from src.screener.constituents import get_nifty500_constituents

    loop = asyncio.get_event_loop()
    fresh = await loop.run_in_executor(None, get_nifty500_constituents)

    fresh_symbols = {r["symbol"] for r in fresh}
    fresh_by_symbol = {r["symbol"]: r for r in fresh}

    existing = db.query(NiftyConstituent).all()
    existing_by_symbol = {r.symbol: r for r in existing}
    existing_active = {r.symbol for r in existing if r.is_active}

    added: list[str] = []
    removed: list[str] = []
    now = datetime.now(timezone.utc)

    # New symbols
    for sym in fresh_symbols - existing_active:
        if sym in existing_by_symbol:
            # Re-activated
            existing_by_symbol[sym].is_active = True
            existing_by_symbol[sym].removed_at = None
            existing_by_symbol[sym].last_refreshed = now
        else:
            db.add(NiftyConstituent(
                symbol=sym,
                ticker=fresh_by_symbol[sym]["ticker"],
                company_name=fresh_by_symbol[sym]["company_name"],
                industry=fresh_by_symbol[sym].get("industry", ""),
                isin=fresh_by_symbol[sym].get("isin", ""),
                is_active=True,
                last_refreshed=now,
            ))
        added.append(sym)
        logger.info("Constituent added: %s", sym)

    # Removed symbols
    for sym in existing_active - fresh_symbols:
        existing_by_symbol[sym].is_active = False
        existing_by_symbol[sym].removed_at = now
        existing_by_symbol[sym].last_refreshed = now
        removed.append(sym)
        logger.info("Constituent removed: %s", sym)

    # Update existing (company_name / industry may change)
    for sym in fresh_symbols & existing_active:
        row = existing_by_symbol[sym]
        row.company_name = fresh_by_symbol[sym]["company_name"]
        row.industry = fresh_by_symbol[sym].get("industry", row.industry)
        row.last_refreshed = now

    db.commit()

    return {
        "total": len(fresh_symbols),
        "added": added,
        "removed": removed,
    }
