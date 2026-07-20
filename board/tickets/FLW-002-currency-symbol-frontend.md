# FLW-002 — Display correct currency symbol in Investment Report and Portfolio Start Node

**Priority:** Must Have
**Component:** Frontend — `app/frontend/src/nodes/components/investment-report-dialog.tsx`, `portfolio-start-node.tsx`
**Related spec:** `docs/analysis/flow-indian-stock-bugs-pm-report.md` (Bug 2)

---

## Problem Statement

All monetary values displayed in the Flows UI use a hardcoded `$` (US Dollar) symbol regardless of the stock's actual currency. For Indian tickers (SGFIN.NS), prices and market caps are denominated in INR (Indian Rupee, ₹). The current display of `$120.50` for a stock priced at ₹120.50 is factually wrong and could mislead trading decisions.

The `currency` field is correctly populated by `src/tools/yf_api.py` (line 163 sets `currency=ig("currency") or "INR"` on `FinancialMetrics`). The currency code is available in the data already delivered to the frontend via `analyst_signals`. The defect is that the rendering layer never reads it.

---

## Root Cause

**Hardcoded `$` in Investment Report dialog (`investment-report-dialog.tsx`, line 145):**

```tsx
<TableCell>
  ${typeof currentPrice === 'number' ? currentPrice.toFixed(2) : currentPrice}
</TableCell>
```

The `$` is a string literal. `current_prices` in the response payload contains no currency metadata.

**Hardcoded `$` in Portfolio Start Node inputs (`portfolio-start-node.tsx`, lines 282 and 326):**

```tsx
<div className="absolute left-3 ...">$</div>  {/* Available Cash */}
<div className="absolute left-3 ...">$</div>  {/* Trade Price per position */}
```

These are always `$` regardless of the ticker(s) entered.

---

## Acceptance Criteria

**AC-0206** — In the Investment Report dialog Price column, when all tickers in the run are Indian (`.NS` or `.BO` suffix), the currency symbol displayed must be `₹`, not `$`.
- Test: render InvestmentReportDialog with `current_prices: { "SGFIN.NS": 120.50 }` and assert the rendered Price cell reads `₹120.50`.

**AC-0207** — In the Investment Report dialog Price column, when all tickers are US tickers (no dot-exchange suffix), the currency symbol must remain `$`.
- Test: render with `current_prices: { "AAPL": 190.00 }` and assert the cell reads `$190.00`.

**AC-0208** — The currency symbol determination must be based on the ticker string(s) available at render time, not on a hardcoded constant, and must not require a new API call.
- Test: verify no additional fetch is triggered during rendering.

**AC-0209** — The "Available Cash" input in the Portfolio Start Node must display a currency symbol/label that reflects the primary ticker's exchange. For Indian tickers, it must show `₹`; for US tickers, it must show `$`. If multiple tickers from different exchanges are entered, the label must be neutral (e.g., an empty prefix or "Amount").
- Test: enter `SGFIN.NS` as the first ticker; assert the Available Cash prefix shows `₹`. Enter `AAPL`; assert it shows `$`. Enter `SGFIN.NS, AAPL`; assert no currency symbol is shown.

**AC-0210** — The "Price" column input in each portfolio position row must apply the same currency symbol logic as AC-0209, driven by the ticker entered in that same row.
- Test: enter ticker `SGFIN.NS` in a position row; assert its Price input prefix shows `₹`.

**AC-0211** — The currency detection logic must be implemented as a shared utility function (e.g., `getCurrencySymbol(ticker: string): string`) so it can be reused across both components without duplication.
- Test: unit test the utility with `.NS`, `.BO`, `.BSE`, and plain US tickers.

---

## Implementation Notes

- A simple utility is sufficient: if `ticker.toUpperCase().endsWith(".NS") || ticker.endsWith(".BO") || ticker.endsWith(".BSE")` return `"₹"`, else return `"$"`. No external call needed.
- For the Investment Report dialog, detect the currency from the ticker key(s) in `outputNodeData.current_prices`. If all tickers are Indian, use `₹`. If mixed, use a neutral label or show per-row.
- For the Portfolio Start Node, detect from the first position's ticker and reactively update as the user types.
- The `analyst_signals` payload already carries `currency: "INR"` on `FinancialMetrics` objects; the frontend could alternatively read from there, but the ticker-suffix approach avoids parsing nested data.
- Do not modify backend schemas or agents in this ticket (backend currency propagation is addressed separately in FLW-003).
