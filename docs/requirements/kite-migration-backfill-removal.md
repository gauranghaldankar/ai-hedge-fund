# PM Analysis + Implementation Plan
# Kite Connect Price Migration and Backfill Removal

**Date:** 2026-07-20
**Author:** Product Manager (AgentCo)
**Status:** Approved for engineering — founder directives confirmed
**Linked specs:** `docs/spec/screener-prd.md`, `docs/analysis/backfill-defect-pm-report.md`
**Supersedes:** AC-0115 (marked deviated — see Section D)

---

## A. Impact Assessment

### What changes

| Area | Change | Trigger |
|---|---|---|
| `POST /screener/backfill` endpoint | Removed entirely | Founder directive: Option D |
| `BackfillRequest` Pydantic model | Removed | No endpoint to bind it to |
| `app/backend/routes/screener.py` | Delete backfill handler (~155 lines) | Same |
| `src/screener/holidays.py` | Removed (only used by backfill) | No other consumer |
| Frontend `ScreenerToolbar.tsx` | Remove "Backfill 7 Days" button | No backend endpoint |
| Frontend `ScreenerPage.tsx` | Remove `handleBackfill`, `isBackfilling`, `backfillDay` state | Same |
| Frontend `ScreenerRunProgress.tsx` | Remove `BackfillContext` prop and backfill title branch | Same |
| Frontend `types.ts`, `screener-service.ts` | Remove `BackfillSSEEvent`, `triggerBackfill` | Same |
| SQLite data | Delete all rows with `source='backfill'` from `screener_results` and `screener_runs` | Corrupted data from post-mortem |
| `src/tools/kite_api.py` | New module: Kite Connect price fetch | Founder directive 2 |
| `src/screener/run_screener.py` `_fetch_ticker_data()` | Price fetch wired to Kite first, yfinance as fallback | Same |
| `src/config/kite_config.py` | New module: credential loading for this project | Same |

### What stays the same

| Area | Status |
|---|---|
| All 6 scorer functions in `src/screener/scorer.py` | Untouched — pure functions, data-source agnostic |
| `score_technical()` input contract (`prices_df` with lowercase OHLCV columns, min 20 rows) | Unchanged — Kite output is normalized to the same shape |
| yfinance as data source for financial metrics, free cash flow, insider trades | Unchanged — Kite has no fundamentals data |
| `src/tools/yf_api.py` `get_financial_metrics()`, `search_line_items()`, `get_insider_trades()` | Unchanged — called exactly as before |
| All 7 surviving API endpoints (`GET /screener/runs`, `POST /screener/run`, etc.) | Unchanged |
| SSE streaming pattern in `POST /screener/run` | Unchanged |
| DB schema (`NiftyConstituent`, `ScreenerRun`, `ScreenerResult` tables) | No new columns required |
| Frontend components except the 4 backfill-touching files | Unchanged |
| All 44 screener unit tests | Must remain green; no AC changes to AC-0101 through AC-0114, AC-0116, AC-0117 |
| NSE ticker symbol format in `nifty500_static.py` (`RELIANCE`, no suffix) | Unchanged in the static list. Kite uses the same bare NSE symbol. The `.NS` suffix is only needed for yfinance calls and is unchanged there. |

### Risks

| Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|
| Kite access token expires daily — screener run early morning before founder refreshes token | High | Medium | Fallback to yfinance for price data (Option 2a). Technical score degrades to yfinance quality rather than failing hard. |
| `kite.instruments("NSE")` call fails (network, Kite outage) | Low | Medium | Caught per-ticker; falls back to yfinance price fetch. The instruments list call happens once per screener run, not per ticker. |
| Token lookup: `SYMBOL` in Kite instruments list may differ from NSE constituent symbol for some stocks (e.g., name changes, corporate actions) | Medium | Low | Token lookup returns `None` on miss; per-ticker fallback to yfinance. Error logged at WARNING level so the founder can audit. |
| `ThreadPoolExecutor(max_workers=10)` issues 10 concurrent Kite historical_data requests. Kite rate limit is 3 req/sec = 180 RPM. 10 concurrent threads could burst over limit. | Medium | Low | Add `time.sleep(0.35)` inside `get_price_data_kite()` matching the rate limit used in the OCE project (2.9 req/sec effective). With 10 workers this becomes a shared bottleneck; engineer must verify and tune. Screener already runs 500 tickers with 10 threads over yfinance; the throughput budget just shifts. |
| Kite `historical_data()` returns `datetime` objects in the date field, not strings | Known | None | Handled in `kite_api.py` normalization (see Ticket 3). |
| Removing `holidays.py` if any other module imports it | Low | Low | Grep confirms only the backfill endpoint imported it. Verify before deletion. |

