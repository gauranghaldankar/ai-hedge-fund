# PM Analysis: Kite Connect Price Data Migration — Flows Pipeline

**Date:** 2026-07-20
**Author:** Product Manager (AgentCo)
**Scope:** Replace yfinance OHLCV price fetches with Kite Connect in the analyst agent pipeline,
mirroring the pattern already established in the Nifty 500 screener.

---

## 1. How Price Data Flows Today

### The routing layer (`src/tools/api.py`)

`api.py` is the single public interface all agents import from. It contains two price-relevant functions:

- `get_prices(ticker, start_date, end_date, api_key)` — returns `list[Price]`
- `get_price_data(ticker, start_date, end_date, api_key)` — returns `pd.DataFrame` (calls `get_prices` + `prices_to_df`)

When the ticker has a `.NS`, `.BO`, or `.BSE` suffix, `_is_yf_ticker()` fires and both functions delegate to
`yf_api.get_prices()` / `yf_api.get_price_data()` immediately, bypassing financialdatasets.ai.
This is the only routing decision that currently exists. There is no Kite path here at all.

### Which agents fetch price data

| Agent | File | Function called | What it returns |
|---|---|---|---|
| Technical Analyst | `src/agents/technicals.py` | `get_prices()` + `prices_to_df()` from `api.py` | `list[Price]` then converted to DataFrame |
| Risk Manager | `src/agents/risk_manager.py` | `get_prices()` + `prices_to_df()` from `api.py` | same pattern |
| Nassim Taleb | `src/agents/nassim_taleb.py` | `get_prices()` + `prices_to_df()` from `api.py` | same pattern |
| Stanley Druckenmiller | `src/agents/stanley_druckenmiller.py` | `get_prices()` from `api.py` | same pattern |

### Which agents do NOT fetch price data

- `fundamentals.py` — calls `get_financial_metrics()` only. No price data.
- `sentiment.py` — calls `get_insider_trades()` and `get_company_news()` only. No price data.
- `valuation.py` — calls `get_financial_metrics()`, `search_line_items()`, `get_market_cap()`. No price data.
- All persona agents (Buffett, Graham, Ackman, etc.) — vary, but those checked do not call `get_prices` directly; they call `get_financial_metrics` and `search_line_items`.

### The single choke point

`api.py::get_prices()` is the single function all price-consuming agents call. It is the correct and minimal
place to add a Kite path. If we add a Kite branch inside `get_prices()`, every agent that calls it gains
Kite price data for free — no agent-level changes needed.

---

## 2. The Screener's Established Pattern

`src/screener/run_screener.py` already implements the correct Kite-primary / yfinance-fallback pattern:

1. At screener startup, a single `KiteConnect` client and a single `token_lookup` dict are built once
   (one `instruments("NSE")` call covers all tickers for the entire run).
2. `_fetch_ticker_data()` receives `(kite_token_lookup, kite_client)` as parameters.
3. For price data, it strips the `.NS`/`.BO` suffix (`ticker.removesuffix(".NS").removesuffix(".BO")`),
   calls `get_price_data_kite()`, and only falls back to `yf_api.get_price_data()` if Kite returns None
   or raises.
4. Fundamentals and insider data always go through yfinance — Kite has no fundamentals API.

This pattern is proven and tested. We replicate it for the flows pipeline.

---

## 3. Architecture Decision: Where to Inject Kite in the Flows Pipeline

### Option A: Add Kite branch inside `api.py::get_prices()` — RECOMMENDED

Add a check before the existing yfinance branch in `get_prices()`:

```
if _is_yf_ticker(ticker):
    # Try Kite first if client is available in call context
    # Fall back to yf_api.get_prices()
```

**Problem:** `get_prices()` currently receives no Kite client. The client would need to be either:
- (a) built inside the function on every call (expensive — one `instruments()` call per `get_prices()` call),
- (b) passed as a parameter (changes the public signature used by all callers), or
- (c) held in a module-level singleton initialized once at app startup.

Option (c) — a module-level singleton initialized lazily — is the lowest-friction approach.
It mirrors how `_cache` is already a module-level singleton in `api.py`.

### Option B: Inject Kite client + token_lookup via `state["data"]` (thread through AgentState)

The `start` node in `src/main.py` simply passes state through. The graph init in `app/backend/services/graph.py`
calls `run_graph_async()`. We could initialize the Kite client once before the graph runs and place it in
`state["data"]["kite_client"]` and `state["data"]["kite_token_lookup"]`.

Each price-consuming agent would then read these from state and pass them to a new function.

**Problem:** This requires changes in every agent that fetches prices (currently 4, potentially more persona
agents in future). It also means modifying `AgentState` semantics, which is a larger surface change.

### Option C: Module-level singleton in `api.py` — RECOMMENDED OVER B

A `_kite_client` and `_kite_token_lookup` module-level variable in `api.py`, initialized lazily on first
call to `get_prices()` for a yf-routed ticker, is the minimal-change solution.

