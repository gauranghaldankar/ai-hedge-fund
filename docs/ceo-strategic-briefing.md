# CEO Strategic Briefing — ai-hedge-fund

> Written: 2026-07-27. Updated as sprints complete.

## What we actually have (three co-existing layers)

```
src/         v1 — 19 LLM analyst agents, LangGraph DAG, CLI + web backend
app/         Web UI — FastAPI over v1 + ReactFlow visual canvas + Screener
v2/          Ground-up rebuild — clean AlphaModel interface, point-in-time, PEAD quant model
             NOT wired into the web app yet
```

The vision (VISION.md) is excellent. The architecture of v2 is sound. The gap is that the three layers don't talk to each other, and several features are dead ends in the UI.

---

## The #1 Strategic Gap: Features that don't connect

| Feature | Exists | Connects to what? | Gap |
|---|---|---|---|
| Nifty 500 Screener | Yes | Nothing | Shortlist dies at the table |
| Analyst flow runner | Yes | Nothing | Results don't persist to a ledger |
| Backtest engine (v1) | Yes | Separate harness | Not same pipeline as live |
| v2 run_cycle | Yes | Nothing | Not in web app at all |
| Flow persistence | Yes | Nothing | Runs stored but no P&L tracking |
| Kite live prices | Yes (FLW-014) | Single run only | No paper trading |

**The screener finds stocks → the flow analyzes them → the run completes → nothing persists.** Every cycle is a fresh start with no memory of what was recommended or what happened.

---

## Opportunities by tier

### Tier 1 — Unlock the Vision (high leverage, connects existing features)

**1. Screener → Flow handoff**
The screener shortlists Nifty 500 stocks by composite score. One button — "Analyze in Flow" — should push the shortlisted tickers into a flow run. Right now these are completely disconnected features. This is the highest-ROI UI change possible.

**2. Persistent P&L / Decision Ledger**
The DB has `HedgeFundFlowRun` and `HedgeFundFlowRunCycle` tables already. What's missing is a dashboard that shows: what was recommended on each run, what the price was then, what the price is now, P&L per recommendation. The "fund as a living thing" requires memory.

**3. Wire v2 into the web app**
v2 has a principled `run_cycle` pipeline — point-in-time correct, one code path for backtest/paper/live. The web app backend exposes `/hedge-fund/run` which today calls the v1 LangGraph DAG. Adding a v2 mode to that endpoint unlocks proper backtesting from the UI.

---

### Tier 2 — Fix data gaps that undermine Indian stock analysis

**4. Indian fundamentals data**
The screener scores valuation, fundamentals, growth — but for Indian stocks, `financialdatasets.ai` returns nothing (US-only). yfinance fills in some gaps but is unreliable. Screener.in has a free API with NSE PE ratios, debt/equity, ROE, etc. This would make the Indian screener actually reliable.

**5. Daily scheduled runs (daemon mode)**
The DB infrastructure exists. A market-calendar cron job that runs the top screener shortlist through the analyst flow every morning at 9:15 AM IST would make this a real daily tool, not a one-shot script. ROADMAP.md lists this as planned but unbuilt.

**6. Kite paper trading**
v2 has a `Broker` protocol. Wire it to Kite's paper order API. Enables "paper before real" — the vision's core promise — and means every analyst recommendation gets a paper trade placed automatically.

---

### Tier 3 — UX / Polish

**7. Onboarding flow**
First-time users face: blank canvas, no API keys configured, no tickers set. A 3-step wizard (pick LLM: Ollama/Gemini/OpenAI → pick market: US/India → add first ticker) would dramatically reduce friction.

**8. Analyst performance tracking**
After N runs, which persona was most accurate? A simple table showing Ben Graham's historical hit rate vs. Warren Buffett's is compelling and educational. The data is in `HedgeFundFlowRun.results` — just needs aggregation.

**9. Thesis persistence**
Each analyst emits a written thesis. Right now it disappears after the run. A "thesis journal" view — scrollable history of every analyst's reasoning per stock per date — is the "explainability" differentiator that makes this more than a black-box signal.

**10. Mobile-responsive screener**
The screener table is not usable on mobile. The screener is the most immediately actionable tool (no flow setup needed) — making it mobile-friendly opens it to a broader audience.

---

## Documentation gaps

| Document | Status |
|---|---|
| VISION.md | Excellent — clear and ambitious |
| ROADMAP.md | Good capability map |
| docs/system-map.md | Good technical reference |
| User guide (how to run, configure LLMs, add stocks) | Missing |
| Indian stocks guide (.NS tickers, Kite setup, screener weights) | Missing |
| How to add a new analyst (contributor guide) | Missing |
| ADR directory | Empty |

---

## Recommended sequencing

```
NOW      Fix IBULLSLTD.NS (update TechnoFunda flow to valid tickers)
         FLW-015: Kite token expiry detection

SPRINT 1 Screener → Flow handoff (one button, biggest UX win)
         P&L dashboard (connects existing runs table to a view)

SPRINT 2 Daily scheduler (daemon mode, market calendar cron)
         Indian fundamentals: Screener.in connector

SPRINT 3 Wire v2 into web app (proper backtest from UI)
         Kite paper trading via v2 Broker protocol

LATER    Onboarding wizard
         Analyst performance tracking / thesis journal
         Mobile screener
```

The single highest-leverage move is **Screener → Flow handoff**. Both features are built; connecting them costs one button in the screener UI and one API call. Everything else in Tier 1 requires new infrastructure.
