# Requirements: Persist and Restore Last Flow Run Results

**Date:** 2026-07-20
**Author:** Product Manager (AgentCo)
**Status:** Ready for engineering
**AC range:** AC-0234 through AC-0249
**Linked source:** Feature brief — "Persist and restore last flow run results"

---

## A. Problem Statement

When a user runs a hedge fund flow (e.g., Data Wizards swarm analyzing SGFIN.NS, RELIANCE.NS), the results — analyst signals, portfolio decision, trade recommendations — are displayed in the UI but are held only in React memory. Closing the browser tab or refreshing the page loses every output. The user must wait for a full re-run to see the same results again.

The DB schema, repository, and REST routes to persist and retrieve runs already exist (`HedgeFundFlowRun`, `FlowRunRepository`, `/flows/{flow_id}/runs/latest`) but are never wired to the execution path. This is a pure wiring gap — no schema changes are required.

---

## B. User Personas

**Solo Founder / Trader** — the single user of this system. Runs the flow manually, inspects results, closes the laptop, returns the next morning, and expects the most recent analysis to be pre-populated without forcing a re-run.

---

## C. User Stories

**US-01 — Automatic result persistence on run complete**
As a solo founder, I want the results of each flow run to be automatically saved to the database when the run completes, so that the output is not lost if I close the tab or refresh the page.

**US-02 — Automatic result restoration on flow open**
As a solo founder, when I open a saved flow (via the flow picker or browser refresh), I want the results of the most recent completed run to be displayed immediately without having to re-run the flow, so that I can review yesterday's signals without waiting for a new LLM run.

**US-03 — No action required from the user**
As a solo founder, I want the persist and restore behavior to be fully automatic — no extra button to press, no explicit "save results" step — so that the workflow remains frictionless.

**US-04 — No stale results from runs in progress or failed runs**
As a solo founder, I do not want to see partial or error-state results restored on page load. Only the results of the most recent COMPLETE run should be restored.

---

## D. Acceptance Criteria

### Backend — Persistence on Run Complete

**AC-0234** — When `POST /hedge-fund/run` receives a `flow_id` in the request body, it calls `FlowRunRepository.create_flow_run(flow_id, request_data)` before starting the graph execution. The created run has `status=IN_PROGRESS` and `started_at` set.

**AC-0235** — When the graph execution completes successfully (the `CompleteEvent` is about to be yielded), the run's `status` is updated to `COMPLETE`, `completed_at` is set, and `results` is stored as the JSON object: `{"decisions": {...}, "analyst_signals": {...}, "current_prices": {...}}`. This update uses `FlowRunRepository.update_flow_run()`.

**AC-0236** — When the graph execution fails or the SSE generator's `except` branch fires, the run's `status` is updated to `ERROR` and `error_message` is set to the exception string.

**AC-0237** — When `POST /hedge-fund/run` is called without a `flow_id` (field absent or `null`), the endpoint behaves exactly as today: no DB write is performed and the stream proceeds normally. The field is optional and backward-compatible.

**AC-0238** — The `flow_id` field on `HedgeFundRequest` is `Optional[int]` defaulting to `None`. No existing call site that omits `flow_id` raises a validation error.

### Backend — Latest Run Retrieval

**AC-0239** — `GET /flows/{flow_id}/runs/latest` returns the most recent run record (ordered by `created_at` descending) regardless of status. If the most recent run has `status=COMPLETE`, the `results` field in the response contains the full output JSON. If no run exists, the endpoint returns `null` with HTTP 200.

**AC-0240** — `GET /flows/{flow_id}/runs/latest` returns HTTP 404 if the `flow_id` does not correspond to a saved flow. (This behavior already exists in `flow_runs.py`; this AC confirms it is not broken by the changes in FLW-008.)

### Frontend — Service Layer

**AC-0241** — `flow-service.ts` exports a `getLatestFlowRun(flowId: number)` method that calls `GET /flows/{flowId}/runs/latest` and returns the parsed `FlowRunResponse` object, or `null` if the response body is `null`.

**AC-0242** — `flow-service.ts` exports a `FlowRunResponse` TypeScript interface matching the backend schema: `id`, `flow_id`, `status`, `run_number`, `created_at`, `started_at`, `completed_at`, `results`, `error_message`.

### Frontend — Run Start: pass flow_id

**AC-0243** — When `runFlow()` is called in `use-flow-connection.ts`, the `flowId` (already available as a string in that hook) is included in the params object passed to `api.runHedgeFund()` as `flow_id: number | null`. `flowId` is converted from string to integer; if the string is not a valid integer the field is omitted.

**AC-0244** — `api.ts` includes `flow_id` in the JSON body serialized to `POST /hedge-fund/run`. No change is required to the SSE stream-reading logic.

### Frontend — Restore on Flow Load

