# SCR-204 — Wire Kite Price Fetch into `_fetch_ticker_data()`

**Type:** Feature modification
**Priority:** Must-Do
**Spec:** `docs/requirements/kite-migration-backfill-removal.md` § C, Ticket SCR-204; § B Decisions 1, 2, 4
**Depends on:** SCR-202, SCR-203
**Blocks:** Nothing (terminal ticket in the Kite chain)

---

## Summary

Modify `src/screener/run_screener.py` so that `_fetch_ticker_data()` tries Kite Connect
first for price data and falls back to yfinance on any failure. The Kite instruments list
is fetched once per `run_screener()` invocation and shared across all worker threads.

---

## Files to Modify

- `src/screener/run_screener.py` only. No other existing file changes.

---

## Changes Required

### 1. In `run_screener()` — build Kite context once before executor submission

Before the `ThreadPoolExecutor` block, add:

```python
# Build Kite price lookup once for this run (AC-0120)
kite_token_lookup: dict[str, int] = {}
kite_client = None
try:
    from src.config.kite_config import get_kite_config
    from src.tools.kite_api import build_token_lookup
    from kiteconnect import KiteConnect
    cfg = get_kite_config()
    if cfg["api_key"] and cfg["access_token"]:
        kite_client = KiteConnect(api_key=cfg["api_key"])
        kite_client.set_access_token(cfg["access_token"])
        kite_token_lookup = build_token_lookup(kite_client)
except Exception as exc:
    logger.warning("Kite initialization failed; price data will use yfinance: %s", exc)
```

Pass `kite_token_lookup` and `kite_client` into `_score_ticker()`, which passes them into
`_fetch_ticker_data()` (add these as parameters to both functions).

### 2. In `_fetch_ticker_data()` — Kite-first price fetch

Replace the existing `# --- Price data (for technical scoring) ---` block with:

```python
# --- Price data (for technical scoring) ---
# Try Kite first; fall back to yfinance if Kite is not configured or fails (AC-0118, AC-0119)
kite_succeeded = False
if kite_token_lookup and kite_client:
    try:
        from src.tools.kite_api import get_price_data_kite
        symbol = ticker.removesuffix(".NS").removesuffix(".BO")
        prices_df = get_price_data_kite(
            symbol, start_date, end_date,
            token_lookup=kite_token_lookup, kite=kite_client
        )
        if prices_df is not None and not prices_df.empty:
            data["prices_df"] = prices_df
            kite_succeeded = True
    except Exception as exc:
        logger.debug("Kite price fetch failed for %s: %s", ticker, exc)

if not kite_succeeded:
    # yfinance fallback (existing path — unchanged)
    try:
        from src.tools.yf_api import get_price_data
        prices_df = get_price_data(ticker, start_date=start_date, end_date=end_date)
        if prices_df is not None and not prices_df.empty:
            data["prices_df"] = prices_df
    except Exception as exc:
        logger.debug("get_price_data failed for %s: %s", ticker, exc)

    # Existing secondary yfinance fallback: get_prices + prices_to_df
    if data["prices_df"] is None or (isinstance(data["prices_df"], pd.DataFrame) and data["prices_df"].empty):
        try:
            from src.tools.yf_api import get_prices, prices_to_df
            prices = get_prices(ticker, start_date=start_date, end_date=end_date)
            if prices:
                data["prices_df"] = prices_to_df(prices)
        except Exception as exc:
            logger.debug("get_prices fallback failed for %s: %s", ticker, exc)
```

### 3. Update docstrings

- Module docstring: update `Concurrency:` note to mention Kite as primary price source.
- `_fetch_ticker_data()` docstring: update to describe Kite-first, yfinance-fallback.

---

## Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-SCR-204a | When `KITE_API_KEY` and `KITE_ACCESS_TOKEN` are set and valid, `_fetch_ticker_data()` uses Kite for `prices_df` and does not call `yf_api.get_price_data()` for that ticker (AC-0118) |
| AC-SCR-204b | When Kite credentials are absent, `_fetch_ticker_data()` falls back to `yf_api.get_price_data()` exactly as before (AC-0119) |
| AC-SCR-204c | When Kite is configured but raises for a specific ticker, that ticker falls back to yfinance; the run continues (AC-0117 maintained) |
| AC-SCR-204d | `build_token_lookup()` is called exactly once per `run_screener()` invocation, not once per ticker (AC-0120) |
| AC-SCR-204e | `score_technical()` continues to receive a DataFrame with lowercase `open, high, low, close, volume` columns and a DatetimeIndex regardless of source |
| AC-SCR-204f | All 44 existing screener unit tests pass after this change |
