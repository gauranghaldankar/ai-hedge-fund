# PM Analysis Report — Backfill Defect: All Scores Return 50.0

**Date:** 2026-07-20
**Author:** Product Manager (AgentCo)
**Status:** Awaiting founder decision on recommended action
**Linked spec:** `docs/spec/screener-prd.md` — AC-0115
**Evidence base:** Engineering screenshots (2026-07-20 backfill run), code review of `src/tools/yf_api.py`, `src/screener/run_screener.py`, `app/backend/routes/screener.py`, timing comparison table

---

## 1. Root Cause Summary

The backfill feature (AC-0115) issued 7 sequential full-universe screener runs (7 x 500 = 3,500 rapid-fire yfinance requests with `max_workers=10`). yfinance rate-limited the process after the first few days, causing `yf.Ticker.info` to return an empty `{}` dict for most tickers. Every scoring function in `scorer.py` is designed to return the neutral value `50.0` when its inputs are `None`, so all 500 stocks in the final backfill day (2026-07-20) received a composite score of exactly 50.0. The 39s completion time versus the expected 139s confirms that yfinance returned empty results instantly rather than fetching real data.

There is a second, deeper structural defect underneath the rate-limiting: `yf.Ticker.info` always returns current live data and has no point-in-time historical fundamentals capability. Even if rate-limiting were solved, every backfill day would produce identical fundamental, valuation, growth, and JJ scores — only the technical score (derived from OHLCV history) and the insider score (date-filtered) would genuinely differ across dates. The PRD claim that "yfinance provides historical OHLCV and fundamental data by date" (screener-prd.md §7-Day Backfill) is factually incorrect for the fundamentals side.

---

## 2. Impact Assessment

### What is broken

| Item | Status | Detail |
|---|---|---|
| All 7 backfill ScreenerRun records for 2026-07-20 day | Corrupted | Composite 50.0 for all 500 stocks; all key metrics null |
| Historical comparison feature (AC-0114) | Broken by extension | Score delta badges will show near-zero or zero change across all backfill days because scores are uniform |
| Shortlist ordering in backfill runs | Meaningless | Top 25 is alphabetical, not merit-based |
| Trust in the screener product at launch | Damaged | A user opening the screener on day 1 sees 7 days of flat-line history |

### What still works

| Item | Status |
|---|---|
| Manual "Run Screener" triggered run (non-backfill) | Working — confirmed by 19 Jul run producing rich, differentiated scores |
| Constituent fetch and DB persistence | Working |
| SSE streaming progress | Working |
| Technical score component within any single run | Working — OHLCV data is genuinely historical |
| Insider score component | Working — insider trades are date-filtered |
| All 44 unit tests | Green — scorer functions are pure and correct given valid input |
| AC-0101 through AC-0114 and AC-0116 through AC-0117 | Unaffected — defect is isolated to backfill path |

### Severity

**High.** The defect affects launch-day data quality for a feature that was explicitly listed as a first-deploy requirement. It does not affect the core daily screener workflow, but it corrupts the historical record and produces a misleading out-of-box experience. It is not a data-loss risk (the corrupted records can be deleted and re-run), but it is a correctness risk if a founder acts on the alphabetical "shortlist."

---

## 3. Fix Options (ranked by effort and value)

The options below are listed from tactical band-aid to principled redesign. All effort estimates assume one engineer-day as the unit.

---

### Option A — Cache reuse across backfill days (suppress end_date in metrics cache key)

**What it does:** Change the `get_financial_metrics` cache key from `yf_fm_{ticker}_{period}_{end_date}_{limit}` to `yf_fm_{ticker}_{period}_{limit}`, so all 7 backfill days share a single cache-warmed fetch per ticker (500 yfinance calls instead of 3,500).

**Effort:** 0.25 days (one-line cache key change).

**Value:** Eliminates the rate-limiting trigger. The first backfill day fetches real live data; days 2-7 read from cache and score identically to day 1 on the fundamentals/valuation/growth/JJ components.

**Residual problem:** Does not fix the underlying architectural flaw. The 7 backfill days will still show identical fundamental scores (because the data is always live, not point-in-time). The technical and insider components will differ per day, giving some variation, but the multi-day history will be misleading — it implies fundamentals changed day-to-day when they did not.

**Verdict:** Stops the bleeding but leaves a lie in the data. Acceptable only as a hotfix if the founder needs any working backfill immediately.

---

### Option B — Rate-limit between backfill days (sleep between day batches)

**What it does:** Insert a configurable sleep (e.g., 60 seconds) between each of the 7 day-batches in the backfill loop in `app/backend/routes/screener.py`.

**Effort:** 0.25 days.

**Value:** May reduce rate-limiting. Does not guarantee it — yfinance throttling thresholds are undocumented and may reset on longer windows.

**Residual problem:** Makes backfill take 7+ minutes longer with no improvement to data quality. The fundamentals are still live-only data, so all 7 days still show identical fundamental scores. This option treats a symptom without addressing either the rate-limiting root cause or the architectural flaw.

**Verdict:** Least value of any option. Not recommended.

---

### Option C — Redesign backfill to only backfill what is genuinely historical (price/technical)

