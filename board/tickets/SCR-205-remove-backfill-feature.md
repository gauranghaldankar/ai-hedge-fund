# SCR-205 — Remove Backfill Feature (Backend + Frontend)

**Type:** Feature removal
**Priority:** Must-Do
**Spec:** `docs/requirements/kite-migration-backfill-removal.md` § C, Ticket SCR-205; § D AC-0115 Disposition
**Depends on:** SCR-201 (corrupted DB records must be deleted first)
**Can run in parallel with:** SCR-202, SCR-203, SCR-204

---

## Summary

Remove the backfill feature entirely: backend endpoint, Pydantic model, holidays module,
and all frontend state/components related to the "Backfill 7 Days" button.

AC-0115 is formally deviated (see `docs/requirements/kite-migration-backfill-removal.md` § D).

---

## Files to Modify / Delete

### Backend

**`app/backend/routes/screener.py`**
- Delete `BackfillRequest` Pydantic model (lines 55–57).
- Delete `trigger_backfill()` handler and its entire `event_generator()` closure (lines 297–449).
- Remove the `POST /screener/backfill` route decorator.
- Update the module-level docstring to remove the `POST /screener/backfill` line.

**`src/screener/holidays.py`** (conditional)
- Grep for any import of `holidays` from `src/screener/` outside of `routes/screener.py`.
- If no other consumer: delete the file.
- If another consumer exists: do not delete; leave as dead code and note in the PR.

### Frontend

**`app/frontend/src/services/screener-service.ts`**
- Remove `triggerBackfill()` function.
- Remove `BackfillSSEEvent` type export.
- Remove any imports made unused by these deletions.

**`app/frontend/src/components/screener/types.ts`**
- Remove `BackfillSSEEvent` type definition.

**`app/frontend/src/components/screener/ScreenerPage.tsx`**
- Remove `isBackfilling` state, `backfillDay` state, `cancelBackfillRef` ref.
- Remove `handleBackfill` callback.
- Remove `isBackfilling` and `onBackfill` props passed to `ScreenerToolbar`.
- Remove `backfill` prop passed to `ScreenerRunProgress`.
- Remove `BackfillSSEEvent` import.

**`app/frontend/src/components/screener/ScreenerToolbar.tsx`**
- Remove `isBackfilling` and `onBackfill` from the props interface.
- Remove the "Backfill 7 Days" button block (the comment through the closing `</Button>` tag).
- Remove `isBackfilling` from the `disabled` expression on the "Run Screener" button.

**`app/frontend/src/components/screener/ScreenerRunProgress.tsx`**
- Remove `BackfillContext` interface.
- Remove `backfill` prop from `ScreenerRunProgressProps` and component signature.
- Remove the `title` ternary referencing `backfill`; replace with a static string.

---

## Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-SCR-205a | `POST /screener/backfill` returns HTTP 404 or 405 after the change |
| AC-SCR-205b | All 6 surviving screener endpoints return correct responses (smoke test: `GET /screener/runs`, `POST /screener/run`, `GET /screener/runs/{id}/results`, `GET /screener/runs/{id}/results/{ticker}`, `POST /screener/ticker`, `GET /screener/constituents`) |
| AC-SCR-205c | The "Backfill 7 Days" button is absent from the Screener toolbar in the frontend |
| AC-SCR-205d | The frontend TypeScript compiles with zero errors after removal |
| AC-SCR-205e | `ScreenerToolbar` renders without errors when `isBackfilling` and `onBackfill` are not passed |
| AC-SCR-205f | Grep for `BackfillSSEEvent` and `triggerBackfill` returns zero matches in the frontend `src/` directory |
| AC-0122 | The History dropdown (AC-0113) renders an empty state or "No historical data yet" message when no manual runs exist in the database |
