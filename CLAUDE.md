# ai-hedge-fund — maintained with AgentCo

> Agents and skills load from the global install (~/.claude/agents, ~/.claude/skills).
> This file carries AgentCo's operating principles plus this project's specifics.

<!-- ===== AgentCo operating principles ===== -->
## Operating principles
1. One human is accountable: the founder. Agents produce and recommend; the founder decides at every approval boundary.
2. Deterministic gates over trust. Mechanical quality is enforced by `scripts/gate.sh` and CI, not by an agent's say-so.
3. Separation of duties. Reviewers and security are READ-ONLY; they never edit the code they judge.
4. Small slices. Ship the smallest vertical slice that passes the gate, then the next.
5. Decisions are recorded. Non-trivial choices get an ADR. No silent architecture.
6. Loops are bounded. Every correction loop has a termination condition and a retry cap; on exhaustion, stop and escalate to the founder.
7. Doubt non-trivial decisions in-flight. Before branching logic, cross-boundary changes, unprovable claims, or irreversible actions stand, apply the doubt-driven skill — a fresh-context skeptic biased to disprove. This runs DURING the work and never replaces the post-hoc gates.
8. Verify AND validate. The gate proves "did we build it right" — tests pass, coverage met, green. The validation-review proves "did we build the right thing" — every persona and flow the vision implies has ACs, including per-role authorization and per-role E2E smoke. A green gate on an incomplete spec is a false signal.

## APPROVAL BOUNDARIES — always stop and ask the founder
- Merging to `main`
- Deploying to production
- Spending money / committing to costs
- Reading, writing, or rotating secrets
- Signing or sending anything legal, financial, or contractual

## Definition of Done (a slice)
- Acceptance criteria are tested and pass
- `scripts/gate.sh` is green
- code-reviewer returned APPROVE (mandatory; waiver requires founder sign-off with reason in BUILD_SUMMARY — 'inline review by engineer' is not a waiver)
- no open Critical/High security findings
- docs updated if behavior changed
- for user-facing surface (new/changed routes, screens): docs-coverage is green (`python3 scripts/docs-coverage.py --project <p>`) — undocumented public surface is not done
- `<project>/BUILD_SUMMARY.md` written by release-manager (agents used/not used, artifacts, gate results, open items, cost)

## Loop policy (bounded loops)
AgentCo runs correction loops: implement → gate → fix → re-gate; review → fix → re-review; eval → fix → re-eval. Loops cost tokens (and your usage window) on every turn, and an unbounded loop can spin forever or quietly "succeed" by lowering the bar. So every loop is bounded:

- **Termination = the check passes**, not "the agent feels done." Green gate, APPROVE, or eval-threshold met ends the loop. Nothing else does.
- **Retry cap: 3 attempts** per loop by default (override with `GATE_MAX_RETRIES`). An attempt is one fix→re-check cycle.
- **On exhaustion, STOP and escalate.** When the cap is hit, do not try again. Write a short failure summary — what was attempted, what still fails, the suspected cause — and hand it to the founder. Exhaustion is an approval-boundary event.
- **Never satisfy a loop by weakening the check.** Deleting a failing test, relaxing an eval threshold, loosening a lint rule, or `# type: ignore`-ing the error is forbidden — that defeats the only thing the loop is for. If the bar itself is wrong, that's an ADR decision for the founder, not a quiet edit mid-loop.
- **The gate enforces the count.** `scripts/gate.sh` tracks attempts per loop and returns a distinct ESCALATE code when the cap is reached, so the loop terminates deterministically rather than on goodwill.

## Spec-driven conventions (when building from pre-written specs)
These are what make the deterministic traceability gate work — keep them exact:
- **Input specs** live in `<project>/docs/spec/`. That folder is the founder's input; `docs/requirements|tech-spec|design/` are agent-produced. A `docs/spec/MASTER_SPEC.md` indexes every spec and lists its AC IDs.
- **Acceptance-criterion IDs** are stable and shaped `AC-NNNN` (e.g. `AC-0101`). Every requirement has one; an AC without an ID can't be traced.
- **Tickets** cite the spec doc(s) and the exact AC IDs they satisfy, and are prefixed by spec for scannability (`S01-001`, `S02-001`).
- **Tests** reference the AC ID(s) they cover **in a docstring or comment** — not the function name (hyphens are invalid in identifiers). That's how `traceability.py` finds the covering test.
- **Coverage = two gates**: `python3 scripts/traceability.py --project <p>` (mechanical, the authority) plus the eval-judge's semantic pass (does the test truly assert the AC). Nothing ships with an uncovered or partial AC.
- **Spec drift**: amending or rejecting a spec mid-build is an ADR, and that ADR's AC must be marked `deviated` in `docs/analysis/ac-registry.csv`, or traceability reports a false green.