**AC-0245** — In `flow-context.tsx`, after the nodes/edges/viewport are restored in `loadFlow()`, the function calls `flowService.getLatestFlowRun(flow.id)`. If the returned run has `status === "COMPLETE"` and `run.results` is non-null, it calls `nodeContext.setOutputNodeData(flow.id.toString(), run.results)` to replay the output into the UI.

**AC-0246** — If `getLatestFlowRun` returns `null` (no prior run), returns a non-COMPLETE run, or throws a network error, `loadFlow()` completes normally with no error surfaced to the user. The flow canvas loads as usual with no results pre-populated.

**AC-0247** — The restored results render in the output node (and any other node that consumes `outputNodeData`) identically to how they appear immediately after a live run completes. No visual difference is observable between a restored and a freshly-run result.

**AC-0248** — After restoration, the "Run" button is enabled (not in a loading/processing state). The restored results are read-only display; the user can trigger a fresh run at any time.

### Authorization

**AC-0249** — There is no multi-user authorization requirement for this feature. The single founder has implicit ALLOW on all flow run operations (create, read, update). No role-gating is required.

---

## E. Out of Scope

- Persisting intermediate progress events (the per-agent `ProgressUpdateEvent` SSE stream). Only the final `CompleteEvent` data is stored.
- Restoring the per-agent node status indicators (IN_PROGRESS/COMPLETE badges on each analyst node). Only the output node data is restored.
- Backtest run persistence. The backtest path (`POST /hedge-fund/backtest`) is excluded from this feature. A separate ticket can address it when needed.
- Run history UI (a list of past runs with navigation between them). This feature restores only the most recent COMPLETE run.
- Automatic re-run scheduling. The founder triggers runs manually.
- Deleting or expiring old run records. No retention policy is set by this feature.
- Multi-user access control. This is a single-founder tool.

---

## F. Data Model Notes

### What is stored

The `HedgeFundFlowRun.results` JSON column (already exists, `nullable=True`) stores the exact payload of the `CompleteEvent.data` dict:

```
{
  "decisions": {
    "<ticker>": {
      "action": "BUY" | "SELL" | "HOLD",
      "quantity": <int>,
      "confidence": <float 0–1>,
      "reasoning": "<string>"
    },
    ...
  },
  "analyst_signals": {
    "<analyst_key>": {
      "<ticker>": {
        "signal": "bullish" | "bearish" | "neutral",
        "confidence": <float>,
        "reasoning": "<string>"
      }
    },
    ...
  },
  "current_prices": {
    "<ticker>": <float>,
    ...
  }
}
```

`request_data` stores the serialized `HedgeFundRequest` body (tickers, graph nodes/edges, model config) so the run is reproducible. The `flow_id` FK links it to the `HedgeFundFlow` record.

### What is NOT stored

- Streaming progress events (per-agent status during execution).
- LangGraph internal state or intermediate messages.
- Per-agent node UI state (node colors, expand/collapse).

### Restore contract

The frontend replays `run.results` directly into `nodeContext.setOutputNodeData(flowId, run.results)`. This is the same call that `api.ts` makes on line 197 after receiving the live `complete` SSE event. The restore path and the live-run path are identical from the `nodeContext` perspective.

---

## G. Persona x Flow Coverage Table (Validation Review)

| Flow | Persona | Covered by ACs | Status |
|---|---|---|---|
| Run flow; results appear in output node | Founder | AC-0234, AC-0235, AC-0243, AC-0244, AC-0247 | Covered |
| Re-open flow next day; results pre-populated | Founder | AC-0241, AC-0245, AC-0247 | Covered |
| Run flow without saving flow first (no flow_id) | Founder | AC-0237, AC-0238 | Covered |
| Flow run errors; error recorded, no stale output restored | Founder | AC-0236, AC-0246 | Covered |
| No prior run exists; flow loads with blank canvas | Founder | AC-0246 | Covered |
| Restore shows only COMPLETE results, not IN_PROGRESS or ERROR | Founder | AC-0245, AC-0246 | Covered |
| User triggers fresh run after restore | Founder | AC-0248 | Covered |
| Authorization — who can access run results | Founder | AC-0249 | Covered (single user, no auth) |

No TBD rows. All flows have at least one covering AC.

---

## H. MoSCoW Priority

| Story | Priority | Rationale |
|---|---|---|
| US-01 Persist results | Must | Without this, US-02 is impossible. Zero DB writes currently happen. |
| US-02 Restore on open | Must | This is the core user value: no re-run required on refresh. |
| US-03 No user action needed | Must | Explicit save steps add friction that defeats the purpose. |
| US-04 No stale results | Must | Displaying partial/error results would mislead the founder on investment decisions. |

---

## I. Release Milestone

**M1 (this slice):** All Must ACs above, implemented across FLW-008 through FLW-012. One founder + agents can ship in a single session. No schema migrations required — DB tables exist.