**What it does:** Acknowledge that yfinance cannot provide point-in-time fundamentals. Redefine the backfill to run only the technical score (OHLCV-based, fully historical) and the insider score (date-filtered) across the 7 days. For fundamental components (valuation, fundamentals, JJ, growth), populate all 7 days with today's live fetch once, clearly labelled in the DB (`data_as_of` field on `ScreenerResult`). The UI shows a tooltip: "Fundamental data as of today; technical data is historical."

**Effort:** 1.5 days (data model change, backfill logic refactor, UI tooltip).

**Residual problem:** The composite score across 7 days still only reflects technical variation. Whether that variation is meaningful for a medium-to-long term screener (where technicals are out of scope per the PRD's weight profile) is debatable.

**Verdict:** Honest and implementable. The correct architectural answer if the founder wants a backfill feature at all. Requires amending AC-0115.

---

### Option D — Drop backfill entirely; run today's screener daily going forward

**What it does:** Delete all 7 corrupted backfill `ScreenerRun` records. Remove the backfill endpoint and loop. History accumulates naturally from daily manual runs. After 7 days of operation, the History dropdown has 7 real entries.

**Effort:** 0.5 days (delete backfill code, clear corrupted DB records, update UI to show "No historical data yet — history builds daily").

**Value:** Zero misleading data. The history feature (AC-0113/AC-0114) works correctly once it has naturally accumulated runs. No architectural compromise in the data.

**Residual problem:** Launch day has no historical data. The score-delta badge (AC-0114) does not appear until day 2. This is honest, not broken.

**Verdict:** Cleanest option. Eliminates a complex feature that was solving a problem (multi-day history at launch) whose architectural precondition (point-in-time fundamentals from yfinance) does not exist.

---

## 4. Recommended Action

**Recommended: Option D (drop backfill), with Option A as an optional fast-follow if the founder considers day-1 history important.**

Rationale:

1. The problem that AC-0115 was solving — having 7 days of history ready on launch day — is only meaningful if that history is accurate. Corrupted 50.0 scores are worse than no history: they imply the product ran correctly and produced a result. Empty history is honest.

2. The architectural precondition for AC-0115 does not hold. yfinance `.info` is documented as returning current live data. There is no yfinance method that returns point-in-time historical fundamentals for Indian equities. The PRD's assumption to the contrary was a factual error.

3. The daily manual run path works correctly and produces accurate, differentiated scores (confirmed by 19 Jul manual run: INDIANB 83.1, KOTAKBANK 82.8, COALINDIA 81.3). The core screener product is sound. The defect is isolated to the backfill wrapper.

4. Option D has the smallest blast radius. It removes code rather than adding complexity (no sleep hacks, no cache key surgery, no data model amendments). It keeps the codebase aligned with its actual data capabilities.

5. If the founder decides 7-day history at launch is a hard requirement, combine Option D (delete corrupted records, remove backfill loop) with Option A (cache key change) and rerun. Accept that "historical" fundamental scores for days 2-7 are actually today's live data re-used, and document that clearly in the UI. Do not pretend the data is point-in-time.

**Immediate steps (before any code change):**

1. Stop presenting the corrupted backfill results to any user. If the web app is running, the founder should not use the backfill run results for any investment decision.
2. The engineer should delete the corrupted ScreenerRun records (ids corresponding to the 2026-07-20 backfill batch) from the database before the fix is deployed.
3. Founder reviews this report and makes the go/no-go call on Option D vs Option C at the approval boundary below.

---

## 5. AC-0115 Disposition

**Recommendation: Amend AC-0115. The criterion as written cannot be satisfied by yfinance.**

Current text (screener-prd.md):
> AC-0115: On first deploy, screener backfills last 7 calendar days (skipping weekends + NSE holidays).

The criterion rests on the assumption that "yfinance provides historical OHLCV and fundamental data by date" (PRD §7-Day Backfill). This is true for OHLCV price data. It is false for fundamental data (P/E, P/B, ROE, DCF intrinsic value, revenue growth, etc.) — yfinance returns only the current filing snapshot via `.info`.

**Proposed amended AC-0115 (two options for founder to choose):**

| Option | Amended AC-0115 text |
|---|---|
| D (drop backfill) | AC-0115 REMOVED. History accumulates from daily runs. The History dropdown shows "No data yet" until at least one manual run has been completed. Score-delta badge (AC-0114) is hidden until two or more runs exist. |
| C (honest backfill) | AC-0115 AMENDED: On first deploy, screener backfills last 7 trading days using historical OHLCV data for the technical sub-score and date-filtered insider data for the insider sub-score. Fundamental sub-scores (valuation, fundamentals, JJ, growth) in all backfill records are populated from a single live data fetch and are labelled with a "data_as_of" timestamp. The UI renders a tooltip on backfill rows indicating that fundamental data reflects today's snapshot, not a point-in-time historical value. |

The amended AC must be marked as `deviated` in `docs/analysis/ac-registry.csv` if that file is created, per CLAUDE.md spec-driven conventions.

---

## Approval Boundary

The following decision requires founder sign-off before engineering proceeds:

- [ ] **Option D selected** — delete backfill code and corrupted records; AC-0115 removed
- [ ] **Option C selected** — honest backfill redesign; AC-0115 amended as above
- [ ] **Option A selected as hotfix only** — founder acknowledges the data will not be point-in-time accurate; AC-0115 amended to state this limitation explicitly

No engineering work should begin on the fix until the founder marks one of the above.
