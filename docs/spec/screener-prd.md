# Screener PRD — Nifty 500 Deterministic Stock Screener

**Status:** Ready for Architecture
**Author:** Product Manager (AgentCo)
**Date:** 2026-07-20
**Approval boundary:** Founder reviewed open items — all resolved below.

---

## Problem Statement

Running the full 19-agent LLM pipeline on 500 stocks requires 7,500+ LLM calls per day —
5× over the Gemini free-tier daily quota of 1,500. We need a zero-LLM screening pass that
ranks the entire Nifty 500, persists results daily, and promotes only the top candidates to
deep LLM analysis.

---

## Goals

1. Screen all Nifty 500 stocks deterministically — zero LLM calls.
2. Produce a composite quality score (0–100) per stock using scoring logic already present
   in the agent codebase.
3. Display a ranked leaderboard in a new "Screener" tab in the existing React web app.
4. Allow drill-down into any stock's sub-score breakdown.
5. Accept custom tickers (not in Nifty 500) on-demand.
6. Surface a shortlist based on one of three selectable threshold modes.
7. Run daily post-market and persist last 30 days of results.

---

## Resolved Decisions (Founder sign-off 2026-07-20)

| # | Question | Decision |
|---|---|---|
| 1 | Nifty 500 constituent source | nselib pattern primary → direct NSE URL fallback → hardcoded list last resort (see §4) |
| 2 | Constituent list refresh | Monthly, manual trigger via UI button |
| 3 | Scheduler | Manual trigger for daily run (APScheduler deferred to later) |
| 4 | Backfill on launch | 7 calendar days of historical scores on first deploy |

---

## Composite Score Design

Weights chosen for **medium-to-long term investing** (2–5 year hold horizon).
Technicals excluded — short-term price action is noise at this horizon.

| Sub-Score | Weight | Extracted From | What It Measures |
|---|---|---|---|
| Valuation | 30% | `valuation_analyst` deterministic path | Discount to intrinsic value: DCF margin of safety + Graham Number blended |
| Fundamentals Quality | 25% | `fundamentals_analyst` (already no LLM) | ROE, margins, debt health, profitability consistency |
| Jhunjhunwala Score | 20% | `rakesh_jhunjhunwala` scoring fn (pre-LLM) | 24-pt India quality score: profitability + growth + balance sheet + FCF + mgmt |
| Growth Consistency | 15% | `growth_analyst` (already no LLM) | Revenue + earnings CAGR, quarter-on-quarter trend |
| Insider Sentiment | 10% | `sentiment_analyst` (already no LLM) | Insider buy/sell ratio |

**Formula:** `composite = 0.30V + 0.25F + 0.20J + 0.15G + 0.10I` (all sub-scores 0–100)

**Colour bands:**

| Range | Band | Meaning |
|---|---|---|
| 80–100 | Deep green | Strong candidate — schedule full LLM analysis |
| 60–79 | Green | Watchlist |
| 40–59 | Yellow | Neutral — monitor |
| 0–39 | Red | Screen out |

---

## Three Shortlist Threshold Options

All three operate on the same full-ranked table; they only change what gets highlighted as "shortlisted."

| Option | Rule | Best For |
|---|---|---|
| **Fixed Top 25** | Always highlight the top 25 by composite score | Daily discipline: consistent review regardless of market mood |
| **Top 5% of universe** | Top 25 from Nifty 500 (25 = 5% of 500); scales if universe changes | Proportional: naturally adapts if index size changes |
| **Score ≥ 60** | Highlight only stocks with composite ≥ 60/100 | Quality gate: count shrinks in expensive markets, grows in cheap ones |

The UI shows all three toggles. The user can switch between them without re-running the screener.

---

## Nifty 500 Constituent Data Strategy

### Fetch order (fallback chain)

```
1. nselib nse_urlfetch("https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv")
   — same URL pattern nselib already uses for Nifty 50; no auth needed.
   — Returns: Company Name, Industry, Symbol, Series, ISIN Code (500 rows confirmed).

2. Direct requests.get on the same URL with User-Agent header
   — Tested: returns 200, 500 rows.

3. Hardcoded static list in src/screener/nifty500_static.py
   — Maintained manually; serves as final safety net.
```

