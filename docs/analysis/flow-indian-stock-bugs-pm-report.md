# PM Report: Flow Feature Bugs — Indian Stock (SGFIN.NS) Run

**Date:** 2026-07-20
**Reporter:** Product Manager (AgentCo)
**Scope:** Flows feature, "Data Wizards" swarm (Technical Analyst, Fundamentals Analyst, Sentiment Analyst, Valuation Analyst -> Portfolio Manager) with ticker SGFIN.NS
**Bugs:** BUG-1 Stale/missing data, BUG-2 Currency displayed in USD instead of INR

---

## 1. Summary of Findings

Two independent defects were confirmed through code inspection. Neither is speculative — each has a precise, traceable code location.

| Bug | Severity | Category | Root Cause Location |
|---|---|---|---|
| BUG-1: Stale/missing price data in single-run mode | High | Data freshness | `app/frontend/src/nodes/components/portfolio-start-node.tsx` line 249 |
| BUG-2: USD symbol hardcoded throughout output layer | Medium | Localisation | `src/agents/valuation.py` lines 171-199; `app/frontend/src/nodes/components/investment-report-dialog.tsx` line 145; `app/frontend/src/nodes/components/portfolio-start-node.tsx` lines 282, 326 |

---

## 2. Bug 1 — Stale / Missing Data

### 2.1 Observed symptom

When a user runs the "Data Wizards" swarm against SGFIN.NS in Single Run mode, the output either shows no price data, reflects stale prices from 90 days ago rather than the current trading day, or the Technical Analyst returns empty signals.

### 2.2 Root cause analysis

**Primary defect — dates frozen at component-mount time (Single Run path)**

`portfolio-start-node.tsx` computes `today` and `threeMonthsAgo` once at the top of the render function (lines 49-51) and then reads those frozen values when building the `runFlow()` call:

```tsx
// Lines 49-51 — computed once at component load:
const today = new Date();
const threeMonthsAgo = new Date(today);
threeMonthsAgo.setMonth(today.getMonth() - 3);

// Lines 248-249 inside handlePlay() — these are NOT the user-editable
// startDate / endDate state values; they are the frozen closure variables:
start_date: threeMonthsAgo.toISOString().split('T')[0],
end_date: today.toISOString().split('T')[0],
```

The date input controls (`startDate`, `endDate` state) that the user sees on screen are wired only to the Backtest path (lines 224-225). In the Single Run path the code ignores the user state and uses the frozen closure values. If the browser tab has been open for multiple days, or the page was loaded on a different date, the effective `end_date` is wrong.

Crucially, the `HedgeFundRequest` schema in `app/backend/models/schemas.py` (line 132) defaults `end_date` to `datetime.now()` server-side only when the field is absent. Because the frontend always sends an explicit `end_date`, the server-side default never fires. The frontend date is therefore always authoritative, and a stale date on the frontend means stale data throughout.

**Secondary defect — in-memory cache key mismatch causes cache hits on wrong date windows**

`src/data/cache.py` stores data keyed by a plain ticker string (e.g., `get_prices(ticker)`), but `src/tools/yf_api.py` constructs keys including dates (e.g., `yf_{ticker}_{start_date}_{end_date}`). The cache getter signature in `cache.py` accepts only a single `ticker` string argument — it is not date-aware:

```python
# cache.py
def get_prices(self, ticker: str) -> list[dict] | None:
    return self._prices_cache.get(ticker)
```

But yf_api.py calls it as:
```python
cache_key = f"yf_{ticker}_{start_date}_{end_date}"
_cache.get_prices(cache_key)   # key is the compound string
```

The Cache class stores data merged under whatever string is passed as the key. Because different calls use different compound keys, a cache "miss" triggers a fresh yfinance download — but the data stored in the first miss goes under the compound key, not the plain ticker. A later call with a different date window creates an entirely separate entry. There is no TTL on the in-memory cache; data lives for the lifetime of the server process. If the server was started days ago and the cache for `yf_SGFIN.NS_<old_dates>` is populated, a new call with different dates will simply bypass it and re-fetch — which is actually correct behaviour in isolation, but it means there is no cache benefit and, more importantly, no mechanism to invalidate stale entries even if the key accidentally collides.

