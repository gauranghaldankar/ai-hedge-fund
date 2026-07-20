# SCR-203 — `src/tools/kite_api.py` — Kite Price Fetch Module

**Type:** New module
**Priority:** Must-Do
**Spec:** `docs/requirements/kite-migration-backfill-removal.md` § C, Ticket SCR-203; § B Decisions 1, 4
**Depends on:** SCR-202
**Blocks:** SCR-204, SCR-206

---

## Summary

Create `src/tools/kite_api.py` exposing two public functions for fetching daily OHLCV
candles from Kite Connect. The module is the only place in the screener that calls
`kite.instruments()` and `kite.historical_data()`.

---

## File to Create

`src/tools/kite_api.py`

---

## Public Interface

### `build_token_lookup(kite) -> dict[str, int]`

- Calls `kite.instruments("NSE")`.
- Filters rows to `instrument_type == "EQ"`.
- Returns `{tradingsymbol: instrument_token}` dict.
- Returns `{}` (empty dict) on any exception. Never raises.

### `get_price_data_kite(symbol, start_date, end_date, token_lookup=None, kite=None) -> pd.DataFrame | None`

Parameters:
- `symbol`: bare NSE symbol string, e.g. `"RELIANCE"` (no `.NS` suffix)
- `start_date`, `end_date`: `"YYYY-MM-DD"` strings
- `token_lookup`: pre-built dict from `build_token_lookup()`; if `None`, builds one internally
- `kite`: `KiteConnect` instance; if `None`, builds one from `get_kite_config()`

Returns:
- `pd.DataFrame` with columns `open`, `high`, `low`, `close`, `volume` (all lowercase),
  DatetimeIndex, sorted ascending, at least 1 row.
- `None` on any failure (symbol not found, network error, empty response, Kite not configured).

Implementation notes:
- `kite.historical_data()` expects Python `date` objects, not strings. Parse inside function.
- Apply `time.sleep(0.35)` before each `kite.historical_data()` call (Kite rate limit: 3 req/sec).
- Import `kiteconnect` inside the function body, not at module top level, so the module
  is importable when `kiteconnect` is not installed.
- Wrap all Kite calls in try/except; log `WARNING` and return `None` on any exception.

---

## Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-SCR-203a | `get_price_data_kite("RELIANCE", "2026-06-01", "2026-07-18", token_lookup={"RELIANCE": 738561}, kite=<mock>)` returns a DataFrame with columns `open, high, low, close, volume` and a DatetimeIndex |
| AC-SCR-203b | The returned DataFrame rows are sorted in ascending date order |
| AC-SCR-203c | `get_price_data_kite("NOTEXIST", ..., token_lookup={})` returns `None` without raising |
| AC-SCR-203d | `get_price_data_kite(...)` returns `None` if `kite.historical_data()` raises any exception |
| AC-SCR-203e | The module is importable even when `kiteconnect` is not installed |
| AC-SCR-203f | `build_token_lookup()` returns `{}` (not an exception) if `kite.instruments()` raises |
