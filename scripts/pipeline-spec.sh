#!/usr/bin/env bash
# WARNING: Reference artifact only — uses `claude -p` which bills the Agent SDK
# credit pool separately from your Max subscription. The interactive playbook
# (docs/playbooks/build-product-interactively.md) is the preferred $0 path.
#
# Spec-driven pipeline: build a product from a set of PRE-WRITTEN spec documents.
# Front of the pipeline becomes intake+validation (not spec authoring); the back
# adds the deterministic traceability gate. Interactive on Max is the primary path;
# this script is the headless reference. Verify flags with `claude --help`.
set -euo pipefail
PROJ="${1:?usage: pipeline-spec.sh <project-dir-containing-docs/spec> }"

stage(){ echo; echo "########## $1 ##########"; }
ask(){ claude -p "$1" --permission-mode acceptEdits; }

stage "0a Intake — extract (spec-analyst, PASS A, per-doc)"
ask "As spec-analyst using the spec-intake skill: read each file in $PROJ/docs/spec/ ONE at a time and build $PROJ/docs/analysis/ac-registry.csv (AC_ID,description,spec_file,testable,priority,depends_on)."

stage "0b Intake — consistency (spec-analyst, PASS B, on the compact registry)"
ask "As spec-analyst: using ONLY the registry + one-line summaries + declared deps, scan for cross-spec contradictions, dependency cycles, non-testable ACs, and ambiguities. Write $PROJ/docs/analysis/spec-map.md. Flag, do not fix."

stage "FOUNDER GATE — resolve flagged gaps BEFORE any ticket"
echo "  Review $PROJ/docs/analysis/spec-map.md. Rewrite vague ACs, break cycles via ADR, drop dead specs."
echo "  Intake-before-build: do not proceed until the gap/contradiction/ambiguity list is resolved."
read -r -p "  All flagged items resolved? [y/N] " ok; [ "$ok" = "y" ] || { echo "Stopping at intake."; exit 0; }

stage "2 Decompose to tickets (eng-manager + ticket-ops)"
ask "As eng-manager: turn the validated specs into dependency-ordered tickets in $PROJ/board/tickets/. Prefix IDs by spec (S01-001, S02-001...). Each ticket CITES the spec doc(s) and the exact AC IDs it satisfies."

stage "3 Build per slice (engineers -> gate -> review -> qa)"
ask "As the right engineer: implement each ticket reading ONLY the spec docs it cites. Each test must REFERENCE its AC ID(s) in a docstring or comment (AC IDs contain hyphens, so they can't be in a function name) so traceability can find them."
echo "  Per slice, run the stack-aware bounded gate:"
echo "    bash scripts/gate.sh --project $PROJ   # green, or N tries then escalate"
ask "As code-reviewer then qa-engineer: review the diff against cited ACs; confirm the suite is green."

stage "4 Traceability gate — TWO gates"
echo "  Gate 1 (mechanical, the authority):"
echo "    python3 scripts/traceability.py --project $PROJ   # non-zero if any AC uncovered/partial"
ask "As eval-judge using the traceability skill — Gate 2 (semantic): for all Must-priority ACs plus a sample, confirm the cited test MEANINGFULLY asserts the AC (not assert True). Weak tests FAIL back to QA."

stage "5 Docs + Release (docs-writer, release-manager)"
ask "As docs-writer then release-manager: write docs and assemble the go/no-go + BUILD_SUMMARY with a Spec Coverage section from TRACEABILITY.md. STOP before merge/deploy."

echo; echo "Founder approval boundary. Ships only if traceability.py is green AND the eval-judge's semantic pass is clean."
