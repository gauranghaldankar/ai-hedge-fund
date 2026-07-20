# FLW-001 — Fix Single Run stale/frozen start_date and end_date

**Priority:** Must Have
**Component:** Frontend — `app/frontend/src/nodes/components/portfolio-start-node.tsx`
**Related spec:** `docs/analysis/flow-indian-stock-bugs-pm-report.md` (Bug 1)

---

## Problem Statement

When a user clicks Play in Single Run mode, the dates sent to the backend are computed from a JavaScript `new Date()` call that was evaluated when the component first mounted — not when Play was clicked. If the browser tab has been open for any non-trivial period (or was loaded on a previous calendar day), the `end_date` sent to the backend is in the past. All four analysts receive this stale date window.

For Indian tickers via yfinance (`.NS`, `.BO`), the Technical Analyst receives a price DataFrame that ends days or weeks before today, causing technical indicators to be computed on stale data and, in the worst case, returning empty signals when the date window predates available data.

---

## Root Cause

In `portfolio-start-node.tsx`, the Backtest path correctly reads from reactive state (`startDate`, `endDate`). The Single Run path ignores these state values and uses frozen closure variables:

```tsx
// Lines 49-51: evaluated once at component mount
const today = new Date();
const threeMonthsAgo = new Date(today);
threeMonthsAgo.setMonth(today.getMonth() - 3);

// Lines 248-249: inside handlePlay(), Single Run branch only
start_date: threeMonthsAgo.toISOString().split('T')[0],   // BUG: stale
end_date: today.toISOString().split('T')[0],               // BUG: stale
```

The `startDate` and `endDate` state variables (lines 59-60) that correctly update when the user interacts with the date inputs are never read in the Single Run code path.

---

## Acceptance Criteria

**AC-0201** — When a user triggers a Single Run, the `end_date` sent to `POST /hedge-fund/run` must equal today's actual calendar date at the moment the Play button is clicked, not the date when the component mounted.
- Test: render the component, wait (or mock) a day boundary, click Play, assert the request body's `end_date` equals the mocked "now" date.

**AC-0202** — When a user triggers a Single Run, the `start_date` sent to `POST /hedge-fund/run` must equal exactly 90 days before the `end_date` computed at click time.
- Test: same setup as AC-0201; assert `start_date` is `end_date - 90 days`.

**AC-0203** — The `end_date` computation must not rely on any value captured at component render/mount time. The Play handler must compute dates fresh on each invocation.
- Test: trigger Play twice in the same component lifecycle with a mocked clock advancing between calls; assert both calls send different dates.

**AC-0204** — The fix must not alter the Backtest path. In Backtest mode, `start_date` and `end_date` must continue to read from the user-editable `startDate` / `endDate` state.
- Test: switch to Backtest mode, change the date inputs, click Play, assert the request body contains the user-entered dates unchanged.

**AC-0205** — The default date values shown to the user in the date input fields in Single Run mode must reflect the same "today minus 90 days" to "today" window, and must update if the component re-renders on a new calendar day.
- Test: verify the input field values match the values sent in the request.

---

## Implementation Notes

- The fix is localised to `handlePlay()` in `portfolio-start-node.tsx`. Move the `new Date()` calls inside the `runFlow()` branch so they execute at click time, not at mount time.
- Do not introduce a `useEffect` that updates state on a timer — computing at click time is simpler and correct.
- The `startDate` / `endDate` state is used for Backtest date inputs; the Single Run path should use fresh local variables, not shared state, to avoid coupling the two modes.
- No backend changes required.