Tickers are stored as `SYMBOL.NS` (append `.NS` to the NSE Symbol column).

### Monthly refresh

- UI button: "Refresh Nifty 500 List" (visible in Screener settings panel).
- On trigger: fetch → diff against stored list → update `NiftyConstituent` table.
- Log additions/removals so the founder can review constituent changes.
- No automatic schedule (manual for now; APScheduler can be wired later).

---

## Daily Run Trigger (Manual)

- UI button: "Run Screener" in the Screener tab toolbar.
- Streams SSE progress (same pattern as `/hedge-fund/run`): per-stock status, overall progress %.
- Completes full Nifty 500 in under 10 minutes (acceptance criterion AC-0112).
- Result persisted as a new `ScreenerRun` record.

---

## 7-Day Backfill (First Deploy Only)

On the first deployment, run the screener for each of the last 7 calendar days (skip weekends
and NSE holidays). yfinance provides historical OHLCV and fundamental data by date, so the
deterministic scoring can be run for past dates. Each backfill day is stored as a separate
`ScreenerRun` record with `source = "backfill"`.

NSE holiday list for 2026 is bundled as a small static dict in `src/screener/holidays.py`.

---

## User Flows

### Flow 1 — Daily review (primary)

1. User opens the web app and clicks the "Screener" tab.
2. Last run info shown in toolbar: date/time, stocks screened, shortlisted count.
3. Top section: shortlisted stocks in a highlighted card band.
4. Main table: all 500 stocks ranked by composite score.
   - Columns: Rank, Ticker, Company, Sector, Composite, Valuation, Fundamentals, Jhunjhunwala, Growth, Insider.
   - Sortable by any column; filterable by sector.
5. Click a row → side drawer opens with:
   - Key metrics card: P/E, P/B, ROE, D/E, FCF, Revenue CAGR, Market Cap.
   - Sub-score breakdown: horizontal bar per component with numeric value.
   - "Run Full Analysis" button → triggers existing LLM hedge fund pipeline for this ticker.
6. "Run Screener" button in toolbar → triggers a fresh run with SSE progress stream.

### Flow 2 — Custom ticker (secondary)

1. User types any ticker in the custom search box (e.g., `SGFIN.NS`).
2. On-demand deterministic scoring runs (~5 seconds, no LLM).
3. Result appears as a score card below the search box using the same layout as the main table.
4. "Run Full Analysis" button available.

### Flow 3 — Historical comparison

1. History dropdown in toolbar shows last 30 daily runs.
2. Selecting a past date repopulates the main table with that day's scores.
3. Score delta vs previous day shown in a small +/- badge on the composite column.

---

## Architecture

### New backend files

```
src/screener/
├── __init__.py
├── constituents.py       # Nifty 500 fetch with fallback chain; returns list[dict]
├── holidays.py           # NSE trading holiday list 2026 (static dict)
├── nifty500_static.py    # Hardcoded fallback list of 500 tickers
├── scorer.py             # 5 pure scoring functions (no state, no LangGraph, no LLM)
├── composite.py          # Weighted combination → 0-100 score
└── run_screener.py       # Orchestrator: accepts tickers list, yields ScreenerResult per ticker

app/backend/routes/
└── screener.py           # New FastAPI router (registered in app/backend/main.py)

app/backend/database/
└── models.py             # Two new tables added (do NOT replace existing tables)
```

### New DB tables (append to models.py)

**`NiftyConstituent`**

| Column | Type | Notes |
|---|---|---|
| id | Integer PK | |
| symbol | String(20) | NSE symbol e.g. "RELIANCE" |
| ticker | String(20) | yfinance ticker e.g. "RELIANCE.NS" |
| company_name | String(200) | |
| industry | String(100) | |
| isin | String(20) | |
| is_active | Boolean | false = removed from index |
| added_at | DateTime | when first seen in constituent list |
| removed_at | DateTime | when removed; null if still active |
| last_refreshed | DateTime | when this record was last updated |

