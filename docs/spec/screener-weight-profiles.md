# Screener Weight Profiles + Technical Score
## AgentCo Pipeline Document

**Feature:** Goal-based weight profiles (Short-term / Medium-long / Custom) + Technical sub-score
**Date:** 2026-07-20
**Builds on:** `screener-prd.md`, `screener-architecture.md`

---

## Answering the Core Question First

> "Does it need reevaluation or will the weights just rebalance and show the result?"

**Just rebalance. No re-run. No re-fetch. No re-score.**

The 6 sub-scores are **facts** about a stock at a point in time. The composite is a **weighted view** of those facts. These two concepts must stay separate:

```
FACT (stored once in DB)         VIEW (computed on demand)
────────────────────────         ──────────────────────────
valuation_score  = 72.4          composite = Σ(score_i × weight_i)
fundamentals_score = 58.1            using whichever profile is active
jhunjhunwala_score = 81.0
growth_score = 44.5
insider_score = 90.0
technical_score = 61.3
```

The screener run computes and stores all 6 scores **once**. Switching from
medium-long to short-term is O(500) arithmetic in the browser — takes <1ms,
no API call, no spinner, no waiting.

---

## Stage 1 — PM: Acceptance Criteria

### Feature: Technical Sub-Score (AC-02xx series)

| ID | Criterion |
|---|---|
| AC-0201 | `technical_score` (0–100 float) computed and stored during every screener run |
| AC-0202 | Technical score derives from the 5 existing standalone functions in `technicals.py`: `calculate_trend_signals`, `calculate_mean_reversion_signals`, `calculate_momentum_signals`, `calculate_volatility_signals`, `calculate_stat_arb_signals`, combined via `weighted_signal_combination` |
| AC-0203 | Signal-to-score mapping: bullish → `50 + (confidence × 50)`, bearish → `50 − (confidence × 50)`, neutral → `50.0` |
| AC-0204 | Technical score uses price history from `end_date − 365 days` to `end_date` (same window as existing technical analyst agent) |
| AC-0205 | Stocks with insufficient price history (<60 trading days) receive `technical_score = None`; run continues |
| AC-0206 | `technical_score` column added to `ScreenerResult` table; existing rows from prior runs display as `null` / grey in UI |

### Feature: Weight Profiles (AC-03xx series)

| ID | Criterion |
|---|---|
| AC-0301 | Three named profiles available: **Short-term**, **Medium-to-long term**, **Custom** |
| AC-0302 | Short-term default weights: Technical 35%, Fundamentals 20%, Valuation 15%, Growth 15%, Insider 10%, Jhunjhunwala 5% |
| AC-0303 | Medium-to-long term weights (existing): Valuation 30%, Fundamentals 25%, Jhunjhunwala 20%, Growth 15%, Insider 10%, Technical 0% |
| AC-0304 | Custom profile: user sets 6 sliders; weights are enforced to sum to exactly 100% (auto-normalised as sliders are dragged) |
| AC-0305 | Custom profile weights persisted in browser `localStorage`; survive page refresh |
| AC-0306 | Switching profiles re-ranks the full table **instantly** with no API call and no loading state |
| AC-0307 | Each column header shows the sub-score name **and** its current weight % in the active profile (e.g. "Valuation 30%") |
| AC-0308 | Active profile name displayed in the toolbar next to the threshold selector |
| AC-0309 | All 6 sub-score columns remain visible regardless of which profile is active — a weight of 0% means "not counted in composite" but the column is still shown |
| AC-0310 | Composite score shown in a dedicated column; recomputed client-side as `Σ(score × weight)` using stored sub-scores |
| AC-0311 | The "Run Screener" button label indicates which profile was active when the stored run was computed (shown in history dropdown as "Top 25 · Short-term · 2026-07-20") |

### Non-functional

| ID | Criterion |
|---|---|
| AC-0320 | Profile recompute on 500 rows completes in <50ms (measured in browser DevTools) |
| AC-0321 | No regression in existing medium-to-long screener scores |

---

## Stage 2 — Architect: Design

### 2.1 The Separation Principle

```
SCREENER RUN (writes facts)          PROFILE (interprets facts)
─────────────────────────────        ──────────────────────────
run_screener.py                      Frontend state / localStorage
  ↓                                  WeightProfile.SHORT_TERM
score_one_ticker()                   WeightProfile.MEDIUM_LONG
  ↓ always computes all 6            WeightProfile.CUSTOM → sliders
ScreenerResult (DB row)
  valuation_score
  fundamentals_score
  jhunjhunwala_score
  growth_score
  insider_score
  technical_score     ← NEW
```

