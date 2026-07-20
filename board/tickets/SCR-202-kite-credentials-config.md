# SCR-202 — Kite Credentials Config Module

**Type:** New module
**Priority:** Must-Do
**Spec:** `docs/requirements/kite-migration-backfill-removal.md` § C, Ticket SCR-202; § B Decision 3
**Depends on:** Nothing
**Blocks:** SCR-203, SCR-204

---

## Summary

Create `src/config/kite_config.py` to load Kite Connect credentials from environment
variables with a documented fallback to the OCE project's daily token file.

---

## Files to Create

- `src/config/__init__.py` (empty, only if the directory does not already exist)
- `src/config/kite_config.py`

---

## Behavior Contract

Public function: `get_kite_config() -> dict`

Return value shape: `{"api_key": str | None, "access_token": str}`

Resolution order:
1. `KITE_API_KEY` from `os.environ`. `None` if absent.
2. `KITE_ACCESS_TOKEN` from `os.environ`. If absent, read from
   `~/workspace/Intraday/secrets/access_token.txt`. If still absent, return `""`.

Logging:
- Log `WARNING` when the access token is sourced from the fallback file path.
- Log `WARNING` when `api_key` is `None` (Kite not configured).

Dependencies: stdlib only (`os`, `pathlib`, `logging`). No `kiteconnect` import here.

---

## Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-SCR-202a | `get_kite_config()` returns `{"api_key": None, "access_token": ""}` when no env vars are set and the fallback file does not exist |
| AC-SCR-202b | `get_kite_config()` returns the env var value for `KITE_API_KEY` when the var is set |
| AC-SCR-202c | `get_kite_config()` reads `KITE_ACCESS_TOKEN` from `~/workspace/Intraday/secrets/access_token.txt` when the env var is absent and the file exists |
| AC-SCR-202d | A `WARNING` is logged when the fallback file path is used |
| AC-SCR-202e | The module is importable with no external dependencies beyond stdlib |