**`ScreenerRun`**

| Column | Type | Notes |
|---|---|---|
| id | Integer PK | |
| run_at | DateTime(IST) | |
| universe | String(50) | "nifty500" or "custom" |
| threshold_mode | String(20) | "top25", "top5pct", "score60" |
| stocks_screened | Integer | |
| shortlisted_count | Integer | |
| duration_seconds | Float | |
| status | String(20) | "IN_PROGRESS", "COMPLETE", "ERROR" |
| source | String(20) | "manual", "backfill" |
| error_message | Text | null if OK |

**`ScreenerResult`**

| Column | Type | Notes |
|---|---|---|
| id | Integer PK | |
| run_id | Integer FK → ScreenerRun | |
| ticker | String(20) | |
| company_name | String(200) | |
| industry | String(100) | |
| rank | Integer | 1 = best |
| composite_score | Float | 0–100 |
| valuation_score | Float | 0–100 |
| fundamentals_score | Float | 0–100 |
| jhunjhunwala_score | Float | 0–100 |
| growth_score | Float | 0–100 |
| insider_score | Float | 0–100 |
| is_shortlisted | Boolean | |
| key_metrics | JSON | P/E, P/B, ROE, D/E, FCF, Rev CAGR, Mkt Cap |
| scored_at | DateTime | |
| error | Text | null if scored OK; error msg if skipped |

### New API endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/screener/runs` | List past runs (id, date, status, shortlisted_count) |
| `POST` | `/screener/run` | Trigger manual run — SSE stream of progress events |
| `GET` | `/screener/runs/{id}/results` | Full ranked table for one run |
| `GET` | `/screener/runs/{id}/results/{ticker}` | Detail for one stock in one run |
| `POST` | `/screener/ticker` | On-demand score for a custom ticker |
| `GET` | `/screener/constituents` | Current Nifty 500 list (from DB) |
| `POST` | `/screener/constituents/refresh` | Trigger monthly constituent refresh |

SSE event shape for `/screener/run` (mirrors `/hedge-fund/run` pattern):
```json
{ "type": "progress", "ticker": "RELIANCE.NS", "done": 47, "total": 500, "score": 72.4 }
{ "type": "complete", "run_id": 12, "shortlisted": 25, "duration_seconds": 387 }
{ "type": "error", "message": "..." }
```

### New frontend components

```
app/frontend/src/components/screener/
├── ScreenerPage.tsx          # Top-level; integrates into existing tab system
├── ScreenerToolbar.tsx       # Run button, history dropdown, threshold toggle, refresh constituents
├── ScreenerShortlist.tsx     # Highlighted card band at the top (shortlisted stocks)
├── ScreenerRankTable.tsx     # Full sortable/filterable table of all 500 stocks
├── ScreenerStockDetail.tsx   # Side drawer: key metrics + sub-score bars + Run Full Analysis
├── ScreenerScoreBar.tsx      # Reusable coloured bar component (0-100 with band colours)
├── ScreenerRunProgress.tsx   # SSE progress display during active run
└── CustomTickerSearch.tsx    # Input + on-demand run for tickers not in Nifty 500
```

The Screener tab is registered in the existing `TabService` alongside the flow editor tab.
No layout changes. No new routes — uses the existing tab system.

---

## Scoring Function Contracts (for architect / engineer reference)

Each function in `scorer.py` is a **pure function**: accepts yfinance data structs, returns a
float 0–100. No side effects. No network calls. No LangGraph state.

