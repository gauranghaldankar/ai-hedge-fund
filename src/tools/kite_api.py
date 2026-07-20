"""
Kite Connect price data adapter for the Nifty 500 screener.

Public interface:
    build_token_lookup(kite) -> dict[str, int]
    get_price_data_kite(symbol, start_date, end_date, token_lookup, kite) -> pd.DataFrame | None

kiteconnect is imported lazily inside functions so the module is importable
when the package is not installed (AC-SCR-203e).

Rate limit: Kite allows ~3 req/sec. A 0.35s sleep is applied before each
historical_data() call to stay safely under the limit (AC-0121).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)


def build_token_lookup(kite) -> dict[str, int]:
    """
    Fetch the NSE instrument list and return {tradingsymbol: instrument_token}
    for all EQ (equity spot) instruments.

    Returns {} on any exception — never raises (AC-SCR-203f).
    """
    try:
        instruments = kite.instruments("NSE")
        return {
            inst["tradingsymbol"]: inst["instrument_token"]
            for inst in instruments
            if inst.get("instrument_type") == "EQ"
        }
    except Exception as exc:
        logger.warning("build_token_lookup failed: %s", exc)
        return {}


def get_price_data_kite(
    symbol: str,
    start_date: str,
    end_date: str,
    token_lookup: dict[str, int] | None = None,
    kite=None,
) -> pd.DataFrame | None:
    """
    Fetch daily OHLCV candles from Kite Connect for a bare NSE symbol
    (e.g. "RELIANCE", no .NS suffix).

    Parameters
    ----------
    symbol      : bare NSE tradingsymbol, e.g. "RELIANCE"
    start_date  : "YYYY-MM-DD" string
    end_date    : "YYYY-MM-DD" string
    token_lookup: pre-built {tradingsymbol: instrument_token} from build_token_lookup();
                  if None, attempts to build one (makes an extra instruments() call)
    kite        : KiteConnect instance; if None, attempts to build from get_kite_config()

    Returns
    -------
    pd.DataFrame with lowercase columns open/high/low/close/volume and DatetimeIndex,
    sorted ascending. None on any failure (AC-SCR-203c, AC-SCR-203d).
    """
    # Resolve kite client
    if kite is None:
        try:
            from kiteconnect import KiteConnect  # noqa: PLC0415
            from src.config.kite_config import get_kite_config
            cfg = get_kite_config()
            if not cfg["api_key"] or not cfg["access_token"]:
                return None
            kite = KiteConnect(api_key=cfg["api_key"])
            kite.set_access_token(cfg["access_token"])
        except Exception as exc:
            logger.debug("Kite client init failed in get_price_data_kite: %s", exc)
            return None

    # Resolve instrument token
    if token_lookup is None:
        token_lookup = build_token_lookup(kite)

    token = token_lookup.get(symbol)
    if token is None:
        logger.debug("Symbol %s not found in Kite token lookup", symbol)
        return None

    # Parse date strings to date objects (Kite API requires date objects)
    try:
        from_date = datetime.strptime(start_date, "%Y-%m-%d").date()
        to_date = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError as exc:
        logger.warning("Invalid date format for Kite fetch (%s, %s): %s", start_date, end_date, exc)
        return None

    # Respect Kite rate limit: ~3 req/sec
    time.sleep(0.35)

    try:
        candles = kite.historical_data(token, from_date, to_date, "day")
    except Exception as exc:
        logger.warning("kite.historical_data failed for %s (token=%s): %s", symbol, token, exc)
        return None

    if not candles:
        return None

    try:
        df = pd.DataFrame(candles)
        # Kite returns "date" as a datetime; set as index
        df = df.rename(columns={"date": "Date"}).set_index("Date")
        # Normalise column names to lowercase to match yfinance convention
        df.columns = [c.lower() for c in df.columns]
        # Keep only OHLCV columns scorer needs
        df = df[["open", "high", "low", "close", "volume"]]
        df = df.sort_index(ascending=True)
        return df
    except Exception as exc:
        logger.warning("DataFrame construction failed for %s: %s", symbol, exc)
        return None