- Zero changes to any agent file.
- Zero changes to `AgentState`.
- Zero changes to the graph construction or the routes layer.
- Consistent with how `_cache` already works.
- For a flows run (1 ticker, 4 agents), the singleton is built once and all 4 agents reuse it.
- For a future multi-ticker flow run, all tickers share the same token_lookup (same as screener).

The only downside: a module-level mutable is process-scoped and not thread-safe (same risk as `_cache`).
For the current single-process FastAPI setup this is acceptable and is already an acknowledged known risk.

### Decision

Use Option C (module-level singleton in `api.py`). The intervention is: add a `_init_kite()` helper and
a `_kite_price_block()` inside `get_prices()`. Non-yf tickers are untouched. When Kite is not configured,
behavior is identical to today.

---

## 4. Ticker Format at the Kite Layer

Flow tickers arrive as `.NS`-suffixed strings (e.g. `"SGFIN.NS"`). This is because users enter them in
the Flows UI in that format and the backend passes them as-is through `state["data"]["tickers"]`.

The Kite API requires bare NSE symbols (`"SGFIN"`). The stripping logic from the screener is:

```python
symbol = ticker.removesuffix(".NS").removesuffix(".BO")
```

This logic belongs inside the new Kite branch in `api.py::get_prices()`, identical to the screener.

`.BSE` tickers: Kite uses `BSE` as the exchange string, not `NSE`. The `build_token_lookup()` currently
only fetches `kite.instruments("NSE")`. BSE support would require a separate lookup or a separate
`instruments("BSE")` call. This migration targets `.NS` tickers only in the first pass.
`.BO` and `.BSE` tickers will continue to fall through to yfinance. This is acceptable for MVP.

---

## 5. Kite Client Lifecycle in a Flow Run

For the screener, building the client once for 500 tickers is essential (0.35s rate limit sleep × 500 = 175s
just in sleep time if done serially; the singleton avoids 500 `instruments()` calls).

For a flows run (typically 1–5 tickers, 4–6 agents), the benefit is smaller in absolute time but still
correct: without a singleton, each agent would re-initialize Kite and re-call `instruments("NSE")`. With
the singleton, it is called once across the entire graph execution, regardless of ticker count or agent count.

The module-level singleton initialized lazily on first price fetch is the right choice.

---

## 6. What Kite Provides vs. What yfinance Must Still Provide

| Data Type | Kite | yfinance (remains) |
|---|---|---|
| Daily OHLCV price history | YES — primary | Fallback only |
| Financial metrics (PE, ROE, margins) | No | YES |
| Line items (FCF, revenue, debt) | No | YES |
| Insider trades | No | YES |
| Company news / sentiment | No | YES |
| Market cap | No | YES |

Agents that do NOT fetch prices (fundamentals, sentiment, valuation, all persona agents using fundamentals)
are completely unaffected by this migration.

---

## 7. Agents and Other Callers Outside the Flows Pipeline

`get_prices()` in `api.py` is also called from:
- `src/backtesting/engine.py` — backtest engine
- `src/backtesting/benchmarks.py` — SPY benchmark via `get_price_data()`

These are US tickers (SPY, AAPL, etc.) and are NOT `.NS` tickers, so `_is_yf_ticker()` returns False for
them and they continue to financialdatasets.ai. The Kite branch only activates for `_is_yf_ticker()` tickers.
No risk to existing US-market backtest behavior.

---

## 8. Test Strategy

The screener already has a full test suite for `kite_api.py` (`src/screener/tests/test_kite_api.py`, 8 tests,
all mocked). The flows migration needs:

1. Unit tests for the new `_init_kite()` / Kite branch inside `api.py::get_prices()`, mocked.
2. An integration smoke test: with a mock Kite client injected, `get_prices("SGFIN.NS", ...)` returns
   a `list[Price]` derived from the Kite DataFrame (not from yfinance).
3. A fallback test: when Kite returns None, `get_prices("SGFIN.NS", ...)` falls back to yfinance.
4. A no-config test: when Kite creds are absent, behavior is identical to today (yfinance path, no error).

---

## 9. Summary of Required Changes (Engineer Scope)

| # | Change | File(s) | Risk |
|---|---|---|---|
| 1 | Add `_kite_client`, `_kite_token_lookup`, `_init_kite()` singleton | `src/tools/api.py` | Low |
| 2 | Add Kite branch inside `get_prices()` for `.NS` tickers | `src/tools/api.py` | Low |
| 3 | Unit + integration tests | `tests/tools/test_api_kite.py` (new file) | None |

Zero changes to agents, AgentState, routes, frontend, or DB.

---

## 10. Tickets Produced

| Ticket | Title | ACs |
|---|---|---|
| FLW-005 | Add Kite module-level singleton to `api.py` | AC-0222, AC-0223, AC-0224 |
| FLW-006 | Kite price branch inside `get_prices()` | AC-0225, AC-0226, AC-0227, AC-0228 |
| FLW-007 | Tests for Kite-in-api.py integration | AC-0229, AC-0230, AC-0231, AC-0232 |
