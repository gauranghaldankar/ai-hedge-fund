# System Map — ai-hedge-fund

> Read-only analysis. Source is unchanged. Produced by codebase-analyst.

---

## 1. Inventory

**Languages & scale**

| Language | Files | Notes |
|---|---|---|
| Python | ~176 | All logic, API, LangGraph agents |
| TypeScript/TSX | ~110 | React frontend |
| SQL (Alembic) | 5 migrations | SQLite schema |

**Package manager / runtime**

- Python: Poetry (`pyproject.toml`), requires Python ≥ 3.11
- Frontend: pnpm (`app/frontend/pnpm-lock.yaml`), Vite + React + Tailwind + shadcn/ui

**Build / run commands**

```bash
# Install all deps
poetry install

# CLI: run one decision cycle
poetry run python src/main.py --ticker AAPL,MSFT,NVDA

# CLI: run backtest
poetry run python src/backtester.py --ticker AAPL,MSFT,NVDA

# Backend API (FastAPI)
# from app/backend/
uvicorn app.backend.main:app --reload

# Frontend (from app/frontend/)
pnpm install && pnpm dev

# v2 engine (interactive)
poetry run python -m v2.run

# v2 tests
poetry run pytest v2/

# v1 tests
poetry run pytest tests/
```

**External dependencies**

| Dependency | Purpose |
|---|---|
| `financialdatasets.ai` | Price data, financial metrics, insider trades, company news |
| OpenAI / Anthropic / Groq / Google / DeepSeek / xAI / GigaChat / Ollama / Azure OpenAI / OpenRouter / Kimi | LLM providers for agent reasoning |
| LangGraph / LangChain | Agent orchestration DAG |
| FastAPI + SQLAlchemy + Alembic + SQLite | Backend REST API + persistence |
| React + ReactFlow + Tailwind + shadcn/ui | Frontend visual flow editor |

**Required env vars**

```
FINANCIAL_DATASETS_API_KEY   # market data (required for all data fetching)
OPENAI_API_KEY               # at least one LLM key required
# Optionally: ANTHROPIC_API_KEY, GROQ_API_KEY, DEEPSEEK_API_KEY, GOOGLE_API_KEY,
#             XAI_API_KEY, OPENROUTER_API_KEY, MOONSHOT_API_KEY,
#             GIGACHAT_API_KEY, AZURE_OPENAI_API_KEY + AZURE_OPENAI_ENDPOINT +
#             AZURE_OPENAI_DEPLOYMENT_NAME, OLLAMA_BASE_URL
```

---

## 2. Module Map

Three **co-existing generations** in the repo. They share code (v2 imports nothing from v1 `src/`; the web app `app/` imports directly from `src/`).

