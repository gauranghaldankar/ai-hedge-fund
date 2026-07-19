# Screener — Technical Architecture

**Status:** Ready for Engineering
**Author:** Architect (AgentCo)
**Date:** 2026-07-20
**Input:** `docs/spec/screener-prd.md`

---

## 1. Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│  FRONTEND  (React + shadcn/ui)                                   │
│                                                                  │
│  ScreenerPage                                                    │
│  ├── ScreenerToolbar  (run btn, history dropdown, threshold)     │
│  ├── ScreenerShortlist  (highlighted top band)                   │
│  ├── ScreenerRankTable  (full sortable 500-row table)            │
│  │   └── ScreenerStockDetail  (side drawer on row click)         │
│  │       └── "Run Full Analysis" → existing hedge-fund pipeline  │
│  ├── ScreenerRunProgress  (SSE live progress bar)                │
│  └── CustomTickerSearch  (on-demand single ticker)               │
└────────────────────────────┬─────────────────────────────────────┘
                             │ HTTP / SSE
┌────────────────────────────▼─────────────────────────────────────┐
│  BACKEND API   app/backend/routes/screener.py                    │
│                                                                  │
│  POST /screener/run           → SSE stream, persists ScreenerRun │
│  GET  /screener/runs          → list past runs                   │
│  GET  /screener/runs/{id}/results → full ranked table            │
│  GET  /screener/runs/{id}/results/{ticker} → one stock detail    │
│  POST /screener/ticker        → on-demand single ticker score    │
│  GET  /screener/constituents  → current Nifty 500 list from DB   │
│  POST /screener/constituents/refresh → trigger monthly refresh   │
└──────┬─────────────────────────┬────────────────────────────────┘
       │                         │
       ▼                         ▼
┌─────────────┐     ┌────────────────────────────────────────────┐
│constituents │     │  src/screener/run_screener.py              │
│.py          │     │  Orchestrator — no LLM, no LangGraph       │
│             │     │  1. Load tickers from DB                   │
│ nselib URL  │     │  2. ThreadPoolExecutor(max_workers=10)     │
│ → HTTP GET  │     │  3. Per ticker: fetch data → score → yield │
│ → hardcoded │     │  4. Persist ScreenerRun + ScreenerResults  │
└─────────────┘     └───────────────┬────────────────────────────┘
                                    │
                          ┌─────────▼──────────┐
                          │  src/screener/      │
                          │  scorer.py          │
                          │                     │
                          │  score_valuation()  │
                          │  score_fundamentals │
                          │  score_jhunjhunwala │
                          │  score_growth()     │
                          │  score_insider()    │
                          └─────────┬───────────┘
                                    │
                          ┌─────────▼──────────┐
                          │  composite.py       │
                          │  30/25/20/15/10     │
                          │  → 0-100 float      │
                          └─────────┬───────────┘
                                    │
                    ┌───────────────▼──────────────┐
                    │  Existing data layer          │
                    │  src/tools/api.py             │
                    │  get_financial_metrics()      │
                    │  search_line_items()          │
                    │  get_market_cap()             │
                    │  get_insider_trades()         │
                    │  (auto-routes to yf_api.py    │
                    │   for .NS tickers)            │
                    └──────────────────────────────┘
```

---

## 2. New File Tree (additions only)

```
src/screener/
├── __init__.py
├── constituents.py       # Nifty 500 fetch with fallback chain
├── holidays.py           # NSE 2026 trading holidays (static dict)
├── nifty500_static.py    # Hardcoded fallback list (500 tickers)
├── scorer.py             # 5 pure scoring functions
├── composite.py          # Weighted combination → 0-100
└── run_screener.py       # Orchestrator

app/backend/routes/
└── screener.py           # FastAPI router — registered in routes/__init__.py

app/backend/database/
└── models.py             # APPEND two new ORM classes (no existing code touched)

