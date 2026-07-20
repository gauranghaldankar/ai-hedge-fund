# SCR-206 — Tests for `kite_api.py`

**Type:** Tests
**Priority:** Should-Do
**Spec:** `docs/requirements/kite-migration-backfill-removal.md` § C, Ticket SCR-206
**Depends on:** SCR-203
**Blocks:** Nothing

---

## Summary

Add unit tests for `src/tools/kite_api.py` using `unittest.mock`. Zero live network calls.
Tests must pass even when the `kiteconnect` package is not installed.

---

## File to Create

`src/screener/tests/test_kite_api.py`

---

## Required Test Cases

All tests mock `kiteconnect.KiteConnect` at the boundary — never call the real API.

| # | Test function | Scenario | Expected result |
|---|---|---|---|
| 1 | `test_build_token_lookup_success` | `kite.instruments("NSE")` returns a list with EQ and non-EQ rows | Result dict contains only EQ tradingsymbols and their integer tokens |
| 2 | `test_build_token_lookup_exception` | `kite.instruments()` raises `Exception("network error")` | Returns `{}` without raising |
| 3 | `test_get_price_data_kite_success` | `kite.historical_data()` returns 30 OHLCV dicts with `datetime` date fields | DataFrame with lowercase columns, DatetimeIndex, 30 rows, sorted ascending |
| 4 | `test_get_price_data_kite_symbol_not_in_lookup` | Symbol not in `token_lookup` dict | Returns `None` |
| 5 | `test_get_price_data_kite_historical_data_exception` | `kite.historical_data()` raises | Returns `None` without raising |
| 6 | `test_get_price_data_kite_empty_response` | `kite.historical_data()` returns `[]` | Returns `None` |
| 7 | `test_get_price_data_kite_no_kite_instance` | Called with `kite=None` and no env vars | Returns `None` without raising |

---

## Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-SCR-206a | All 7 test cases pass under `poetry run pytest src/screener/tests/test_kite_api.py` |
| AC-SCR-206b | Tests make zero network calls (all Kite interactions are mocked) |
| AC-SCR-206c | Tests pass even when `kiteconnect` package is not installed |
