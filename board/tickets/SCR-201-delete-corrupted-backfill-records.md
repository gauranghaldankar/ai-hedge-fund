# SCR-201 — Delete Corrupted Backfill Records

**Type:** Data cleanup
**Priority:** Must-Do
**Spec:** `docs/requirements/kite-migration-backfill-removal.md` § C, Ticket SCR-201
**Blocks:** SCR-205
**Depends on:** Nothing

---

## Summary

Delete all `ScreenerRun` and `ScreenerResult` rows produced by the backfill feature.
These rows have `source='backfill'` and contain all-50.0 composite scores caused by
yfinance rate-limiting (see `docs/analysis/backfill-defect-pm-report.md` for root cause).

No code changes. SQL only.

---

## Steps

1. Locate the SQLite database file (check `app/backend/database/connection.py` for the
   exact file path — typically `app/backend/hedge_fund.db`).
2. Execute in order:

```sql
DELETE FROM screener_results
WHERE run_id IN (
  SELECT id FROM screener_runs WHERE source = 'backfill'
);

DELETE FROM screener_runs WHERE source = 'backfill';
```

3. Run verification queries (see ACs below).

---

## Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-SCR-201a | `SELECT COUNT(*) FROM screener_runs WHERE source='backfill'` returns 0 |
| AC-SCR-201b | `SELECT COUNT(*) FROM screener_results WHERE run_id NOT IN (SELECT id FROM screener_runs)` returns 0 (no orphaned result rows) |
| AC-SCR-201c | `SELECT COUNT(*) FROM screener_runs WHERE source='manual'` returns the same count as before the operation |
