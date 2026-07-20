# FLW-004 — Add TTL and date-aware invalidation to in-memory cache

**Priority:** Should Have
**Component:** Backend — `src/data/cache.py`, `src/tools/yf_api.py`
**Related spec:** `docs/analysis/flow-indian-stock-bugs-pm-report.md` (Bug 1, secondary defect)

---

## Problem Statement

The in-memory cache (`src/data/cache.py`) has no time-to-live (TTL) mechanism. Once a value is written, it persists for the lifetime of the server process. For price data specifically, this means:

1. A server started days ago will hold stale price entries indefinitely.
2. The `yf_api.py` price cache uses compound keys (`yf_{ticker}_{start_date}_{end_date}`) while the `cache.py` API accepts any string as the key. A compound-key hit on a different date range simply writes a new independent entry — the cache accumulates unbounded entries per ticker rather than serving or invalidating them correctly.
3. There is no mechanism to force a refresh of `t.info`-derived data (financial metrics, market cap), which yfinance itself caches internally for the process lifetime.

This defect is lower urgency than FLW-001 because FLW-001's fix (computing dates at click time) means users will always send correct dates. However, without a TTL, a long-running server can still serve stale price ranges from a previous day's in-memory cache even when the dates are correct.

---

## Root Cause

`cache.py` stores data in plain Python dicts with no expiry metadata:

```python
class Cache:
    def __init__(self):
        self._prices_cache: dict[str, list[dict]] = {}
        ...

    def set_prices(self, ticker: str, data: list[dict]):
        self._prices_cache[ticker] = self._merge_data(...)   # no TTL stored
```

`yf_api.py` constructs date-scoped cache keys but relies on the same TTL-less store:

```python
cache_key = f"yf_{ticker}_{start_date}_{end_date}"
if cached := _cache.get_prices(cache_key):
    return [Price(**p) for p in cached]
```

There is also a known key-signature mismatch documented in `docs/system-map.md`: `api.py` (the financialdatasets.ai path) passes compound keys while `cache.py` was originally designed for plain ticker keys, causing the merge logic to be dead for that path.

---

## Acceptance Criteria

**AC-0216** — Price data cached by `yf_api.py` must expire and be re-fetched from yfinance after at most 4 hours. A request arriving after the TTL must not return the stale cache entry.
- Test: populate the cache, advance a mocked clock by more than 4 hours, call `get_prices()`, assert that `yf.download()` is called again (i.e., the cache miss path is taken).

**AC-0217** — Price data fetched within the TTL window must be served from cache and must not trigger a new `yf.download()` call.
- Test: populate cache, advance clock by less than 4 hours, call `get_prices()`, assert `yf.download()` is not called.

**AC-0218** — Financial metrics data (from `t.info`) must expire and be re-fetched from yfinance after at most 24 hours. The TTL for metrics is longer than for prices because `.info` is a heavier call and changes at a daily cadence.
- Test: same pattern as AC-0216 with a 24-hour clock advance and `get_financial_metrics()`.

**AC-0219** — The TTL implementation must not require a background thread or external scheduler. A lazy expiry check on cache read is acceptable.
- Test: verify no `threading.Thread` or `asyncio.Task` is created by the cache module.

**AC-0220** — The fix must not break the existing in-process cache behaviour for the financialdatasets.ai path in `api.py`. US ticker cache reads and writes must continue to work correctly.
- Test: run `poetry run pytest tests/` with no regressions on any existing cache-related test.

**AC-0221** — The cache must not grow unboundedly. After the TTL expires, the stale entry must be evicted (removed from the dict) on the next read attempt for that key, not retained in memory.
- Test: populate cache with multiple entries, advance clock past TTL, call get on expired entries, assert the internal dict no longer contains those keys.

---

## Implementation Notes

- A simple approach: store `(data, expiry_timestamp)` tuples in the cache dict. On `get_*()`, check `time.time() > expiry_timestamp`; if expired, delete the entry and return `None`. On `set_*()`, store `(data, time.time() + TTL_SECONDS)`.
- TTL constants: `PRICE_TTL = 4 * 3600` (4 hours), `METRICS_TTL = 24 * 3600` (24 hours), `NEWS_TTL = 6 * 3600`, `INSIDER_TTL = 24 * 3600`.
- This change requires updating both `Cache.get_*` and `Cache.set_*` method signatures. Because the cache is a singleton, no caller code (in `yf_api.py` or `api.py`) needs to change — only `cache.py` internals.
- The known key-mismatch between `api.py` and `cache.py` (compound vs plain keys) is a pre-existing defect noted in `docs/system-map.md`. This ticket should not attempt to fix that mismatch — it is a separate refactor. Only the TTL/eviction mechanism is in scope here.
- Do not introduce dependencies beyond the Python standard library for this change.
