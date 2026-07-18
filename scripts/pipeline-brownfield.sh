#!/usr/bin/env bash
# Brownfield pipeline: change an EXISTING app safely.
# Swaps the greenfield vision start for a codebase-mapping start, and adds the
# regression gate (existing suite + characterization tests must stay green).
# Verify flags with `claude --help`.
set -euo pipefail
REPO="${1:?usage: pipeline-brownfield.sh <path-to-existing-repo> \"<change goal>\"}"
GOAL="${2:?provide a change goal, e.g. \"add CSV export without touching the report view\"}"

stage(){ echo; echo "########## $1 ##########"; }
ask(){ claude -p "$1" --permission-mode acceptEdits; }

stage "0  Map the codebase (codebase-analyst, read-only)"
ask "As codebase-analyst: map the repo at $REPO and write docs/analysis/system-map.md. Founder intent: $GOAL. List the surfaces this change will touch."

stage "2-3 Change request (product-manager)"
ask "As product-manager: write a change request + tickets for: $GOAL, grounded in the system map. Keep scope tight."

stage "6  Integration design (architect; principal-engineer if it's an improvement)"
ask "As architect (and principal-engineer if this is a refactor/improvement): design how the change fits the existing architecture. ADR for any deviation or structural change. Apply the change-impact skill: isolated vs cross-cutting, prefer additive design."

stage "PRE  Characterization tests (qa-engineer)"
ask "As qa-engineer: using the characterization-tests skill, pin the CURRENT behavior of the touched surfaces as golden tests. Confirm they pass against the unchanged code."

stage "8  Implement additively (engineers / ai-engineer if AI)"
ask "As the right engineer: implement $GOAL. Prefer new paths/flags/extension points. Do not modify existing behavior beyond what the change requires."

stage "GATE  Regression"
bash scripts/gate.sh   # existing suite + characterization tests must be GREEN

stage "9-12 Review / QA / Security / Performance"
ask "As code-reviewer, qa-engineer, security-engineer, performance-engineer: review the diff, confirm the full existing suite + characterization tests pass, scan, and check for regressions."

stage "13-14 Docs + Release prep"
ask "As docs-writer then release-manager: update docs for the change and assemble the go/no-go. STOP before merge/deploy."

echo; echo "Founder approval boundary reached. Existing behavior preserved iff the regression gate stayed green."