```
src/                  ← v1: production CLI + web-app backend logic
  main.py             ← entry point: build LangGraph, invoke, print
  backtester.py       ← entry point: iterate trading days, call run_hedge_fund()
  agents/             ← 19 analyst agents + risk_manager + portfolio_manager
  graph/state.py      ← AgentState TypedDict (messages, data, metadata)
  tools/api.py        ← all financialdatasets.ai HTTP calls + in-memory cache
  data/cache.py       ← in-memory Cache class (process-scoped singleton)
  data/models.py      ← Pydantic models for API responses
  llm/models.py       ← ModelProvider enum, LLMModel, get_model(), load from JSON
  llm/api_models.json ← list of cloud LLM models
  llm/ollama_models.json ← list of Ollama models
  utils/analysts.py   ← ANALYST_CONFIG (single source of truth for all 19 agents)
  utils/llm.py        ← call_llm() with retry + structured output
  cli/input.py        ← argparse + questionary interactive prompts
  backtesting/        ← BacktestEngine: iterate dates, simulate trades
    engine.py
    types.py

app/                  ← web application (wraps src/)
  backend/
    main.py           ← FastAPI app, CORS, startup Ollama check
    routes/           ← API routers (hedge_fund, flows, flow_runs, api_keys, etc.)
    services/
      graph.py        ← create_graph() from ReactFlow nodes/edges, run_graph()
      agent_service.py← create_agent_function() — binds unique node ID to agent
      backtest_service.py ← async backtest runner
      portfolio.py    ← create_portfolio() helper
      api_key_service.py ← CRUD for stored API keys
    database/
      connection.py   ← SQLite engine (hedge_fund.db in backend dir)
      models.py       ← SQLAlchemy: HedgeFundFlow, HedgeFundFlowRun,
                         HedgeFundFlowRunCycle, ApiKey
    models/
      schemas.py      ← Pydantic request/response models (HedgeFundRequest etc.)
      events.py       ← SSE event types (StartEvent, ProgressUpdateEvent, etc.)
    repositories/     ← thin DB CRUD wrappers
    alembic/          ← 5 migration versions
  frontend/
    src/
      App.tsx         ← root; ReactFlow canvas
      components/
        Flow.tsx      ← drag-drop agent graph builder
        panels/       ← left (flow list), right (agent palette), bottom (output)
        settings/     ← API keys, model config, appearance

v2/                   ← v2: ground-up rebuild (NOT yet wired into app/)
  models.py           ← Signal, QuantSignals (core data contracts)
  signals/
    base.py           ← AlphaModel ABC (predict(ticker, date, data_client)->Signal)
    pead.py           ← PEAD quant model
    buffett.py        ← Warren Buffett LLM agent
    graham/munger/lynch/druckenmiller.py ← more LLM agents
  pipeline/
    run_cycle.py      ← run_cycle(): one tick of the fund (the heartbeat)
    execution.py      ← build_orders() pure function
    models.py         ← CycleRecord, StrategyRecord, TickerSkip
  fund/spec.py        ← FundSpec + Fund (YAML mandate → Python objects)
  strategies/         ← YAML strategy definitions (pod library)
  portfolio/construction.py ← blend_signals() pure function
  risk/limits.py      ← apply_limits() pure function (hard position/gross caps)
  brokers/            ← Broker protocol + SimBroker (paper trading)
  data/               ← DataClient protocol, FinancialDatasetsClient, disk cache
  backtesting/        ← v2 backtest engine (built on run_cycle)
  llm/                ← AnthropicLLM with prompt cache
  run.py              ← CLI: interactive fund builder or YAML mandate runner
```

**Dependency direction**

```
app/backend → src/agents, src/utils, src/graph, src/llm, src/tools
src/agents  → src/tools/api, src/utils/llm, src/graph/state
src/tools/api → src/data/cache, src/data/models
v2/         → (self-contained, no src/ or app/ imports)
```

---

## 3. Data Flow — End-to-end Request (Web App)

**`POST /hedge-fund/run`** (the primary user action)

1. **Frontend** (`Flow.tsx`) serializes the ReactFlow canvas (nodes = analyst agents, edges = connections) into a `HedgeFundRequest` payload (tickers, graph_nodes, graph_edges, model_config, start/end dates, initial cash).

2. **`hedge_fund.py` route** receives the request. Hydrates API keys from SQLite `api_keys` table if not supplied in the request body.

3. **`create_portfolio()`** (`services/portfolio.py`) builds a dict of cash + zero positions.

4. **`create_graph()`** (`services/graph.py`) walks the ReactFlow nodes/edges and constructs a `LangGraph.StateGraph`:
   - Each analyst node → an `AgentState → AgentState` function (from `ANALYST_CONFIG`)
   - Each portfolio_manager node gets a paired `risk_management_agent_{suffix}` node auto-inserted
   - Edges are wired: analyst → risk_manager → portfolio_manager → END

