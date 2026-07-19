"""
Nifty 500 constituent fetching with fallback chain.

Fetch order:
  1. nselib nse_urlfetch (same URL NSE already uses internally)
  2. Direct requests.get with User-Agent header
  3. Hardcoded static list (src/screener/nifty500_static.py)

Returns list[dict] with keys: symbol, ticker, company_name, industry, isin
"""

from __future__ import annotations

import io
import logging
from typing import Any

import pandas as pd
import requests

logger = logging.getLogger(__name__)

NSE_CSV_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
_REQUEST_TIMEOUT = 15


def _from_nselib() -> list[dict[str, Any]] | None:
    """Try fetching via nselib nse_urlfetch."""
    try:
        from nselib import capital_market  # type: ignore

        # nselib exposes a low-level HTTP helper
        raw = capital_market.nse_urlfetch(NSE_CSV_URL)  # type: ignore[attr-defined]
        if raw is None:
            return None
        df = pd.read_csv(io.StringIO(raw) if isinstance(raw, str) else io.BytesIO(raw))
        return _parse_df(df)
    except Exception as exc:
        logger.debug("nselib fetch failed: %s", exc)
        return None


def _from_direct_http() -> list[dict[str, Any]] | None:
    """Try fetching via requests with NSE User-Agent."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://www.nseindia.com/",
    }
    try:
        resp = requests.get(NSE_CSV_URL, headers=headers, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        return _parse_df(df)
    except Exception as exc:
        logger.debug("Direct HTTP fetch failed: %s", exc)
        return None


def _from_static() -> list[dict[str, Any]]:
    """Return the hardcoded static fallback list."""
    from src.screener.nifty500_static import NIFTY500_STATIC

    return [
        {
            "symbol": sym,
            "ticker": f"{sym}.NS",
            "company_name": name,
            "industry": industry,
            "isin": "",
        }
        for sym, name, industry in NIFTY500_STATIC
    ]


def _parse_df(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Parse the NSE CSV DataFrame into the standard record format."""
    # NSE CSV columns: Company Name, Industry, Symbol, Series, ISIN Code
    df.columns = [c.strip() for c in df.columns]
    records: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        symbol = str(row.get("Symbol", "")).strip()
        if not symbol:
            continue
        records.append(
            {
                "symbol": symbol,
                "ticker": f"{symbol}.NS",
                "company_name": str(row.get("Company Name", "")).strip(),
                "industry": str(row.get("Industry", "")).strip(),
                "isin": str(row.get("ISIN Code", "")).strip(),
            }
        )
    return records


def get_nifty500_constituents() -> list[dict[str, Any]]:
    """
    Return Nifty 500 constituents using the three-level fallback chain.
    Always returns a non-empty list.
    """
    result = _from_nselib()
    if result:
        logger.info("Nifty 500 fetched via nselib (%d records)", len(result))
        return result

    result = _from_direct_http()
    if result:
        logger.info("Nifty 500 fetched via direct HTTP (%d records)", len(result))
        return result

    logger.warning("NSE fetch failed — using hardcoded static list")
    static = _from_static()
    return static