app/frontend/src/components/screener/
├── ScreenerPage.tsx
├── ScreenerToolbar.tsx
├── ScreenerShortlist.tsx
├── ScreenerRankTable.tsx
├── ScreenerStockDetail.tsx
├── ScreenerScoreBar.tsx
├── ScreenerRunProgress.tsx
└── CustomTickerSearch.tsx
```

**Existing files modified (minimal surgery):**

| File | Change |
|---|---|
| `app/backend/routes/__init__.py` | Import and register `screener_router` |
| `app/backend/database/models.py` | Append `NiftyConstituent`, `ScreenerRun`, `ScreenerResult` classes |
| `app/frontend/src/services/tab-service.ts` | Add `createScreenerTab()` factory |
| `app/frontend/src/components/tabs/tab-content.tsx` | Add `case "screener"` render branch |
| `app/frontend/src/components/layout/top-bar.tsx` | Add "Screener" button in toolbar |

---

## 3. Database Schema

No Alembic — project uses `Base.metadata.create_all(bind=engine)` on startup.
Append the three classes below to `app/backend/database/models.py`.

```python
class NiftyConstituent(Base):
    __tablename__ = "nifty_constituents"

    id           = Column(Integer, primary_key=True, index=True)
    symbol       = Column(String(20), nullable=False, unique=True, index=True)  # "RELIANCE"
    ticker       = Column(String(20), nullable=False)                           # "RELIANCE.NS"
    company_name = Column(String(200), nullable=False)
    industry     = Column(String(100), nullable=True)
    isin         = Column(String(20), nullable=True)
    is_active    = Column(Boolean, default=True)
    added_at     = Column(DateTime(timezone=True), server_default=func.now())
    removed_at   = Column(DateTime(timezone=True), nullable=True)
    last_refreshed = Column(DateTime(timezone=True), nullable=True)