5. **`run_graph_async()`** offloads `graph.invoke()` to a thread pool (blocking LLM calls don't block the event loop). The graph is invoked with initial `AgentState`.

6. **Inside the graph** (parallel analyst nodes):
   - Each analyst (e.g. `warren_buffett_agent`) reads `state["data"]["tickers"]`
   - Calls `src/tools/api.py` functions (`get_financial_metrics`, `search_line_items`, `get_prices`, etc.)
   - `tools/api.py` checks the in-memory `Cache` singleton first; on miss, calls `api.financialdatasets.ai` with rate-limit retry
   - Runs deterministic scoring logic (e.g. ROE checks, DCF)
   - Calls `call_llm()` → `get_model()` → LangChain model → structured output → `WarrenBuffettSignal`
   - Writes signal to `state["data"]["analyst_signals"][agent_id]`

7. **`risk_management_agent`**: reads price data, computes volatility (60-day rolling std), builds correlation matrix across tickers, calculates per-ticker position limits (% of portfolio, volatility-adjusted + correlation-adjusted). Writes to `state["data"]["analyst_signals"]["risk_management_agent"]`.

8. **`portfolio_management_agent`**: reads all analyst signals + risk limits. Pre-fills "hold" for any ticker with no trade room. Sends remainder to LLM with allowed actions + max quantities. LLM returns `PortfolioManagerOutput` (one `PortfolioDecision` per ticker). Last message in `state["messages"]` is the JSON-encoded decisions.

9. **SSE streaming**: while the graph runs in a thread, a `progress_queue` receives updates from `progress.update_status()` calls. The event generator drains the queue, yielding `ProgressUpdateEvent` SSEs. On completion, yields `CompleteEvent` with `{decisions, analyst_signals, current_prices}`.

10. **Frontend** reads the SSE stream, populates the bottom panel with per-agent reasoning and the final trade decisions.

---

## 4. Conventions

**Naming**

- Python: `snake_case` everywhere (functions, vars, files). Agent files named after the persona (`warren_buffett.py`).
- TypeScript: `camelCase` for variables/functions, `PascalCase` for components.
- Pydantic models: `PascalCase` for class names (e.g. `WarrenBuffettSignal`, `PortfolioDecision`).
- LangGraph node names: `{analyst_key}_agent` (e.g. `warren_buffett_agent`).

**Error handling**

- `tools/api.py`: returns empty list `[]` on non-200 HTTP responses (silent failure). Rate-limited (429) responses retry up to 3x with linear backoff (60s, 90s, 120s).
- `call_llm()`: retries up to 3x; on final failure calls `default_factory()` or falls back to a default Pydantic instance. Agents provide specific `default_factory` lambdas that return neutral/hold defaults.
- v2 raises explicitly on infrastructure failures (no price for held position, equity ≤ 0). v1 silently returns empty.

**Logging**

- v1: `print()` statements directly. `logging.basicConfig(level=INFO)` in `app/backend/main.py` for FastAPI startup. `progress.update_status()` for agent-level tracking.
- v2: no explicit logger; uses `print()` in demos.

**Test framework**

- `pytest` (7.x). Tests live in `tests/` (v1) and co-located `v2/signals/test_*.py`, `v2/pipeline/test_*.py`.
- Test style: class-based for rate limiting (`class TestRateLimiting`), function-based elsewhere.
- Fixtures in `tests/fixtures/` and `tests/backtesting/conftest.py`.
- `unittest.mock` for patching HTTP calls and external deps.

**Agent pattern** (v1)

Every analyst follows the same structure:
1. `def agent_name(state: AgentState, agent_id: str = "..."):`
2. Loop over `state["data"]["tickers"]`
3. Fetch data via `src/tools/api.py`
4. Compute a deterministic score
5. Call `call_llm()` → typed Pydantic signal
6. Write `state["data"]["analyst_signals"][agent_id] = {ticker: {signal, confidence, reasoning}}`
7. Return `{"messages": [HumanMessage(content=json.dumps(signals), name=agent_id)], "data": state["data"]}`

New analysts must follow this contract to integrate with risk manager and portfolio manager.

---

## 5. Test Health

**What exists:**

| Test file | Coverage |
|---|---|
| `tests/test_api_rate_limiting.py` | `_make_api_request()` 429 retry logic (GET + POST) |
| `tests/test_cache.py` | `Cache` class: get/set/merge |
| `tests/test_cli_ticker_alias.py` | CLI ticker normalization |
| `tests/backtesting/test_*.py` | `BacktestEngine`: controller, execution, metrics, portfolio, results, valuation |
| `v2/signals/test_signals.py` | v2 signal models |
| `v2/signals/test_llm_agents.py` | v2 LLM agent contracts |
| `v2/pipeline/test_execution.py` | `build_orders()` |
| `v2/pipeline/test_run_cycle.py` | `run_cycle()` (mocked) |

**Critical gaps:**

- Zero tests for any of the 19 analyst agents (no coverage of `warren_buffett_agent`, `risk_management_agent`, `portfolio_management_agent` or their scoring logic)
- Zero tests for `call_llm()` retry behavior with structured output
- Zero tests for `create_graph()` or the SSE streaming route
- Zero tests for `tools/api.py` functions (get_prices, get_financial_metrics, etc.) beyond rate limiting
- No integration tests verifying an analyst signal flows correctly to portfolio decisions
- Tests require the Poetry virtual env (`colorama` import fails under bare system Python)

**Coverage estimate:** ~10–15% of v1 business logic. v2 is better covered (~30–40%) due to pure-function design.

---

## 6. Risk Areas

### High severity

**Cache key mismatch (silent, hard to detect)**
`src/data/cache.py` declares methods with parameter `ticker: str` but `src/tools/api.py` passes compound keys like `f"{ticker}_{start_date}_{end_date}"`. The dict stores and retrieves correctly under the compound key, but the merge logic in `set_prices` (intended to deduplicate by `time` field) is effectively dead — it will never merge across overlapping date ranges because the compound key is always an exact hit or miss. A backtest iterating day-by-day re-fetches data on every slightly different date window. **Impact:** excessive API calls and potential rate-limit exhaustion during backtests.

**API keys stored plaintext**
The `ApiKey` table in SQLite stores key values as plain `Text`. The comment says "encrypted in production" but no encryption exists in code. Any read from the DB (including the `ApiKeyResponse` schema) returns the full key value. **Impact:** key exposure if SQLite file is readable.

**In-memory cache is process-global and not thread-safe**
`src/data/cache.py` uses a module-level `_cache = Cache()` singleton. FastAPI runs handlers in a threadpool. Multiple concurrent `/hedge-fund/run` requests share the same cache dict with no locking. Python's GIL protects individual dict operations but not the check-then-set patterns in the cache methods. **Impact:** race conditions on simultaneous requests for the same ticker.

### Medium severity

**`parse_hedge_fund_response` duplicated**
Identical function exists in both `src/main.py` and `app/backend/services/graph.py`. Any bug fix must be applied in two places.

**v2 not wired into the app**
The web app (`app/`) still runs the v1 engine exclusively. v2's principled point-in-time data guarantees and `run_cycle` pipeline are not exposed to users. As v2 matures, there's a risk of drift between what's being developed and what's being used.

**Graph construction implicitly inserts risk manager**
`app/backend/services/graph.py:create_graph()` silently inserts a `risk_management_agent_{suffix}` for every `portfolio_manager` node, using the last 6 chars of the node ID as a suffix. If a ReactFlow node ID doesn't end with a 6-char alphanumeric suffix, `extract_base_agent_key()` returns the full ID and the suffix/pairing logic breaks silently.

**No disconnect between analyst signals on failure**
If `call_llm()` exhausts all retries and returns a default neutral signal, the risk manager and portfolio manager see it as a valid "neutral with confidence=50" signal — indistinguishable from a genuine neutral view. There is no "abstain" or "failed" sentinel value in v1.

### Low severity

**`line-length = 420` in Black config**
`pyproject.toml` sets Black's `line-length` to 420 characters. This is almost certainly a placeholder value never corrected, meaning Black is effectively disabled as a line-length enforcer. Long single-line expressions are common throughout.

**`bear except:` swallows exceptions**
`src/agents/warren_buffett.py:calculate_owner_earnings()` (line ~424): `except: pass` swallows all exceptions from the working-capital calculation block. This is the only silent exception suppressor found.

**`print()` in library code**
`src/llm/models.py:get_model()` calls `print()` for API key errors before raising. In the web-app context these prints go to stdout, not to SSE or structured logs.

---

## 7. Change Surface

Given the stated direction (evolving into a persistent, always-on fund with backtesting and paper trading):

**Files most likely to change:**

| File/Module | Why |
|---|---|
| `v2/pipeline/run_cycle.py` | Core heartbeat — every new fund capability touches this |
| `v2/signals/` | Adding new quant/LLM alpha models |
| `v2/strategies/` | New YAML strategy pod definitions |
| `v2/fund/spec.py` | Fund mandate schema as requirements evolve |
| `app/backend/routes/hedge_fund.py` | Wiring v2 engine into the web app |
| `app/backend/services/graph.py` | Will need to delegate to v2 `run_cycle` instead of v1 LangGraph |
| `app/backend/database/models.py` + `alembic/` | New tables as the persistent fund concept materializes |
| `src/agents/` | Any v1 agent added by community contributors |
| `src/utils/analysts.py` | ANALYST_CONFIG must be updated every time an agent is added |
| `src/llm/api_models.json` | New LLM providers/models |

**Load-bearing code to treat as immutable without tests:**

- `src/graph/state.py:AgentState` — changing the shape of `data` or `metadata` breaks all 19 agents simultaneously
- `src/utils/llm.py:call_llm()` — all agents depend on this; structured output mode changes affect every agent
- `v2/pipeline/run_cycle.py` — v2's single code path for all execution modes; bugs here corrupt backtests and live runs identically
- `v2/signals/base.py:AlphaModel.predict()` — the interface contract for every v2 alpha model

---

*Map complete. Do not modify source. Review before feature work.*