Profiles live entirely in the frontend. The backend knows nothing about profiles.
`GET /screener/runs/{id}/results` always returns all 6 sub-scores.
The client computes composite from sub-scores × active weights.

### 2.2 Technical Score Integration into `TickerData`

The `TickerData` dataclass (defined in `run_screener.py`) gains one new field:

```python
@dataclass
class TickerData:
    ticker: str
    financial_metrics: list
    line_items: list
    market_cap: float | None
    insider_trades: list
    prices_df: pd.DataFrame | None   # NEW — fetched via get_prices() → prices_to_df()
    end_date: str
```

`score_one_ticker()` already calls `get_prices()` for the technical step.
`prices_to_df()` is an existing utility in `src/tools/api.py`.

**Price fetch window:** `start_date = end_date − 365 days`, same as existing technical agent.

### 2.3 `score_technical()` Implementation

```python
# In scorer.py — direct import from technicals.py (all standalone, no LangGraph calls)
from src.agents.technicals import (
    calculate_trend_signals,
    calculate_mean_reversion_signals,
    calculate_momentum_signals,
    calculate_volatility_signals,
    calculate_stat_arb_signals,
    weighted_signal_combination,
)

TECHNICAL_STRATEGY_WEIGHTS = {
    "trend": 0.25,
    "mean_reversion": 0.20,
    "momentum": 0.25,
    "volatility": 0.15,
    "stat_arb": 0.15,
}

def score_technical(data: TickerData) -> float | None:
    """
    Mirrors technical_analyst_agent deterministic path exactly.
    Returns 0-100. Returns None if prices_df is None or has <60 rows.
    Signal mapping:
      bullish + confidence C → 50 + (C * 50)   [range: 50–100]
      bearish + confidence C → 50 - (C * 50)   [range: 0–50]
      neutral               → 50.0
    """
    if data.prices_df is None or len(data.prices_df) < 60:
        return None
    df = data.prices_df
    combined = weighted_signal_combination(
        {
            "trend":          calculate_trend_signals(df),
            "mean_reversion": calculate_mean_reversion_signals(df),
            "momentum":       calculate_momentum_signals(df),
            "volatility":     calculate_volatility_signals(df),
            "stat_arb":       calculate_stat_arb_signals(df),
        },
        TECHNICAL_STRATEGY_WEIGHTS,
    )
    signal = combined["signal"]       # "bullish" | "bearish" | "neutral"
    confidence = combined["confidence"]  # float 0–1

    if signal == "bullish":
        return round(50.0 + confidence * 50.0, 2)
    elif signal == "bearish":
        return round(50.0 - confidence * 50.0, 2)
    else:
        return 50.0
```

### 2.4 DB Migration (no Alembic)

Since `Base.metadata.create_all` only creates tables and never alters them,
existing `screener_results` tables won't gain `technical_score` automatically
after this feature is deployed on a live DB.

Add a startup migration helper in `app/backend/database/connection.py`:

```python
from sqlalchemy import text, inspect as sa_inspect

def run_migrations(engine) -> None:
    """Lightweight ALTER TABLE migrations for columns added post-initial-create."""
    insp = sa_inspect(engine)
    with engine.begin() as conn:
        # Add technical_score to screener_results if missing
        cols = [c["name"] for c in insp.get_columns("screener_results") if insp.has_table("screener_results")]
        if "technical_score" not in cols:
            conn.execute(text("ALTER TABLE screener_results ADD COLUMN technical_score REAL"))
```

Call `run_migrations(engine)` in `app/backend/main.py` startup, after `Base.metadata.create_all`.

### 2.5 Frontend Profile Architecture