---

## B. Kite Integration Design Decisions

### Decision 1: Symbol to Token Resolution

**Chosen: Option 1a — resolve tokens once per screener run, cache in memory for that run.**

Rationale:
- `kite.instruments("NSE")` returns the full NSE list (~2,000+ rows) in a single REST call. This is cheap: one call per screener run versus 500 calls.
- Option 1b (SQLite cache) adds schema complexity (a new `instrument_token` column on `NiftyConstituent`) and a weekly refresh job. Given the Kite token itself expires daily and the screener is triggered manually, per-run resolution is simpler and always fresh.
- The lookup dict (`{tradingsymbol: instrument_token}`) is built once at the start of each screener run inside `get_price_data_kite()` or a helper called by `_fetch_ticker_data()`. It is passed as an argument to avoid repeated API calls across the 500 tickers being scored concurrently.

**Implementation note for engineer:** `_fetch_ticker_data()` is called inside `ThreadPoolExecutor`. The token lookup dict must be built before the executor is submitted and passed in as a parameter. The dict is read-only inside the threads; no locking needed.

### Decision 2: Graceful Fallback When Kite is Unavailable

**Chosen: Option 2a — fall back to yfinance for price data silently, with a logged WARNING.**

Rationale:
- Option 2c (hard fail) would break the screener for the 5–10 minutes it takes the founder to refresh the token. That is unacceptable for a manually triggered tool.
- Option 2b (return 50.0 neutral) destroys information — the founder loses the technical sub-score entirely even when yfinance could have provided it.
- Option 2a maintains continuity: the screener behaves exactly as it did before the Kite migration. If Kite is unavailable, technical scores are computed from yfinance OHLCV (same as today). The log makes the degraded path visible.

**Fallback trigger conditions:**
1. `KITE_API_KEY` environment variable is not set.
2. `KITE_ACCESS_TOKEN` is empty (token file missing or env var unset).
3. `kite.instruments("NSE")` raises any exception.
4. `kite.historical_data()` raises any exception for a specific ticker.
5. Token lookup returns no match for a given NSE symbol.

In all five cases, `get_price_data_kite()` returns `None`, and `_fetch_ticker_data()` falls through to its existing yfinance `get_price_data()` call.

### Decision 3: Credential Configuration

**Chosen: Project-local `.env` file with a documented optional path fallback to the OCE token file.**

Rationale:
- Sharing OCE credentials from `~/workspace/Intraday/secrets/access_token.txt` creates a cross-project dependency. If the OCE project is moved or the path changes, the ai-hedge-fund screener silently degrades.
- The ai-hedge-fund project already has its own `.env` pattern (existing `KITE_API_KEY`-style env vars are already referenced in project docs).

**Implementation:**

```
KITE_API_KEY=<your_kite_api_key>
KITE_ACCESS_TOKEN=<today_access_token>
```

Both go in `/Users/gaurang/workspace/ai-hedge-fund/.env` (already gitignored).

The `src/config/kite_config.py` module (new, see Ticket 2) reads from `os.environ` first. If `KITE_ACCESS_TOKEN` is absent, it checks the OCE fallback path `~/workspace/Intraday/secrets/access_token.txt` as a convenience — but logs a WARNING so the founder knows they are using a cross-project credential. This keeps the OCE workflow working without making it the primary path.

`KITE_API_KEY` is never read from the OCE path — only the daily-rotating token uses the fallback.

### Decision 4: Scope of Replacement

**Confirmed: Price OHLCV only. Kite replaces yfinance solely for `get_price_data()`.**

This is not a debate. The data availability table in the brief is definitive:

| Data type | Kite available | Action |
|---|---|---|
| OHLCV daily candles | Yes | Migrate to Kite |
| P/E, P/B, ROE, margins | No | Remain on yfinance |
| Free cash flow | No | Remain on yfinance |
| Insider transactions | No | Remain on yfinance |

