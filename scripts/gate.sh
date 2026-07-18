#!/usr/bin/env bash
# Deterministic quality gate — the "QA director" that can't be argued with.
# Runs available tools, skips gracefully when one isn't installed, AND bounds the
# correction loop: it counts consecutive RED attempts per loop and escalates when
# the retry cap is reached, so a fix->re-gate loop terminates deterministically.
#
# Usage (flags in any order):
#   scripts/gate.sh [--quick]            run checks (‑‑quick skips the slow ones)
#   scripts/gate.sh --project <dir>      gate THAT project dir (per-project isolation)
#   scripts/gate.sh --reset              clear this loop's attempt counter
#   scripts/gate.sh --infra-reset        reset after a CONFIRMED infrastructure
#                                        failure (e.g. dirty Redis, network blip) —
#                                        does NOT count against the retry budget.
#                                        Use only when tests passed before the
#                                        env was dirty; founder must confirm.
#
# Exit codes:
#   0  GREEN     — checks pass; counter reset; loop ends successfully
#   1  RED       — checks fail; attempts remain; fix and re-run
#   2  ESCALATE  — retry cap reached; STOP and hand to the founder
#   3  CONFIG    — bad invocation (e.g. --project dir missing)
#
# Per-project: --project cds into the dir for stack detection + test execution,
# but counters always live at $REPO_ROOT/.agentco/loops (resolved BEFORE the cd),
# so one gitignored namespace holds all counters and projects key independently.
#
# Tunables (env):
#   GATE_MAX_RETRIES   attempts before escalation (default 3)
#   GATE_LOOP          name this loop explicitly; else "<project>/<branch>"
set -uo pipefail

CAP="${GATE_MAX_RETRIES:-3}"

# --- parse args (any order): --quick  --reset  --project <dir> ----------------
QUICK=""; RESET=0; PROJECT=""; INFRA_RESET=0
while [ $# -gt 0 ]; do
  case "$1" in
    --quick)      QUICK="--quick" ;;
    --reset)      RESET=1 ;;
    --infra-reset) INFRA_RESET=1 ;;
    --project)    PROJECT="${2:-}"; shift ;;
    --project=*)  PROJECT="${1#*=}" ;;
    *) echo "gate.sh: unknown arg '$1'" >&2 ;;
  esac
  shift
done

# --- resolve the counter location at REPO ROOT, BEFORE any cd into the project -
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
STATE_DIR="$REPO_ROOT/.agentco/loops"
mkdir -p "$STATE_DIR" 2>/dev/null || true

# --- loop key: <project>/<branch> so projects count independently --------------
loop_key() {
  if [ -n "${GATE_LOOP:-}" ]; then echo "$GATE_LOOP"; return; fi
  local b proj; b="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  proj="$(basename "${PROJECT:-$PWD}")"
  echo "${proj}/${b:-default}"
}
KEY="$(loop_key)"
SAFE="${KEY//\//__}"
COUNTER="$STATE_DIR/$SAFE.count"

read_count() { local c; c="$(cat "$COUNTER" 2>/dev/null || echo 0)"; [[ "$c" =~ ^[0-9]+$ ]] && echo "$c" || echo 0; }
write_count() { echo "$1" > "$COUNTER" 2>/dev/null || true; }

# --- infra reset (env failure, NOT a product failure) ---
if [ "$INFRA_RESET" -eq 1 ]; then
  write_count 0
  echo "GATE: counter reset for loop '$KEY' (infra-reset — env failure confirmed by founder)."
  echo "  This did NOT count against the retry budget. The underlying product failures"
  echo "  must still be fixed before the gate can go GREEN."
  exit 0
fi

# --- manual reset --------------------------------------------------------------
if [ "$RESET" -eq 1 ]; then
  write_count 0; echo "GATE: counter reset for loop '$KEY'"; exit 0
fi

# --- cd into the project for checks (counter already bound to repo root) --------
if [ -n "$PROJECT" ]; then
  cd "$PROJECT" 2>/dev/null || { echo "gate.sh: cannot cd to project '$PROJECT'" >&2; exit 3; }
fi