```typescript
// src/screener/types.ts

export type SubScoreKey =
  | "valuation_score"
  | "fundamentals_score"
  | "jhunjhunwala_score"
  | "growth_score"
  | "insider_score"
  | "technical_score";

export type WeightMap = Record<SubScoreKey, number>;  // values 0-1, must sum to 1.0

export interface WeightProfile {
  id: "short_term" | "medium_long" | "custom";
  label: string;
  weights: WeightMap;
  editable: boolean;
}

// src/screener/profiles.ts — SINGLE SOURCE OF TRUTH for built-in profiles

export const PROFILES: Record<string, WeightProfile> = {
  short_term: {
    id: "short_term",
    label: "Short-term",
    editable: false,
    weights: {
      technical_score:     0.35,
      fundamentals_score:  0.20,
      valuation_score:     0.15,
      growth_score:        0.15,
      insider_score:       0.10,
      jhunjhunwala_score:  0.05,
    },
  },
  medium_long: {
    id: "medium_long",
    label: "Medium-to-long term",
    editable: false,
    weights: {
      valuation_score:     0.30,
      fundamentals_score:  0.25,
      jhunjhunwala_score:  0.20,
      growth_score:        0.15,
      insider_score:       0.10,
      technical_score:     0.00,
    },
  },
  custom: {
    id: "custom",
    label: "Custom",
    editable: true,
    weights: loadCustomWeights(),  // from localStorage; default = medium_long weights
  },
};

// src/screener/hooks/useCompositeScore.ts

export function computeComposite(
  result: ScreenerResultResponse,
  weights: WeightMap,
): number | null {
  const scores: SubScoreKey[] = [
    "valuation_score", "fundamentals_score", "jhunjhunwala_score",
    "growth_score", "insider_score", "technical_score",
  ];
  let total = 0;
  let totalWeight = 0;
  for (const key of scores) {
    const score = result[key];
    const w = weights[key];
    if (score != null && w > 0) {
      total += score * w;
      totalWeight += w;
    }
  }
  if (totalWeight === 0) return null;
  // Re-normalise to account for null sub-scores (e.g. technical_score=null for old runs)
  return Math.round((total / totalWeight) * 100) / 100;
}

// Applied in ScreenerRankTable: results.map(r => ({...r, composite: computeComposite(r, activeProfile.weights)}))
//                               .sort((a,b) => b.composite - a.composite)
```

### 2.6 Custom Weight Slider UX Rule

When a user drags one slider, the remaining sliders auto-adjust proportionally so the sum stays at 100%. Implementation:

```typescript
function adjustWeights(weights: WeightMap, changedKey: SubScoreKey, newValue: number): WeightMap {
  const delta = newValue - weights[changedKey];
  const others = Object.keys(weights).filter(k => k !== changedKey) as SubScoreKey[];
  const totalOthers = others.reduce((s, k) => s + weights[k], 0);
  const adjusted: WeightMap = { ...weights, [changedKey]: newValue };
  if (totalOthers > 0) {
    for (const k of others) {
      adjusted[k] = Math.max(0, weights[k] - (delta * weights[k] / totalOthers));
    }
  }
  return adjusted;
}
```

### 2.7 What Changes vs. What Stays the Same

| Component | Change type | Detail |
|---|---|---|
| `ScreenerResult` DB model | Add column | `technical_score = Column(Float, nullable=True)` |
| `database/connection.py` | Add fn | `run_migrations(engine)` — ALTER TABLE guard |
| `app/backend/main.py` | 1 line | call `run_migrations(engine)` after `create_all` |
| `src/screener/scorer.py` | Add fn | `score_technical(data)` |
| `src/screener/run_screener.py` | Extend | fetch prices into `TickerData.prices_df`; call `score_technical`; persist to DB |
| `app/backend/routes/screener.py` | Schema | `ScreenerResultResponse` gains `technical_score: float | None` |
| Frontend: `ScreenerResultResponse` type | Extend | add `technical_score?: number` |
| Frontend: new files | New | `profiles.ts`, `types.ts`, `useCompositeScore.ts`, `WeightProfileSelector.tsx`, `WeightSliders.tsx` |
| Frontend: `ScreenerToolbar.tsx` | Extend | add `<WeightProfileSelector>` |
| Frontend: `ScreenerRankTable.tsx` | Extend | read active profile weights, run `computeComposite` on each row, re-sort |
| **Screener API** | **No change** | All 6 sub-scores already returned; no new endpoints |
| **Screener run logic** | **Minimal change** | One extra data fetch (prices) + one score function call |

---

## Stage 3 — Engineer: Implementation Plan

Build in this exact order (each step is independently testable):

### Step 1 — Backend: `score_technical()` in scorer.py

```python
# src/screener/scorer.py — append after existing score functions

def score_technical(data: TickerData) -> float | None:
    # (exact implementation shown in §2.3 above)
```

**Test:** `poetry run pytest src/screener/tests/test_scorer.py::test_score_technical`

Fixture: use SGFIN.NS price data (already fetched in prior sessions).
Assert: bullish signal → score > 50; bearish → score < 50; None for empty df.

### Step 2 — Backend: extend `TickerData` + `score_one_ticker()`