**Tertiary defect — yfinance `end_date` is exclusive**

`yf.download(ticker, start=start_date, end=end_date)` treats `end_date` as exclusive (yfinance convention). So when the frontend sends `end_date = today` (e.g., `2026-07-20`), yfinance returns data up to and including `2026-07-19`. The most recent trading day's close is silently excluded. For Indian NSE tickers the last available close is therefore always the previous session, which is correct market behaviour (today's session may not have closed), but when the `end_date` is already stale due to the frontend bug above, the data gap compounds.

### 2.3 Data flow trace

```
User clicks Play (Single Run)
  -> handlePlay() in portfolio-start-node.tsx
  -> runFlow({ start_date: threeMonthsAgo, end_date: today })   # frozen at component mount
  -> POST /hedge-fund/run with HedgeFundRequest
  -> run_graph_async() -> run_graph()
  -> LangGraph state["data"]["start_date"] / ["end_date"]
  -> technical_analyst_agent() calls get_prices(ticker, start_date, end_date)
  -> api.py _is_yf_ticker("SGFIN.NS") == True -> yf_api.get_prices()
  -> yf.download(ticker, start=start_date, end=end_date)   # end is exclusive
  -> returns prices up to (end_date - 1 day)
```

If the browser was loaded on a previous date or the tab stayed open overnight, `today` in the closure is that old date, not the actual current date.

### 2.4 User impact

- The Technical Analyst receives a price DataFrame whose latest row may be days or weeks old, causing all technical indicators (EMAs, RSI, momentum) to be computed on stale data.
- If the date window is so old that SGFIN.NS had low volume or was halted, the DataFrame may be empty, causing the agent to emit no signal at all.
- The Fundamentals and Valuation agents use `end_date` to filter financial metrics. An old `end_date` can cause yfinance to return an older snapshot of `t.info`, though in practice yfinance's `.info` is always live — so these agents are less affected by this specific bug.
- The user has no visible warning that the dates being used are stale.

---

## 3. Bug 2 — Currency Displayed in USD Instead of INR

### 3.1 Observed symptom

All monetary values in the flow output — stock price in the Investment Report dialog, valuation model outputs (DCF value, market cap, owner earnings value), and the "Available Cash" and "Price" inputs in the Portfolio Start Node — display the `$` symbol regardless of the stock being analysed.

### 3.2 Root cause analysis

The currency symbol is hardcoded in four distinct locations. There is no currency-detection or locale-switching logic anywhere in the rendering pipeline.

**Location 1: `investment-report-dialog.tsx` line 145 — Price column**

```tsx
<TableCell>
  ${typeof currentPrice === 'number' ? currentPrice.toFixed(2) : currentPrice}
</TableCell>
```

The `$` is a string literal concatenated before the price value. For SGFIN.NS, `currentPrice` is in INR (values like 120.50 rupees), but the cell renders `$120.50`.

**Location 2: `src/agents/valuation.py` lines 171-180 — reasoning strings**

```python
base_details = (
    f"Value: ${vals['value']:,.2f}, Market Cap: ${market_cap:,.2f}, "
    f"Gap: {vals['gap']:.1%}, Weight: {vals['weight']*100:.0f}%"
)
enhanced_details = (
    f"{base_details}\n"
    f"  WACC: {wacc:.1%}, Bear: ${dcf_results['downside']:,.2f}, "
    f"Bull: ${dcf_results['upside']:,.2f}, Range: ${dcf_results['range']:,.2f}"
)
```

These strings are embedded in the `reasoning` dict that flows to the frontend and is rendered verbatim in the Investment Report dialog and the bottom panel's Analysis section. For SGFIN.NS, the intrinsic values are in INR crores (yfinance returns INR-denominated figures for `.NS` tickers), but the text says `$`.

**Location 3: `src/agents/valuation.py` lines 196-200 — DCF scenario summary**

```python
reasoning["dcf_scenario_analysis"] = {
    "bear_case": f"${dcf_results['downside']:,.2f}",
    "base_case": f"${dcf_results['scenarios']['base']:,.2f}",
    "bull_case": f"${dcf_results['upside']:,.2f}",
    ...
}
```