`src/tools/yf_api.py` is **not modified**. Three of its four call sites in `_fetch_ticker_data()` remain unchanged. Only the price fetch path gets a Kite-first attempt.

---

## C. Implementation Plan — Engineering Tickets

Tickets are sequenced so each is independently completable and testable. Tickets 1, 2, and 5 have no inter-dependencies and can proceed in parallel. Tickets 3 and 4 depend on Ticket 2. Ticket 6 depends on Ticket 3.

---

### Ticket SCR-201: Delete Corrupted Backfill Records

**Priority:** Must-Do (MoSCoW: Must)
**Rationale:** Corrupted data is live in the DB. Any run of the screener web app exposes it to the founder. This ticket has zero code risk and should be done first, before the screener is used for any investment decision.

**Scope:** Data cleanup only. No code changes.

**Steps:**
1. Connect to the SQLite database at `app/backend/database/` (exact file path: `app/backend/hedge_fund.db` or as configured in `app/backend/database/connection.py`).
2. Execute in order:
   ```sql
   DELETE FROM screener_results
   WHERE run_id IN (
     SELECT id FROM screener_runs WHERE source = 'backfill'
   );
   DELETE FROM screener_runs WHERE source = 'backfill';
   ```
3. Verify: `SELECT COUNT(*) FROM screener_runs WHERE source = 'backfill';` must return 0.

**Acceptance Criteria:**
- AC-SCR-201a: `SELECT COUNT(*) FROM screener_runs WHERE source='backfill'` returns 0 after the operation.
- AC-SCR-201b: `SELECT COUNT(*) FROM screener_results WHERE run_id NOT IN (SELECT id FROM screener_runs)` returns 0 (no orphaned result rows).
- AC-SCR-201c: The existing manual run records (source='manual') are unaffected. `SELECT COUNT(*) FROM screener_runs WHERE source='manual'` returns the same count as before.

---

### Ticket SCR-202: Kite Credentials Config Module

**Priority:** Must-Do (MoSCoW: Must)
**Depends on:** Nothing
**Blocks:** SCR-203, SCR-204

**Scope:**
- New file: `src/config/kite_config.py`
- No changes to any existing file

**What the module must do:**
1. Read `KITE_API_KEY` from `os.environ`. Return `None` if absent (not an error; indicates Kite is not configured).
2. Read `KITE_ACCESS_TOKEN` from `os.environ`. If absent, attempt to read from `~/workspace/Intraday/secrets/access_token.txt`. If still absent, return empty string.
3. Expose a single public function: `get_kite_config() -> dict` returning `{"api_key": str | None, "access_token": str}`.
4. Log a `WARNING` if the access token was sourced from the fallback file path.
5. Log a `WARNING` if `api_key` is None (Kite not configured; callers will use yfinance fallback).

**Files to create:**
- `/Users/gaurang/workspace/ai-hedge-fund/src/config/__init__.py` (empty, if not already present)
- `/Users/gaurang/workspace/ai-hedge-fund/src/config/kite_config.py`

**Acceptance Criteria:**
- AC-SCR-202a: `get_kite_config()` returns `{"api_key": None, "access_token": ""}` when neither env var is set and the fallback file does not exist.
- AC-SCR-202b: `get_kite_config()` returns the env var value for `KITE_API_KEY` when set.
- AC-SCR-202c: `get_kite_config()` reads `KITE_ACCESS_TOKEN` from the fallback file path when the env var is absent and the file exists.
- AC-SCR-202d: A `WARNING` is logged when the fallback file path is used.
- AC-SCR-202e: The module is importable with no external dependencies beyond stdlib (`os`, `pathlib`, `logging`).

---

### Ticket SCR-203: `src/tools/kite_api.py` — Kite Price Fetch Module

**Priority:** Must-Do (MoSCoW: Must)
**Depends on:** SCR-202
**Blocks:** SCR-204

**Scope:**
- New file: `src/tools/kite_api.py`
- No changes to any existing file

**What the module must expose:**