class ScreenerRun(Base):
    __tablename__ = "screener_runs"

    id               = Column(Integer, primary_key=True, index=True)
    run_at           = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    universe         = Column(String(50), default="nifty500")  # "nifty500" | "custom"
    threshold_mode   = Column(String(20), default="top25")     # "top25" | "top5pct" | "score60"
    stocks_screened  = Column(Integer, nullable=True)
    shortlisted_count = Column(Integer, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    status           = Column(String(20), default="IN_PROGRESS")  # IN_PROGRESS | COMPLETE | ERROR
    source           = Column(String(20), default="manual")        # "manual" | "backfill"
    error_message    = Column(Text, nullable=True)


class ScreenerResult(Base):
    __tablename__ = "screener_results"

    id                  = Column(Integer, primary_key=True, index=True)
    run_id              = Column(Integer, ForeignKey("screener_runs.id"), nullable=False, index=True)
    ticker              = Column(String(20), nullable=False, index=True)
    company_name        = Column(String(200), nullable=True)
    industry            = Column(String(100), nullable=True)
    rank                = Column(Integer, nullable=True)
    composite_score     = Column(Float, nullable=True)
    valuation_score     = Column(Float, nullable=True)
    fundamentals_score  = Column(Float, nullable=True)
    jhunjhunwala_score  = Column(Float, nullable=True)
    growth_score        = Column(Float, nullable=True)
    insider_score       = Column(Float, nullable=True)
    is_shortlisted      = Column(Boolean, default=False)
    key_metrics         = Column(JSON, nullable=True)  # P/E, P/B, ROE, D/E, FCF, Rev CAGR, Mkt Cap
    scored_at           = Column(DateTime(timezone=True), nullable=True)
    error               = Column(Text, nullable=True)  # null = OK; message = skipped with reason
```

---

## 4. `src/screener/constituents.py` — Interface

```python
def fetch_nifty500() -> list[dict]:
    """
    Returns list of dicts: {symbol, ticker, company_name, industry, isin}
    Fallback chain:
      1. nselib nse_urlfetch("https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv")
      2. requests.get same URL with User-Agent header
      3. load_static_list()  (from nifty500_static.py)
    Raises RuntimeError only if all three fail.
    """

def load_static_list() -> list[dict]:
    """Returns the hardcoded 500-ticker list from nifty500_static.py."""

def sync_constituents_to_db(db: Session) -> dict:
    """
    Fetch fresh list, diff against NiftyConstituent table.
    Returns {"added": [...], "removed": [...], "unchanged": int}
    Marks removed tickers as is_active=False with removed_at timestamp.
    """

def get_active_tickers_from_db(db: Session) -> list[str]:
    """Returns list of ticker strings for all is_active=True constituents."""
```

---

## 5. `src/screener/scorer.py` — Interface & Implementation Strategy

### Data bundle per ticker

The orchestrator fetches all data once per ticker and passes a single `TickerData` dict to all scoring functions. This avoids redundant network calls.

```python
@dataclass
class TickerData:
    ticker: str
    financial_metrics: list       # from get_financial_metrics(..., limit=12)
    line_items: list              # from search_line_items([...])
    market_cap: float | None      # from get_market_cap()
    insider_trades: list          # from get_insider_trades(..., limit=1000)
    end_date: str                 # ISO date string
```

### Line items to fetch per ticker

```python
SCREENER_LINE_ITEMS = [
    "net_income", "earnings_per_share", "revenue",
    "operating_income", "ebit", "operating_margin",
    "total_assets", "total_liabilities",
    "current_assets", "current_liabilities",
    "free_cash_flow", "capital_expenditure",
    "depreciation_and_amortization",
    "dividends_and_other_cash_distributions",
    "issuance_or_purchase_of_equity_shares",
    "total_debt", "cash_and_equivalents",
    "working_capital",
]
```

### Scoring functions — implementation strategy

**Key decision: import standalone helpers directly from agent files.**
The helper functions in agent files are pure Python math (no network, no state, no LangGraph calls).
Importing them causes agent-file top-level imports to execute (LangChain etc.) but causes no side effects.
This eliminates code duplication and ensures screener scores match agent scores exactly.

```python
# scorer.py imports

# From rakesh_jhunjhunwala.py — all standalone functions
from src.agents.rakesh_jhunjhunwala import (
    analyze_profitability,          # → {score 0-8}
    analyze_growth,                 # → {score 0-7}
    analyze_balance_sheet,          # → {score 0-4}
    analyze_cash_flow,              # → {score 0-3}
    analyze_management_actions,     # → {score 0-2}
    calculate_intrinsic_value as rj_intrinsic_value,  # → float
)

# From valuation.py — all standalone functions
from src.agents.valuation import (
    calculate_owner_earnings_value,
    calculate_intrinsic_value as dcf_intrinsic_value,
    calculate_ev_ebitda_value,
    calculate_residual_income_value,
    calculate_wacc,
    calculate_dcf_scenarios,
)

# From growth_agent.py — all standalone functions
from src.agents.growth_agent import (
    analyze_growth_trends,      # → {score 0-1}
    analyze_margin_trends,      # → {score 0-1}
    analyze_insider_conviction, # → {score 0-1}
    check_financial_health,     # → {score 0-1}
)
```

### Function signatures

```python
def score_valuation(data: TickerData) -> float:
    """
    Replicates valuation_analyst deterministic path (no LLM).
    Runs 4 valuation models: DCF scenarios, owner earnings, EV/EBITDA, residual income.
    weighted_gap = weighted average of (intrinsic_value - market_cap) / market_cap across models.
    Normalise: gap +50%+ → 100, gap 0% → 50, gap -50%- → 0. Linear clamp to [0, 100].
    Returns 0.0 if insufficient data.
    """

def score_fundamentals(data: TickerData) -> float:
    """
    Reimplements fundamentals_analyst inline logic (30 lines of thresholds).
    profitability_score (0-3) + growth_score (0-3) + health_score (0-3) + price_ratio_score (0-3).
    Normalise total (0-12) → 0-100. Price ratios invert (high = bad).
    """

def score_jhunjhunwala(data: TickerData) -> float:
    """
    Calls analyze_profitability + analyze_growth + analyze_balance_sheet +
    analyze_cash_flow + analyze_management_actions from rakesh_jhunjhunwala.py.
    total_score 0-24 → (total_score / 24) * 100.
    """

def score_growth(data: TickerData) -> float:
    """
    Calls analyze_growth_trends + analyze_margin_trends from growth_agent.py.
    Both return score 0-1. Blend: 0.6 * growth + 0.4 * margins → * 100.
    """

def score_insider(data: TickerData) -> float:
    """
    Calls analyze_insider_conviction from growth_agent.py (score 0-1 → * 100).
    No trades → 50.0 (neutral, not 0 — absence of data ≠ bad signal).
    """
```

---

## 6. `src/screener/composite.py` — Interface

```python
WEIGHTS = {
    "valuation":     0.30,
    "fundamentals":  0.25,
    "jhunjhunwala":  0.20,
    "growth":        0.15,
    "insider":       0.10,
}

def compute_composite(
    valuation: float,
    fundamentals: float,
    jhunjhunwala: float,
    growth: float,
    insider: float,
) -> float:
    """Weighted average. All inputs 0-100. Returns 0-100 float, rounded to 2dp."""

def apply_threshold(
    results: list[ScreenerResult],
    mode: Literal["top25", "top5pct", "score60"],
) -> list[ScreenerResult]:
    """
    Marks result.is_shortlisted=True for qualifying rows.
    top25:    top 25 by composite_score
    top5pct:  top ceil(len(results) * 0.05) by composite_score
    score60:  all results where composite_score >= 60.0
    Returns results list with is_shortlisted set (does not mutate DB).
    """
```

---

## 7. `src/screener/run_screener.py` — Orchestrator

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

MAX_WORKERS = 10  # Conservative; yfinance rate limit tolerance

def score_one_ticker(ticker: str, end_date: str) -> dict:
    """
    Runs for a single ticker in a thread worker.
    Returns a dict with all 5 sub-scores, composite, key_metrics, and error field.
    Never raises — catches all exceptions and returns error field instead.
    """

def run_screener(
    tickers: list[str],
    end_date: str,
    threshold_mode: str,
    db: Session,
    progress_callback: Callable[[int, int, str, float | None], None] | None = None,
) -> int:
    """
    Main entry point. Returns the run_id of the persisted ScreenerRun.

    Steps:
    1. Insert ScreenerRun(status="IN_PROGRESS") → get run_id.
    2. ThreadPoolExecutor: submit score_one_ticker for each ticker.
    3. As futures complete: insert ScreenerResult, call progress_callback(done, total, ticker, score).
    4. After all complete: rank results by composite DESC, set rank + is_shortlisted via apply_threshold.
    5. Update ScreenerRun(status="COMPLETE", stocks_screened, shortlisted_count, duration_seconds).
    6. Return run_id.
    """

def run_backfill(db: Session, days: int = 7) -> list[int]:
    """
    Computes the last `days` trading days (skip weekends + NSE holidays from holidays.py).
    For each date: calls run_screener with that date as end_date.
    Returns list of run_ids created.
    Note: uses the same fundamentals data as today (yfinance doesn't have true
    point-in-time financials); uses historical price from yfinance for that date.
    This is documented as a known approximation in the UI.
    """
```

---

## 8. `app/backend/routes/screener.py` — API

```python
router = APIRouter(prefix="/screener")

# ── SSE run endpoint ─────────────────────────────────────────────────────────

@router.post("/run")
async def trigger_run(
    request: ScreenerRunRequest,   # {threshold_mode: str}
    db: Session = Depends(get_db)
) -> StreamingResponse:
    """
    Streams SSE events while screener runs.
    Runs screener in a background thread (run_in_executor) so FastAPI stays async.

    SSE event types:
      data: {"type": "progress", "done": 47, "total": 500, "ticker": "RELIANCE.NS", "score": 72.4}
      data: {"type": "complete", "run_id": 12, "shortlisted": 25, "duration_seconds": 387.2}
      data: {"type": "error", "message": "..."}
    """

# ── Constituent endpoints ─────────────────────────────────────────────────────

@router.get("/constituents")
def get_constituents(db: Session = Depends(get_db)) -> list[ConstituentResponse]:
    """Returns current active Nifty 500 list from DB."""

@router.post("/constituents/refresh")
def refresh_constituents(db: Session = Depends(get_db)) -> ConstituentRefreshResponse:
    """
    Synchronously fetches fresh constituent list and diffs against DB.
    Returns {"added": [...], "removed": [...], "unchanged": int, "refreshed_at": datetime}
    """

# ── Run history & results ─────────────────────────────────────────────────────

@router.get("/runs")
def list_runs(limit: int = 30, db: Session = Depends(get_db)) -> list[ScreenerRunSummary]:
    """Returns last `limit` runs ordered by run_at DESC."""

@router.get("/runs/{run_id}/results")
def get_results(
    run_id: int,
    sort_by: str = "composite_score",
    sort_dir: str = "desc",
    industry: str | None = None,
    db: Session = Depends(get_db)
) -> list[ScreenerResultResponse]:
    """Full ranked table for one run. Optional filter by industry."""

@router.get("/runs/{run_id}/results/{ticker}")
def get_result_detail(
    run_id: int,
    ticker: str,
    db: Session = Depends(get_db)
) -> ScreenerResultDetail:
    """Single stock detail including key_metrics breakdown."""

# ── On-demand single ticker ───────────────────────────────────────────────────

@router.post("/ticker")
def score_custom_ticker(
    request: CustomTickerRequest,  # {ticker: str}
    db: Session = Depends(get_db)
) -> ScreenerResultResponse:
    """
    Synchronous (no SSE). Scores a single ticker on-demand.
    Creates a ScreenerRun with universe="custom", persists one ScreenerResult.
    Returns the result immediately (~5 seconds).
    """
```

### Pydantic request/response schemas (in `app/backend/models/schemas.py`)

```python
class ScreenerRunRequest(BaseModel):
    threshold_mode: Literal["top25", "top5pct", "score60"] = "top25"

class CustomTickerRequest(BaseModel):
    ticker: str  # e.g. "SGFIN.NS" or "RELIANCE.NS"

class ConstituentResponse(BaseModel):
    symbol: str
    ticker: str
    company_name: str
    industry: str | None
    isin: str | None

class ConstituentRefreshResponse(BaseModel):
    added: list[str]
    removed: list[str]
    unchanged: int
    refreshed_at: datetime

class ScreenerRunSummary(BaseModel):
    id: int
    run_at: datetime
    universe: str
    threshold_mode: str
    stocks_screened: int | None
    shortlisted_count: int | None
    duration_seconds: float | None
    status: str
    source: str

class ScreenerResultResponse(BaseModel):
    ticker: str
    company_name: str | None
    industry: str | None
    rank: int | None
    composite_score: float | None
    valuation_score: float | None
    fundamentals_score: float | None
    jhunjhunwala_score: float | None
    growth_score: float | None
    insider_score: float | None
    is_shortlisted: bool
    error: str | None

class ScreenerResultDetail(ScreenerResultResponse):
    key_metrics: dict | None  # P/E, P/B, ROE, D/E, FCF, Rev CAGR, Mkt Cap

class ScreenerRunSummaryWithDelta(ScreenerResultResponse):
    composite_delta: float | None  # diff vs previous day's score for same ticker
```

---

## 9. SSE Concurrency Model

FastAPI is async but yfinance calls are synchronous/blocking. Pattern:

```python
# In route handler
async def generate():
    loop = asyncio.get_event_loop()
    queue = asyncio.Queue()

    def run_in_thread():
        def on_progress(done, total, ticker, score):
            loop.call_soon_threadsafe(queue.put_nowait, {
                "type": "progress", "done": done,
                "total": total, "ticker": ticker, "score": score
            })
        run_screener(tickers, end_date, threshold_mode, db, on_progress)
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "done"})

    executor = ThreadPoolExecutor(max_workers=1)
    loop.run_in_executor(executor, run_in_thread)

    while True:
        event = await queue.get()
        if event["type"] == "done":
            break
        yield f"data: {json.dumps(event)}\n\n"
```

This is the same pattern `hedge_fund.py` already uses for SSE. No new pattern introduced.

---

## 10. Frontend Architecture

### Tab integration (minimal change)

The existing tab system is type-driven. Two files change:

**`tab-service.ts`** — add one factory:
```typescript
static createScreenerTab(): TabData {
  return { id: "screener", type: "screener", title: "Screener", closeable: false };
}
```

**`tab-content.tsx`** — add one case in the switch:
```typescript
case "screener":
  return <ScreenerPage />;
```

**`top-bar.tsx`** — add one button that calls `openTab(TabService.createScreenerTab())`.

### Component data flow

```
ScreenerPage
├── state: currentRunId, results[], thresholdMode, historyRuns[]
│
├── ScreenerToolbar
│   ├── props: thresholdMode, onThresholdChange, onRunNow, historyRuns, onHistorySelect
│   └── fires: POST /screener/run (SSE) | GET /screener/runs
│
├── ScreenerRunProgress   (visible only during active run)
│   ├── props: done, total, currentTicker, latestScore
│   └── consumes SSE stream from POST /screener/run
│
├── ScreenerShortlist
│   ├── props: results.filter(r => r.is_shortlisted)
│   └── renders: compact card grid of shortlisted stocks
│
└── ScreenerRankTable
    ├── props: results[], thresholdMode
    ├── state: sortColumn, sortDir, industryFilter, selectedTicker
    ├── renders: shadcn Table, sortable columns, industry filter dropdown
    └── on row click → ScreenerStockDetail (Sheet drawer)
        ├── props: result (ScreenerResultDetail from GET /screener/runs/{id}/results/{ticker})
        ├── ScreenerScoreBar × 5 sub-scores
        ├── key_metrics table
        └── "Run Full Analysis" button → opens existing hedge fund flow with this ticker
```

### API client (new file: `src/services/screener-service.ts`)

Follows same pattern as existing API calls in the codebase:

```typescript
export const ScreenerService = {
  triggerRun: (thresholdMode: string): EventSource => { /* SSE */ },
  listRuns: (): Promise<ScreenerRunSummary[]> => { /* GET /screener/runs */ },
  getResults: (runId: number, filters?: ResultFilters): Promise<ScreenerResultResponse[]> => {},
  getResultDetail: (runId: number, ticker: string): Promise<ScreenerResultDetail> => {},
  scoreTicker: (ticker: string): Promise<ScreenerResultResponse> => {},
  getConstituents: (): Promise<ConstituentResponse[]> => {},
  refreshConstituents: (): Promise<ConstituentRefreshResponse> => {},
};
```

---

## 11. `src/screener/holidays.py` — NSE 2026 Holidays

```python
# NSE trading holidays 2026 (dates when NSE is closed)
NSE_HOLIDAYS_2026: set[str] = {
    "2026-01-26",  # Republic Day
    "2026-02-19",  # Chhatrapati Shivaji Maharaj Jayanti
    "2026-03-20",  # Holi
    "2026-04-02",  # Shri Ram Navami
    "2026-04-03",  # Good Friday
    "2026-04-14",  # Dr. Ambedkar Jayanti
    "2026-05-01",  # Maharashtra Day
    "2026-06-05",  # Id-Ul-Adha (Bakri Id)
    "2026-07-20",  # Muharram  ← today; if market is closed, backfill skips today
    "2026-08-15",  # Independence Day
    "2026-08-27",  # Ganesh Chaturthi
    "2026-10-02",  # Mahatma Gandhi Jayanti / Dussehra
    "2026-10-22",  # Diwali Laxmi Pujan
    "2026-10-23",  # Diwali Balipratipada
    "2026-11-04",  # Gurunanak Jayanti
    "2026-12-25",  # Christmas
}

def is_trading_day(date_str: str) -> bool:
    """Returns True if date is a weekday and not an NSE holiday."""
    from datetime import datetime
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    if dt.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    return date_str not in NSE_HOLIDAYS_2026
```

---

## 12. Backfill Strategy

On first deploy, call `run_backfill(db, days=7)` from a one-shot startup hook
or a manual API endpoint `POST /screener/backfill` (admin-only, no UI button needed).

```python
# In app/backend/main.py startup_event — guarded so it only runs once:
@app.on_event("startup")
async def startup_event():
    db = next(get_db())
    run_count = db.query(ScreenerRun).count()
    if run_count == 0:
        # First ever run — trigger backfill in background thread
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, lambda: run_backfill(db, days=7))
    ...
```

**Known limitation (documented in UI tooltip):**
yfinance does not offer true point-in-time financial statements. The backfill uses today's
fundamentals data but historical prices for each past date. This means scores for 7 days
ago reflect current fundamentals at historical prices — acceptable for trend analysis but
not a rigorous backtest.

---

## 13. `key_metrics` JSON shape

Stored in `ScreenerResult.key_metrics` column:

```json
{
  "pe_ratio": 23.5,
  "pb_ratio": 2.8,
  "roe": 0.105,
  "debt_to_equity": 1.85,
  "free_cash_flow": -15700000000,
  "revenue_cagr_2y": 0.64,
  "market_cap": 41590000000,
  "current_ratio": 1.35,
  "net_margin": 0.39,
  "operating_margin": 0.92
}
```

---

## 14. Build Order for Engineering

Follow this order. Each step is independently testable before proceeding.

| Step | Deliverable | Test signal |
|---|---|---|
| 1 | `constituents.py` | `fetch_nifty500()` returns 500-item list; fallback chain verified manually |
| 2 | `nifty500_static.py` | Hardcoded list has 500 entries with `.NS` tickers |
| 3 | `holidays.py` + `is_trading_day()` | Unit tests: weekend returns False, holiday returns False, normal trading day returns True |
| 4 | `scorer.py` — 5 functions | Unit tests using SGFIN.NS fixture data from previous run |
| 5 | `composite.py` | Unit tests: weights sum to 1.0, score clamps to [0,100], threshold modes correct |
| 6 | `run_screener.py` | Integration test on 5 tickers; assert ScreenerRun + 5 ScreenerResults in DB |
| 7 | DB model additions | Tables created on `Base.metadata.create_all`; verify with sqlite3 inspect |
| 8 | `routes/screener.py` + schema | API endpoints testable via curl / FastAPI /docs |
| 9 | Frontend static shell | ScreenerPage renders with hardcoded mock data (no API wired) |
| 10 | Frontend SSE wiring | Progress bar updates during live run |
| 11 | Table + drawer | Sort, filter, drill-down working |
| 12 | Backfill | `run_backfill(db, 7)` creates 7 ScreenerRun records; history dropdown shows them |
| 13 | Constituent refresh | UI button triggers refresh; added/removed logged |

**Do not skip steps.** Step 4 (scorer) is the core; all later steps depend on it being correct.
Run `poetry run pytest src/screener/tests/` after each step before moving on.

---

## 15. Risk Register

| Risk | Likelihood | Mitigation |
|---|---|---|
| yfinance rate-limiting on 500 stocks | Medium | `MAX_WORKERS=10`; exponential backoff in `score_one_ticker`; stocks that fail get `error` field, run continues |
| NSE archives URL changes/blocks nselib | Low | Fallback to direct requests.get; final fallback to hardcoded list |
| Agent helper function signature changes | Low | Pin imports by function name; scorer tests will catch regressions immediately |
| SQLite contention during backfill + live use | Low | SQLite WAL mode; screener writes happen in background thread; reads from UI are fast |
| First backfill takes >10 min (7 days × 500 stocks) | Medium | Backfill runs in background; UI shows "Backfill in progress" banner; does not block normal use |