Same issue — `$` prefix on INR-denominated values.

**Location 4: `portfolio-start-node.tsx` lines 281-283, 325-327 — UI inputs**

```tsx
<div className="absolute left-3 ...">$</div>  {/* Available Cash */}
...
<div className="absolute left-3 ...">$</div>  {/* Trade Price per position */}
```

These are cosmetic but misleading: when a user enters a position in SGFIN.NS at ₹120, the input shows `$120`.

**What yf_api.py does correctly**

`src/tools/yf_api.py` correctly reads `currency` from `t.info` and stores it in `FinancialMetrics.currency` and `LineItem.currency` (lines 163, 380). The data model carries the right currency code (`"INR"`). The defect is that nothing downstream reads `currency` to select the correct symbol — neither the valuation agent's reasoning strings nor the frontend rendering layer.

### 3.3 Data flow trace

```
yf_api.get_financial_metrics("SGFIN.NS", ...)
  -> FinancialMetrics(currency="INR", market_cap=<INR value>, ...)
  -> stored in state["data"]["analyst_signals"]

valuation_analyst_agent()
  -> builds reasoning strings with literal "$" prefix
  -> emits: { "dcf_analysis": { "details": "Value: $1234.00, ..." } }

frontend investment-report-dialog.tsx
  -> renders signal.reasoning verbatim (JSON block)
  -> renders currentPrice as "$120.50"
```

The `currency` field on `FinancialMetrics` and `LineItem` is never read by any agent or by any frontend component.

### 3.4 User impact

- Every monetary figure in the Investment Report shows `$` for an INR-denominated stock, which is factually wrong and potentially misleading for trading decisions.
- The Portfolio Start Node inputs suggest cash and trade prices are in USD, creating confusion when the user enters rupee amounts.
- The Valuation Agent's DCF output (which does the heaviest currency-denominated work) is the most visible manifestation.

---

## 4. MoSCoW Prioritisation

| Ticket | Description | Priority | Rationale |
|---|---|---|---|
| FLW-001 | Fix Single Run start/end dates (frozen closure bug) | Must Have | Silent data staleness; users can't trust any analysis result |
| FLW-002 | Expose currency symbol from data layer to rendering | Must Have | Incorrect currency symbol on every Indian stock run |
| FLW-003 | Propagate currency to valuation agent reasoning strings | Should Have | Backend strings are embedded in reports; fixing FLW-002 alone leaves backend strings broken |
| FLW-004 | Cache: add TTL and date-aware key invalidation | Should Have | Prevents accidental stale-cache hits after server restarts; lower urgency than FLW-001 |

---

## 5. Out of Scope

- General yfinance data quality for SGFIN.NS (illiquidity, delayed NSE feed) — separate data concern.
- INR formatting conventions (lakh/crore separators) — acceptable as a follow-on enhancement.
- Backtest mode date handling — dates are correctly wired to user state in the backtest path; only Single Run is broken.

---

## 6. Open Questions for Founder

1. Should "Available Cash" and trade price inputs in the Portfolio Start Node switch their currency symbol based on the tickers entered, or is a generic neutral label (e.g., "Amount") sufficient?
2. For the Valuation Agent's reasoning strings: should INR values use Indian numbering (lakhs/crores) or standard international notation?
3. Should the Investment Report header show the detected currency prominently (e.g., "All values in INR")?

---

## 7. Validation Coverage Table

| Persona | Flow | Covered by tickets? |
|---|---|---|
| Retail investor running SGFIN.NS single run | Dates are current, data is fresh | FLW-001 |
| Retail investor reading Investment Report price | Price shows ₹ not $ | FLW-002 |
| Retail investor reading Valuation Agent reasoning | DCF values show ₹ | FLW-003 |
| Investor entering portfolio position | Cash/price inputs show ₹ | FLW-002 |
| Investor re-running after hours | Fresh yfinance data, no stale cache | FLW-004 |

All rows resolved by the four tickets. No TBD rows remain pending founder resolution of the open questions above (cosmetic only, do not block development).