# --- prepend project venv bin/ so tools resolve from the venv, not Anaconda ---
for _venv_bin in .venv/bin venv/bin backend/.venv/bin backend/venv/bin; do
  if [ -d "$_venv_bin" ]; then
    export PATH="$(pwd)/$_venv_bin:$PATH"
    break
  fi
done

# --- run the checks ------------------------------------------------------------
fail=0
run()  { echo "==> $*"; if "$@"; then return 0; else fail=1; return 1; fi; }
have() { command -v "$1" >/dev/null 2>&1; }

# Lint / secrets — generic, run whatever is present.
if have ruff;  then run ruff check .; elif have flake8; then run flake8; fi
if have black; then run black --check .; fi
if have eslint && [ -f package.json ]; then run npx --no-install eslint . || true; fi
if have gitleaks; then run gitleaks detect --no-banner; fi

# Tests — STACK-AWARE: detect the project type(s) and run the right runner(s).
# A spec-driven build can produce any stack, so don't assume Python.
run_tests() {
  local ran=0
  if [ -f pyproject.toml ] || [ -f setup.py ] || ls requirements*.txt >/dev/null 2>&1; then
    if have pytest; then run pytest -q; ran=1; fi
  fi
  if [ -f package.json ]; then
    if grep -q '"test"' package.json 2>/dev/null && have npm; then run npm test --silent; ran=1; fi
  fi
  if [ -f Package.swift ]; then
    if have swift; then run swift build && run swift test; ran=1; fi
  fi
  if [ -f go.mod ]; then
    if have go; then run go test ./...; ran=1; fi
  fi
  if [ -f Cargo.toml ]; then
    if have cargo; then run cargo test --quiet; ran=1; fi
  fi
  if [ -f build.gradle ] || [ -f build.gradle.kts ] || [ -f settings.gradle ] || [ -f settings.gradle.kts ]; then
    if [ -x ./gradlew ]; then run ./gradlew test; ran=1
    elif have gradle; then run gradle test; ran=1; fi
  fi
  if [ "$ran" -eq 0 ]; then
    echo "==> (no recognized test runner present for this stack — tests skipped)"
  fi
}

if [ "$QUICK" != "--quick" ]; then
  run_tests
  if have mypy && { [ -f pyproject.toml ] || [ -f setup.py ]; }; then run mypy . || true; fi
  if have pip-audit; then run pip-audit || true; fi
  if have semgrep; then run semgrep --error --quiet || true; fi
  if have trivy && [ -f Dockerfile ]; then run trivy config .; fi
fi

# --- verdict + bounded-loop accounting ----------------------------------------
if [ "$fail" -eq 0 ]; then
  write_count 0
  if [ -n "${TICKET:-}" ]; then
    mkdir -p "$REPO_ROOT/board/tickets" 2>/dev/null || true
    echo "gate: GREEN $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$REPO_ROOT/board/tickets/${TICKET}.verdicts.md"
  fi
  echo "GATE: GREEN  (loop '$KEY' — counter reset)"
  echo "  Build/tests passing is NOT the same as done. Run:"
  echo "    python3 scripts/slice-status.py --project . --ticket <TICKET-ID>"
  echo "  to confirm code-reviewer, qa-engineer, and security-engineer have also recorded"
  echo "  a positive verdict before calling this slice complete."
  exit 0
fi

attempt=$(( $(read_count) + 1 ))
write_count "$attempt"

if [ "$attempt" -ge "$CAP" ]; then
  echo "GATE: ESCALATE  (loop '$KEY' — attempt $attempt/$CAP, cap reached)"
  echo "  STOP. Do not retry and do not weaken any check to pass."
  echo "  Summarize for the founder: what was attempted, what still fails, the suspected cause."
  echo "  (Reset after a founder decision with: scripts/gate.sh --reset)"
  echo "  If failures were caused by infrastructure noise (dirty Redis, DB state,"
  echo "  network blip) AND tests were passing before, use --infra-reset instead."
  echo "  --infra-reset clears the counter without consuming a retry slot."
  echo "  The distinction matters: product bugs get the full cap; env noise does not."
  exit 2
fi

echo "GATE: RED  (loop '$KEY' — attempt $attempt/$CAP). Fix the failures and re-run; do not weaken checks."
exit 1
