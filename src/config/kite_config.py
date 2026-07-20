"""
Kite Connect credential loader for the ai-hedge-fund screener.

Resolution order for KITE_ACCESS_TOKEN:
  1. KITE_ACCESS_TOKEN environment variable
  2. ~/workspace/Intraday/secrets/access_token.txt (OCE project daily refresh fallback)
  3. Empty string (Kite not available; screener falls back to yfinance for price data)

No external dependencies — stdlib only.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_FALLBACK_TOKEN_PATH = Path("~/workspace/Intraday/secrets/access_token.txt").expanduser()


def get_kite_config() -> dict:
    """Return {"api_key": str | None, "access_token": str}.

    AC-SCR-202a: returns {"api_key": None, "access_token": ""} when nothing is configured.
    AC-SCR-202b: returns env var value for KITE_API_KEY when set.
    AC-SCR-202c: reads access token from fallback file when env var absent and file exists.
    AC-SCR-202d: logs WARNING when fallback file is used.
    """
    api_key: str | None = os.environ.get("KITE_API_KEY") or None
    if api_key is None:
        logger.warning("KITE_API_KEY not set — Kite Connect is not configured; screener will use yfinance for price data")

    access_token = os.environ.get("KITE_ACCESS_TOKEN", "").strip()

    if not access_token:
        if _FALLBACK_TOKEN_PATH.is_file():
            access_token = _FALLBACK_TOKEN_PATH.read_text().strip()
            logger.warning(
                "KITE_ACCESS_TOKEN env var not set; loaded access token from fallback path %s",
                _FALLBACK_TOKEN_PATH,
            )

    return {"api_key": api_key, "access_token": access_token}