In `run_screener.py`:
```python
@dataclass
class TickerData:
    ...
    prices_df: pd.DataFrame | None = None   # add this field

def score_one_ticker(ticker: str, end_date: str) -> dict:
    ...
    # After existing fetches, add:
    from datetime import datetime, timedelta
    start_date = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=365)).strftime("%Y-%m-%d")
    prices = get_prices(ticker=ticker, start_date=start_date, end_date=end_date, api_key=None)
    prices_df = prices_to_df(prices) if prices else None

    data = TickerData(
        ...,
        prices_df=prices_df,
    )
    ...
    technical = score_technical(data)
    return {
        ...,
        "technical_score": technical,
    }
```

### Step 3 — Backend: DB column + migration

In `app/backend/database/models.py`:
```python
class ScreenerResult(Base):
    ...
    technical_score = Column(Float, nullable=True)   # add this line
```

In `app/backend/database/connection.py`: add `run_migrations(engine)` as shown in §2.4.

In `app/backend/main.py`:
```python
from app.backend.database.connection import engine, run_migrations
Base.metadata.create_all(bind=engine)
run_migrations(engine)    # add this line
```

**Test:** Start server, check `sqlite3 app/backend/hedge_fund.db ".schema screener_results"` shows `technical_score` column.

### Step 4 — Backend: API schema

In `app/backend/models/schemas.py`:
```python
class ScreenerResultResponse(BaseModel):
    ...
    technical_score: float | None = None   # add this field
```

No route changes needed.

### Step 5 — Frontend: types and profiles

New files:
- `src/components/screener/types.ts` — `WeightProfile`, `WeightMap`, `SubScoreKey`
- `src/components/screener/profiles.ts` — `PROFILES`, `loadCustomWeights`, `saveCustomWeights`
- `src/components/screener/hooks/useCompositeScore.ts` — `computeComposite`, `useRerankedResults`

### Step 6 — Frontend: WeightProfileSelector + WeightSliders

New components:
- `WeightProfileSelector.tsx` — dropdown with 3 options; shows active profile in toolbar
- `WeightSliders.tsx` — 6 labelled sliders, shown only in Custom mode; auto-normalises

### Step 7 — Frontend: integrate into ScreenerToolbar + ScreenerRankTable

`ScreenerToolbar.tsx`:
- Add `activeProfile` state (default: `PROFILES.medium_long`)
- Render `<WeightProfileSelector>` after threshold toggle
- When Custom selected: render `<WeightSliders>` in a popover

`ScreenerRankTable.tsx`:
- Accept `activeProfile: WeightProfile` prop
- On render: `const rankedResults = results.map(r => ({...r, displayComposite: computeComposite(r, activeProfile.weights)})).sort(...)`
- Column headers: `"Valuation ${(activeProfile.weights.valuation_score * 100).toFixed(0)}%"`

---

## Stage 4 — Gates

### ruff (linting)
```bash
poetry run ruff check src/screener/ app/backend/
```
All new Python files must pass with zero warnings.
Config already in `pyproject.toml` (line-length=420, effectively disabled).

### mypy (type checking)
```bash
poetry run mypy src/screener/scorer.py src/screener/run_screener.py src/screener/composite.py --ignore-missing-imports
```
`score_technical` must have correct return type `float | None`.
`TickerData.prices_df` must be typed `pd.DataFrame | None`.

### pytest (unit tests)

New test file: `src/screener/tests/test_scorer.py`

```python
# Required test cases mapping to ACs

def test_score_technical_bullish_returns_above_50():     # AC-0201, AC-0203
def test_score_technical_bearish_returns_below_50():     # AC-0201, AC-0203
def test_score_technical_neutral_returns_50():           # AC-0203
def test_score_technical_none_on_empty_df():             # AC-0205
def test_score_technical_none_on_short_history():        # AC-0205
def test_score_technical_matches_technical_agent_output(): # AC-0202 — same functions, same result

# New test file: src/screener/tests/test_composite.py
def test_compute_composite_short_term_profile():         # AC-0302
def test_compute_composite_medium_long_profile():        # AC-0303
def test_compute_composite_custom_weights_sum_to_100():  # AC-0304
def test_compute_composite_null_technical_renormalises(): # AC-0310
def test_profile_rerank_is_deterministic():              # AC-0306
```

Run gate:
```bash
poetry run pytest src/screener/tests/ -v --tb=short
```
All tests must pass. Zero new failures in existing tests.

---

## Stage 5 — Traceability: AC Coverage Map

