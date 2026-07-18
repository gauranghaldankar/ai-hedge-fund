#!/usr/bin/env bash
# Headless orchestration: drive the lifecycle with `claude -p`, gating between stages.
# Verify exact flags with `claude --help`; from ~June 15 2026 `claude -p` draws from the
# separate Agent SDK credit pool, not your interactive subscription limits.
set -euo pipefail
GOAL="${1:?usage: pipeline.sh \"<product goal>\"}"

stage() { echo; echo "########## $1 ##########"; }
ask()   { claude -p "$1" --permission-mode acceptEdits; }   # adjust flags to your version

stage "1-3 Vision -> Requirements (ceo + product-manager)"
ask "As ceo then product-manager: turn this goal into prioritized requirements with acceptance criteria and tickets on the board. Goal: $GOAL"

stage "6-7 Architecture + UX (architect, ux-designer)"
ask "As architect then ux-designer: produce the tech spec, ADRs, and design spec from the approved requirements."
bash scripts/gate.sh --quick || true

stage "8 Development (eng-manager -> engineers)"
ask "As eng-manager: decompose the spec and have the engineers implement the top backlog slice on a feature branch with tests and migrations."

stage "GATE"
bash scripts/gate.sh

stage "9-12 Review, Test, Security, Perf"
ask "As code-reviewer, then qa-engineer, then security-engineer, then performance-engineer: review, test, scan, and benchmark the slice. Return verdicts."

stage "13-14 Docs + Release prep (docs-writer, release-manager)"
ask "As docs-writer then release-manager: update docs and assemble the go/no-go summary. STOP before merge/deploy."

echo; echo "Pipeline reached the founder approval boundary. Review the go/no-go, then approve merge + deploy manually."