```python
def build_token_lookup(kite) -> dict[str, int]:
    """
    Call kite.instruments("NSE"), filter to instrument_type == "EQ",
    return {tradingsymbol: instrument_token}.
    Returns empty dict on any exception.
    """

def get_price_data_kite(
    symbol: str,          # NSE bare symbol e.g. "RELIANCE" (no .NS suffix)
    start_date: str,      # YYYY-MM-DD string
    end_date: str,        # YYYY-MM-DD string
    token_lookup: dict[str, int] | None = None,
    kite=None,            # KiteConnect instance; if None, builds one from config
) -> pd.DataFrame | None:
    """
    Fetch daily OHLCV candles from Kite for [start_date, end_date].
    Returns a pd.DataFrame with lowercase columns: open, high, low, close, volume
    and a DatetimeIndex, sorted ascending. Min 1 row; None on any failure.
    Applies time.sleep(0.35) before the historical_data call (rate limit compliance).
    """
```

**Implementation notes for engineer:**
- `kite.historical_data()` expects Python `date` objects for `from_date` / `to_date`, not strings. Parse `start_date` / `end_date` strings to `datetime.date` inside the function.
- The returned list of dicts has key `"date"` as a `datetime` object. Convert to `pd.Timestamp` for the index.
- Column normalization: Kite returns `{"date", "open", "high", "low", "close", "volume"}` — all already lowercase. No rename needed beyond setting the DatetimeIndex.
- If `token_lookup` is `None`, call `build_token_lookup()` internally (single-ticker ad-hoc usage). In batch screener use, pass the pre-built dict to avoid re-fetching the instruments list per ticker.
- If `symbol` is not found in `token_lookup`, log `WARNING` and return `None`.
- Wrap the entire `kite.historical_data()` call in try/except; log `WARNING` and return `None` on any exception.
- Do not import `kiteconnect` at module level. Import inside the function body so that the module is importable even if `kiteconnect` is not installed.

**Files to create:**
- `/Users/gaurang/workspace/ai-hedge-fund/src/tools/kite_api.py`

**Acceptance Criteria:**
- AC-SCR-203a: `get_price_data_kite("RELIANCE", "2026-06-01", "2026-07-18", token_lookup={"RELIANCE": 738561}, kite=<mock>)` returns a DataFrame with columns `open`, `high`, `low`, `close`, `volume` and a DatetimeIndex.
- AC-SCR-203b: The returned DataFrame has rows sorted in ascending date order.
- AC-SCR-203c: `get_price_data_kite("NOTEXIST", ..., token_lookup={})` returns `None` without raising.
- AC-SCR-203d: `get_price_data_kite(...)` returns `None` if `kite.historical_data()` raises any exception.
- AC-SCR-203e: The module is importable even when `kiteconnect` package is not installed (conditional import inside function body).
- AC-SCR-203f: `build_token_lookup()` returns an empty dict (not an exception) if `kite.instruments()` raises.

---

### Ticket SCR-204: Wire Kite Price Fetch into `_fetch_ticker_data()`

**Priority:** Must-Do (MoSCoW: Must)
**Depends on:** SCR-202, SCR-203

**Scope:**
- Modify: `src/screener/run_screener.py`
- No changes to any other existing file

**What changes in `run_screener.py`:**