## How work flows
`ceo → product-manager → architect → ux-designer → eng-manager → {backend,frontend,database,mobile}-engineer → code-reviewer → qa-engineer → security-engineer → performance-engineer → docs-writer → release-manager → founder go/no-go → devops-sre deploy`

For mobile apps the release-manager is replaced by `mobile-release-engineer` (store-readiness gate); submitting to the App Store / Play Console is always a founder approval boundary.

The eval-judge scores each stage's artifact before the next stage starts.

## Git commit rules
- Never add `Co-Authored-By` lines to commit messages
- Never add "Generated with Claude Code" footer to PR descriptions

<!-- ===== Project specifics — FILL THIS IN (or let onboarding populate it) ===== -->
## This project

**Stack**
- Python 3.11+ / Poetry — all backend logic
- LangGraph 0.2 + LangChain 0.3 — agent orchestration DAG (v1)
- FastAPI + SQLAlchemy + SQLite (Alembic migrations) — REST backend (`app/backend/`)
- React + ReactFlow + Tailwind + shadcn/ui / pnpm — visual flow editor frontend (`app/frontend/`)
- v2 engine: self-contained rebuild in `v2/` (not yet wired into the web app)

**Entry points**
- CLI hedge fund: `poetry run python src/main.py --ticker AAPL,MSFT`
- CLI backtest: `poetry run python src/backtester.py --ticker AAPL,MSFT`
- Web backend: `uvicorn app.backend.main:app --reload` (from repo root)
- Web frontend: `pnpm dev` (from `app/frontend/`)
- v2 interactive: `poetry run python -m v2.run`
- v2 YAML mandate: `poetry run python -m v2.run v2/funds/example.yaml --date 2025-06-03`
- Tests (v1): `poetry run pytest tests/`
- Tests (v2): `poetry run pytest v2/`

**Architecture**
Three co-existing generations: `src/` (v1 production), `app/` (web wrapper over v1),
`v2/` (ground-up rebuild — principled point-in-time design, not yet exposed in the app).
`ANALYST_CONFIG` in `src/utils/analysts.py` is the single source of truth for all 19 agents.
Every v1 analyst follows an identical contract: fetch data → score deterministically → call_llm() → write to `state["data"]["analyst_signals"]`.
External data via `financialdatasets.ai`; LLM providers via LangChain wrappers.
In-memory cache singleton (`src/data/cache.py`) is process-scoped and not thread-safe.

**Repo-specific conventions**
- `call_llm()` (`src/utils/llm.py`) is the only LLM call site; always pass `default_factory` for graceful fallback
- Adding a new v1 agent: create `src/agents/<name>.py`, register in `ANALYST_CONFIG`, follow the existing agent return contract exactly
- Adding a new v2 alpha model: implement `AlphaModel.predict(ticker, date, data_client) -> Signal` in `v2/signals/`, register it, add a test
- New v2 strategies: YAML-only, drop in `v2/strategies/` — no code needed
- `black` line-length is set to 420 (placeholder) — effectively no line-length enforcement

**System map**: `docs/system-map.md`

<!-- ===== CONFLICTS between AgentCo scaffold and this project's actual state ===== -->
## Scaffold conflicts (resolve before enforcing AgentCo workflow)

| Principle / Rule | Conflict |
|---|---|
| Principle 2 + DoD + Loop policy: `scripts/gate.sh` | File does not exist. No CI config exists either (`.github/` has only issue templates). Gate checks cannot run. |
| DoD: `scripts/docs-coverage.py`, `scripts/traceability.py` | Neither script exists. Coverage and traceability checks are manual. |
| DoD: `<project>/BUILD_SUMMARY.md` | Does not exist. |
| Spec-driven conventions: `docs/spec/`, `docs/analysis/ac-registry.csv` | Neither path exists. Project is not spec-driven in its current form. |
| How work flows: persona chain (ceo → PM → architect → ...) | This is a solo OSS project. No multi-persona review workflow is in place. Apply selectively. |
| Tests: `poetry run pytest` required | Bare `python3 -m pytest` fails — `colorama` and other deps are not in the system Python. Always use `poetry run pytest`. |