```python
def score_valuation(ticker_data: dict) -> float:
    """
    Blended: 60% DCF margin of safety + 40% Graham Number margin of safety.
    MoS > 50% → 100. MoS 0% → 50. Premium > 50% → 0. Linear interpolation.
    """

def score_fundamentals(ticker_data: dict) -> float:
    """
    Extracted from fundamentals_analyst sub-scores:
    profitability_score (0-3) + growth_score (0-3) + health_score (0-3) → normalised 0-100.
    """

def score_jhunjhunwala(ticker_data: dict) -> float:
    """
    Calls analyze_rakesh_jhunjhunwala_style() directly; total_score 0-24 → 0-100.
    """

def score_growth(ticker_data: dict) -> float:
    """
    Revenue CAGR (2yr) + Earnings CAGR (2yr) + quarter-on-quarter consistency.
    Normalised 0-100; negative CAGR → < 50; CAGR > 30% → capped at 100.
    """

def score_insider(ticker_data: dict) -> float:
    """
    Extracted from sentiment_analyst logic: insider_buys / (insider_buys + insider_sells).
    No trades → 50 (neutral). All buys → 100. All sells → 0.
    """
```

---

## LLM Budget After This Feature

| Activity | LLM calls/day |
|---|---|
| Screener — full Nifty 500 | **0** |
| Full deep analysis on shortlisted top 25 | ~325 (13 calls × 25 stocks) |
| Remaining daily quota (Gemini free tier 1,500/day) | **1,175 spare** |

Reduction: from potentially exhausting 100% of quota to using 22%.

---

## Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-0101 | Screener runs on all 500 Nifty stocks with 0 LLM calls |
| AC-0102 | Composite score 0–100 computed from 5 weighted sub-scores (30/25/20/15/10) |
| AC-0103 | Constituent list fetched via nselib URL pattern; falls back to direct HTTP; then hardcoded |
| AC-0104 | "Refresh Nifty 500 List" UI button triggers constituent refresh and logs additions/removals |
| AC-0105 | "Run Screener" button triggers a fresh run with SSE progress stream |
| AC-0106 | Results persisted in ScreenerRun + ScreenerResult tables |
| AC-0107 | UI shows full ranked table of all 500 stocks with composite + 5 sub-score columns |
| AC-0108 | Table is sortable by any column and filterable by industry/sector |
| AC-0109 | Shortlist highlighted; threshold mode switchable among 3 options without re-running |
| AC-0110 | Clicking a stock opens detail drawer with key metrics + sub-score bars |
| AC-0111 | "Run Full Analysis" in drawer triggers existing LLM pipeline for that ticker |
| AC-0112 | Custom ticker input runs on-demand deterministic score for any .NS / .BO ticker |
| AC-0113 | History dropdown shows last 30 runs; selecting one repopulates the table |
| AC-0114 | Score delta vs prior day shown as +/- badge on composite column |
| AC-0115 | On first deploy, screener backfills last 7 calendar days (skipping weekends + NSE holidays) |
| AC-0116 | Full Nifty 500 run completes in under 10 minutes |
| AC-0117 | Stocks that fail to score (yfinance error) are logged with error field; run continues |

---

## Out of Scope

- No LLM calls in the screener path — ever.
- Technical analyst sub-score excluded from composite (not relevant for long-term).
- News sentiment excluded (LLM-dependent, no deterministic substitute).
- APScheduler automatic daily trigger (deferred; manual button for now).
- Backtesting the screener score itself (future feature).
- Nifty 50 / BSE 500 / custom index universe (future feature).
- Mobile UI (future feature).

---

## Recommended Build Order (for engineer)

1. `src/screener/constituents.py` — get Nifty 500 list working, test fallback chain.
2. `src/screener/scorer.py` — 5 pure scoring functions with unit tests; no DB or API needed.
3. `src/screener/composite.py` + `run_screener.py` — orchestrator, tested on 10 stocks.
4. DB migration — add 3 new tables; existing tables untouched.
5. `app/backend/routes/screener.py` — API endpoints + SSE streaming.
6. Frontend — ScreenerPage + table + toolbar (static mock data first, then wire to API).
7. Drawer detail + Run Full Analysis wiring.
8. Backfill script (one-shot, run post-deploy).
9. Constituent refresh UI + endpoint.

Each step produces a independently testable deliverable. Do not start step N+1 before step N
passes its gate check (unit tests green, no regressions in existing hedge fund flow).