1. In `run_screener()` (the public entry point), before submitting tasks to the `ThreadPoolExecutor`, attempt to build the Kite token lookup:
   ```python
   # Build Kite token lookup once for the run (not per-ticker)
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
   Pass `kite_token_lookup` and `kite_client` into `_score_ticker()`, which passes them into `_fetch_ticker_data()`.

2. In `_fetch_ticker_data()`, add a Kite-first price fetch path before the existing yfinance `get_price_data()` call:
   ```python
   # --- Price data (for technical scoring) ---
   # Try Kite first; fall back to yfinance on any failure or missing config
   kite_tried = False
   if kite_token_lookup and kite_client:
       try:
           from src.tools.kite_api import get_price_data_kite
           # Strip .NS suffix to get bare NSE symbol for Kite lookup
           symbol = ticker.removesuffix(".NS").removesuffix(".BO")
           prices_df = get_price_data_kite(
               symbol, start_date, end_date,
               token_lookup=kite_token_lookup, kite=kite_client
           )
           if prices_df is not None and not prices_df.empty:
               data["prices_df"] = prices_df
               kite_tried = True
       except Exception as exc:
           logger.debug("Kite price fetch failed for %s: %s", ticker, exc)
   ```
   The existing yfinance price fetch block runs only when `not kite_tried` (i.e., Kite was not configured or failed).

3. Update the docstring on `_fetch_ticker_data()` to reflect Kite as the primary source for price data.

4. Update the module docstring at the top of `run_screener.py` (the `Concurrency:` line references yfinance exclusively; add a note that Kite is used for price data when configured).

**Acceptance Criteria:**
- AC-SCR-204a: When `KITE_API_KEY` and `KITE_ACCESS_TOKEN` are set and valid, `_fetch_ticker_data()` uses Kite for `prices_df` and does not call `yf_api.get_price_data()` for that ticker.
- AC-SCR-204b: When Kite credentials are absent (env vars not set), `_fetch_ticker_data()` falls back to `yf_api.get_price_data()` as before. Behavior is identical to the pre-migration screener.
- AC-SCR-204c: When Kite is configured but `kite.historical_data()` raises for a specific ticker, that ticker falls back to yfinance. The screener run continues (no exception propagated up — consistent with AC-0117).
- AC-SCR-204d: `build_token_lookup()` is called exactly once per `run_screener()` invocation, not once per ticker.
- AC-SCR-204e: `score_technical()` continues to receive a DataFrame with lowercase `open`, `high`, `low`, `close`, `volume` columns and a DatetimeIndex regardless of whether the source was Kite or yfinance.
- AC-SCR-204f: All 44 existing screener unit tests remain green after this change.

---

### Ticket SCR-205: Remove Backfill Feature (Backend + Frontend)

**Priority:** Must-Do (MoSCoW: Must)
**Depends on:** SCR-201 (data must be deleted first so no orphan cleanup is required)
**Can run in parallel with:** SCR-202, SCR-203, SCR-204

**Scope — backend (`app/backend/routes/screener.py`):**
1. Delete the `BackfillRequest` Pydantic model (lines 55–57).
2. Delete the entire `trigger_backfill()` handler and its `event_generator()` closure (lines 297–449).
3. Remove the `POST /screener/backfill` route decorator.
4. Update the module docstring at the top of the file to remove the `POST /screener/backfill` line.
5. Verify no other file in `app/backend/` imports `BackfillRequest`. (Grep confirms none do.)

**Scope — backend (`src/screener/holidays.py`):**
1. Verify no other file imports from `src/screener/holidays.py`. If confirmed unused, delete the file.
2. If any other file imports it, do not delete — instead leave in place and note as dead code for the founder to decide later.

**Scope — frontend (`app/frontend/src/services/screener-service.ts`):**
1. Remove `triggerBackfill()` function.
2. Remove `BackfillSSEEvent` type export.
3. Remove any import that is now unused as a result.

**Scope — frontend (`app/frontend/src/components/screener/types.ts`):**
1. Remove `BackfillSSEEvent` type definition.

**Scope — frontend (`app/frontend/src/components/screener/ScreenerPage.tsx`):**
1. Remove `isBackfilling` state variable.
2. Remove `backfillDay` state variable.
3. Remove `cancelBackfillRef` ref.
4. Remove `handleBackfill` callback and all its body.
5. Remove all props passed to `ScreenerToolbar` related to backfill (`isBackfilling`, `onBackfill`).
6. Remove the `backfill` prop passed to `ScreenerRunProgress`.
7. Remove the `BackfillSSEEvent` import from `screener-service.ts`.

**Scope — frontend (`app/frontend/src/components/screener/ScreenerToolbar.tsx`):**
1. Remove `isBackfilling` and `onBackfill` from the props interface.
2. Remove the "Backfill 7 Days" button block entirely (the `{/* Backfill button */}` comment through the closing tag).
3. Remove `isBackfilling` from all `disabled` expressions on other buttons.

**Scope — frontend (`app/frontend/src/components/screener/ScreenerRunProgress.tsx`):**
1. Remove `BackfillContext` interface.
2. Remove `backfill` prop from `ScreenerRunProgressProps`.
3. Remove the `backfill` parameter from the component function signature.
4. Remove the `title` variable ternary that references `backfill`.
5. Simplify: title is always `"Screening Nifty 500..."` or similar fixed string.

**Acceptance Criteria:**
- AC-SCR-205a: `POST /screener/backfill` returns HTTP 404 or 405 after the change (route no longer exists).
- AC-SCR-205b: The 6 surviving screener endpoints continue to return correct responses (smoke test each endpoint).
- AC-SCR-205c: The "Backfill 7 Days" button is absent from the Screener toolbar in the frontend.
- AC-SCR-205d: The frontend compiles with no TypeScript errors after the removal.
- AC-SCR-205e: `ScreenerToolbar` renders without errors when `isBackfilling` and `onBackfill` props are absent.
- AC-SCR-205f: No import of `BackfillSSEEvent` or `triggerBackfill` remains in the frontend codebase (grep check).

---

### Ticket SCR-206: Tests for `kite_api.py`

**Priority:** Should-Do (MoSCoW: Should)
**Depends on:** SCR-203

**Scope:**
- New file: `src/screener/tests/test_kite_api.py`
- Uses `unittest.mock.MagicMock` to mock the `kiteconnect.KiteConnect` instance. No live Kite API calls in tests.

**Test cases required:**

1. `test_build_token_lookup_success`: Mock `kite.instruments("NSE")` returning a list with EQ and non-EQ rows. Assert that the result dict contains only EQ tradingsymbols and their tokens.

2. `test_build_token_lookup_exception`: Mock `kite.instruments()` raising `Exception("network error")`. Assert that `build_token_lookup()` returns an empty dict without raising.

3. `test_get_price_data_kite_success`: Mock `kite.historical_data()` returning a list of 30 OHLCV dicts with `datetime` date fields. Assert that the returned DataFrame has lowercase column names, a DatetimeIndex, and 30 rows sorted ascending.

4. `test_get_price_data_kite_symbol_not_in_lookup`: Call with a symbol not in the token_lookup dict. Assert returns `None`.

5. `test_get_price_data_kite_historical_data_exception`: Mock `kite.historical_data()` raising. Assert returns `None` without raising.

6. `test_get_price_data_kite_empty_response`: Mock `kite.historical_data()` returning `[]`. Assert returns `None` (empty result treated as no data).

7. `test_get_price_data_kite_no_kite_instance`: Call with `kite=None` and no env vars set. Assert returns `None` without raising.

**Acceptance Criteria:**
- AC-SCR-206a: All 7 test cases above pass under `poetry run pytest src/screener/tests/test_kite_api.py`.
- AC-SCR-206b: Tests make zero network calls (all Kite interactions are mocked).
- AC-SCR-206c: Tests pass even when `kiteconnect` package is not installed (conditional import in the module under test means the test can mock at the right layer).

---

## D. AC-0115 Disposition

**Status: DEVIATED — removed per founder directive Option D (2026-07-20).**

**Original AC-0115 text (screener-prd.md):**
> On first deploy, screener backfills last 7 calendar days (skipping weekends + NSE holidays).

**Reason for deviation:** The architectural precondition for AC-0115 does not hold. `yf.Ticker.info` returns only current live data; there is no yfinance method that retrieves point-in-time historical fundamental data for Indian equities. Running the backfill produced 3,500 rapid-fire yfinance requests that triggered rate-limiting, causing all 500 stocks to score exactly 50.0 on the final day. The data is corrupted and misleading. The founder confirmed Option D: drop the feature entirely and let history accumulate from daily manual runs.

**Disposition record (for `docs/analysis/ac-registry.csv` when that file is created):**
```
AC-0115,deviated,2026-07-20,"Removed per founder directive Option D. Backfill produced corrupted 50.0 scores due to yfinance rate-limiting and fundamental data being live-only. History to accumulate from daily manual runs. See docs/analysis/backfill-defect-pm-report.md."
```

**Downstream effects of removing AC-0115:**
- AC-0113 (History dropdown shows last 30 runs) — unaffected; still required; works as soon as 2+ manual runs exist.
- AC-0114 (Score delta badge) — unaffected; hidden until 2+ runs exist, then appears. This is the documented honest behavior.
- `src/screener/holidays.py` — created solely for AC-0115. Removed in SCR-205 unless another consumer is found.

---

## E. New Acceptance Criteria for Kite Price Integration

The following new ACs replace the behavioral gap left by AC-0115 and formally specify the Kite integration.

| ID | Criterion |
|---|---|
| AC-0118 | When `KITE_API_KEY` and `KITE_ACCESS_TOKEN` env vars are set and valid, `_fetch_ticker_data()` fetches OHLCV price data from Kite Connect `historical_data()` for the technical sub-score computation, not from yfinance. |
| AC-0119 | When Kite credentials are absent or Kite returns an error for a ticker, `_fetch_ticker_data()` falls back to yfinance price data without raising an exception. The screener run completes normally and the technical score for that ticker reflects the yfinance-sourced data. |
| AC-0120 | `kite.instruments("NSE")` is called at most once per `run_screener()` invocation. The resulting `{tradingsymbol: instrument_token}` lookup dict is shared across all 500 concurrent ticker workers for that run. |
| AC-0121 | Kite credentials (`KITE_API_KEY`, `KITE_ACCESS_TOKEN`) are read from project-local environment variables. The module also accepts the access token from `~/workspace/Intraday/secrets/access_token.txt` as a fallback convenience, with a WARNING log when the fallback path is used. |
| AC-0122 | The "Backfill 7 Days" button is absent from the Screener UI. The History dropdown (AC-0113) shows "No historical data yet" or an empty state until at least one completed manual run exists in the database. |

---

## F. Persona x Flow Coverage Table (Validation Review)

The founder is the single user role for this system. The table below maps every flow from the screener PRD against the AC set after the Kite migration.

| Flow | Persona | Covered by ACs | Status |
|---|---|---|---|
| Daily screener run triggered manually | Founder | AC-0101, AC-0105, AC-0106, AC-0116, AC-0117 | Covered |
| Technical sub-score uses real Kite price data when configured | Founder | AC-0118 | NEW — covered |
| Technical sub-score falls back to yfinance when Kite unavailable | Founder | AC-0119 | NEW — covered |
| Kite instruments list fetched once per run (not per ticker) | System | AC-0120 | NEW — covered |
| Kite credentials loaded from project .env | Founder/DevOps | AC-0121 | NEW — covered |
| Backfill button absent from UI after removal | Founder | AC-0122 | NEW — covered |
| View ranked results table | Founder | AC-0107, AC-0108, AC-0109 | Covered |
| Drill into stock detail drawer | Founder | AC-0110, AC-0111 | Covered |
| Custom ticker on-demand score | Founder | AC-0112 | Covered |
| Historical run selection | Founder | AC-0113, AC-0114 | Covered (data accumulates from daily runs) |
| Constituent list refresh | Founder | AC-0103, AC-0104 | Covered |
| Score delta badge absent until 2+ runs | Founder | AC-0114, AC-0122 | Covered |

No TBD rows remain. All flows have at least one covering AC.

---

## G. Build Sequence

The tickets must be executed in this order to minimize risk:

1. **SCR-201** (delete corrupted DB records) — zero code risk, eliminates misleading data immediately.
2. **SCR-205** (remove backfill — backend + frontend) — can run in parallel with SCR-202/203. No dependency on Kite config.
3. **SCR-202** (Kite config module) — prerequisite for SCR-203 and SCR-204.
4. **SCR-203** (kite_api.py module) — prerequisite for SCR-204 and SCR-206.
5. **SCR-204** (wire Kite into run_screener.py) — requires SCR-202 and SCR-203.
6. **SCR-206** (tests for kite_api.py) — can proceed after SCR-203 is drafted.

**Not-Doing (explicit out-of-scope for this iteration):**
- Migrating yfinance financial metrics to any alternative source (no better alternative identified for Indian equities; Kite does not provide fundamentals).
- Kite WebSocket live quotes (founder directive: REST API only).
- Storing Kite `instrument_token` in the `NiftyConstituent` DB table (per-run in-memory lookup is sufficient given manual trigger cadence).
- Automatic daily screener scheduling (deferred per original PRD out-of-scope decision).

---

*End of PM Analysis + Implementation Plan. No engineering work should proceed on SCR-202 through SCR-206 without the founder confirming this plan. SCR-201 may proceed immediately as it is a data cleanup with no code changes.*