| AC | Covered by | Type |
|---|---|---|
| AC-0201 | `test_score_technical_bullish_returns_above_50` | unit |
| AC-0202 | `test_score_technical_matches_technical_agent_output` | integration |
| AC-0203 | `test_score_technical_*` (3 signal cases) | unit |
| AC-0204 | `test_score_technical_none_on_short_history` | unit |
| AC-0205 | `test_score_technical_none_on_empty_df` | unit |
| AC-0206 | Manual: check DB schema after migration | manual |
| AC-0301 | `test_compute_composite_short_term_profile` + `test_compute_composite_medium_long_profile` | unit |
| AC-0302 | `test_compute_composite_short_term_profile` asserts weight values | unit |
| AC-0303 | `test_compute_composite_medium_long_profile` asserts weight values | unit |
| AC-0304 | `test_compute_composite_custom_weights_sum_to_100` | unit |
| AC-0305 | Manual: reload page, verify custom weights survive | manual |
| AC-0306 | `test_profile_rerank_is_deterministic` | unit |
| AC-0307 | Visual: column headers show weight % | UI smoke |
| AC-0308 | Visual: toolbar shows active profile name | UI smoke |
| AC-0309 | Visual: all 6 columns visible when technical weight = 0 | UI smoke |
| AC-0310 | `test_compute_composite_null_technical_renormalises` | unit |
| AC-0311 | Visual: history dropdown shows profile name in run label | UI smoke |
| AC-0320 | Browser DevTools: measure re-sort time on 500 rows | perf |
| AC-0321 | `test_compute_composite_medium_long_profile` values unchanged | regression |

**Coverage breakdown:**
- 10/19 ACs covered by automated unit tests
- 3/19 covered by manual checks (DB schema, localStorage, history label)
- 4/19 covered by UI smoke test (visual)
- 1/19 by perf measurement
- 1/19 by regression test

**Uncovered ACs requiring manual sign-off:** AC-0305, AC-0307, AC-0308, AC-0309, AC-0311, AC-0320.
Engineer must check these off manually before marking the slice as done.

---

## Stage 6 — Slice Check: `slice-status.py`

The `scripts/slice-status.py` script does not exist yet (noted as a scaffold conflict in CLAUDE.md).
Define what it must verify for this feature slice:

```python
# scripts/slice-status.py — checks for weight-profiles slice

checks = [
    # Backend presence
    ("src/screener/scorer.py has score_technical()",
     lambda: "def score_technical" in open("src/screener/scorer.py").read()),

    ("TickerData has prices_df field",
     lambda: "prices_df" in open("src/screener/run_screener.py").read()),

    ("ScreenerResult model has technical_score column",
     lambda: "technical_score" in open("app/backend/database/models.py").read()),

    ("run_migrations called in main.py",
     lambda: "run_migrations" in open("app/backend/main.py").read()),

    ("ScreenerResultResponse has technical_score field",
     lambda: "technical_score" in open("app/backend/models/schemas.py").read()),

    # Frontend presence
    ("profiles.ts exists",
     lambda: os.path.exists("app/frontend/src/components/screener/profiles.ts")),

    ("WeightProfileSelector.tsx exists",
     lambda: os.path.exists("app/frontend/src/components/screener/WeightProfileSelector.tsx")),

    ("WeightSliders.tsx exists",
     lambda: os.path.exists("app/frontend/src/components/screener/WeightSliders.tsx")),

    # Test presence
    ("test_score_technical tests exist",
     lambda: "test_score_technical" in open("src/screener/tests/test_scorer.py").read()),

    ("test_compute_composite tests exist",
     lambda: "test_compute_composite" in open("src/screener/tests/test_composite.py").read()),

    # AC traceability comments in tests
    ("AC-0201 referenced in tests",
     lambda: "AC-0201" in open("src/screener/tests/test_scorer.py").read()),

    ("AC-0302 referenced in tests",
     lambda: "AC-0302" in open("src/screener/tests/test_composite.py").read()),
]
```

Run: `poetry run python scripts/slice-status.py`
Expected: all checks GREEN before marking this slice DONE.

---

## Weight Profile Reference Card

| Sub-score | Short-term | Medium-long | Notes |
|---|---|---|---|
| Technical | **35%** | 0% | Dominant for short-term; irrelevant long-term |
| Fundamentals | 20% | **25%** | Always relevant |
| Valuation | 15% | **30%** | Entry price matters more long-term |
| Growth | 15% | 15% | Equal weight both horizons |
| Insider | 10% | 10% | Equal weight both horizons |
| Jhunjhunwala | 5% | **20%** | Long-term quality score, minimal short-term value |
| **Total** | **100%** | **100%** | |

**Custom:** User-defined via sliders; weights auto-normalised to sum to 100%.
Profiles live in frontend only. Backend always stores all 6 sub-scores.
