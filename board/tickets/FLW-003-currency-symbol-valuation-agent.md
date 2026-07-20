# FLW-003 — Fix USD symbol hardcoded in Valuation Agent reasoning strings

**Priority:** Should Have
**Component:** Backend — `src/agents/valuation.py`
**Related spec:** `docs/analysis/flow-indian-stock-bugs-pm-report.md` (Bug 2, backend layer)

---

## Problem Statement

The Valuation Agent constructs human-readable reasoning strings that are embedded in the response payload and rendered verbatim in the Investment Report dialog and the Analysis tab. These strings contain hardcoded `$` prefixes on all monetary values. For Indian tickers, the underlying figures are INR-denominated (yfinance returns all `.NS` ticker data in INR), but the strings read `$1,234.00` instead of `₹1,234.00`.

This is a backend defect separate from the frontend rendering fix in FLW-002. Even after FLW-002 is applied, the valuation reasoning text blocks will still display `$` because they are pre-formatted strings produced by the agent.

---

## Root Cause

In `src/agents/valuation.py`, three distinct string templates use `$` as a literal prefix:

**Lines 171-173 (base_details, built for every valuation method):**

```python
base_details = (
    f"Value: ${vals['value']:,.2f}, Market Cap: ${market_cap:,.2f}, "
    f"Gap: {vals['gap']:.1%}, Weight: {vals['weight']*100:.0f}%"
)
```

**Lines 178-181 (enhanced DCF details):**

```python
enhanced_details = (
    f"{base_details}\n"
    f"  WACC: {wacc:.1%}, Bear: ${dcf_results['downside']:,.2f}, "
    f"Bull: ${dcf_results['upside']:,.2f}, Range: ${dcf_results['range']:,.2f}"
)
```

**Lines 196-198 (DCF scenario summary):**

```python
reasoning["dcf_scenario_analysis"] = {
    "bear_case": f"${dcf_results['downside']:,.2f}",
    "base_case": f"${dcf_results['scenarios']['base']:,.2f}",
    "bull_case": f"${dcf_results['upside']:,.2f}",
    ...
}
```

The `currency` field is available from `most_recent_metrics.currency` (populated by `yf_api.get_financial_metrics()` which reads `t.info["currency"]`). It is never read in `valuation.py`.

---

## Acceptance Criteria

**AC-0212** — When `valuation_analyst_agent` runs against an Indian ticker (`.NS`), the reasoning strings in `valuation_analysis[ticker]["reasoning"]` must use `₹` as the currency prefix, not `$`.
- Test: run `valuation_analyst_agent` with a mocked state containing SGFIN.NS data where `most_recent_metrics.currency == "INR"`; assert all dollar signs in the reasoning output have been replaced by `₹`.

**AC-0213** — When `valuation_analyst_agent` runs against a US ticker (no exchange suffix), the reasoning strings must continue to use `$`.
- Test: run with `most_recent_metrics.currency == "USD"`; assert `$` is present in reasoning strings.

**AC-0214** — The currency symbol selection must derive from `most_recent_metrics.currency` (the value returned by `get_financial_metrics()` for that ticker), not from a hardcoded mapping of ticker suffixes.
- Test: mock `most_recent_metrics.currency = "GBP"` and assert the symbol `£` (or the raw currency code if no symbol mapping exists) appears rather than `$`.

**AC-0215** — The fix must be confined to `src/agents/valuation.py`. No other agent files, schemas, or tests should require changes for this ticket.
- Test: run the full pytest suite (`poetry run pytest tests/`) and confirm no regressions outside the valuation agent test file.

---

## Implementation Notes

- Read the currency from `most_recent_metrics.currency` early in the ticker loop and derive a symbol. A minimal mapping (`{"USD": "$", "INR": "₹", "GBP": "£", "EUR": "€"}`) with a fallback to the raw code (e.g., `"JPY 1234.00"`) is sufficient. Do not over-engineer this.
- Replace the three `f"${...}"` template occurrences with `f"{currency_symbol}{...}"`.
- The `FinancialMetrics` model field `currency` is already populated correctly by `yf_api.py`; no changes to the data layer are needed.
- Write or extend the existing valuation agent test to cover both INR and USD currency paths.
