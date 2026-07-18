#!/usr/bin/env python3
"""slice-status.py — deterministic sequencing gate: is this ticket actually DONE?

Sibling to traceability.py and docs-coverage.py, closing the last enforcement gap in
the trio. Those two prove an AC has a test and a route has a doc. This proves the
REQUIRED STAGES (code-reviewer, qa-engineer, security-engineer, ...) actually ran and
recorded a verdict for a given ticket — not that CLAUDE.md says they're mandatory, but
that a checkable record exists. Before this script, "code-reviewer approved" and
"qa-engineer ran" existed only as prose instructions and conversation history — nothing
a script could point at. That let a stage be silently skipped and rationalized away
(the exact restoos build-2 failure: "the gate substitutes for the reviewer").

Ground truth = a per-ticket verdict ledger the agents themselves append to, never a
hand-maintained checklist:
    board/tickets/<TICKET-ID>.verdicts.md
      gate: GREEN 2026-07-14T10:00:00
      code-reviewer: APPROVE 2026-07-14T10:05:00
      qa-engineer: PASS 2026-07-14T10:10:00
      security-engineer: PASS 2026-07-14T10:12:00

This script does NOT judge quality — it cannot prove a reviewer looked carefully, only
that a verdict was recorded (the same floor/ceiling boundary as docs-coverage.py: this
is the floor). It also cannot be spoofed into GREEN by weakening a check — a FAIL/RED/
REQUEST_CHANGES verdict blocks completion just as hard as a missing one.

Exit codes:
  0  COMPLETE  — every required stage has a positive verdict
  1  INCOMPLETE — a required stage is missing or has a negative verdict
  3  CONFIG    — bad invocation (ticket file not found, malformed ledger)
(3, not 2 — 2 is reserved for gate.sh's ESCALATE, matching traceability.py/docs-coverage.py.)

Usage:
  python3 scripts/slice-status.py --project <dir> --ticket <TICKET-ID> [--require gate,code-reviewer,...]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DEFAULT_REQUIRED = ["gate", "code-reviewer", "qa-engineer", "security-engineer"]

# Which verdict tokens count as POSITIVE per stage. Everything else recorded is negative
# (RED, FAIL, REQUEST_CHANGES, ESCALATE, ...) and blocks completion just like "missing".
POSITIVE = {
    "gate": {"GREEN"},
    "code-reviewer": {"APPROVE"},
    "qa-engineer": {"PASS"},
    "security-engineer": {"PASS"},
    "eval-judge": {"PASS"},
    "docs-coverage": {"GREEN"},
}

# Which agent/skill to point at when a required stage is missing entirely.
OWNER = {
    "gate": "run scripts/gate.sh --project <p>",
    "code-reviewer": "invoke the code-reviewer agent (mandatory — see CLAUDE.md DoD)",
    "qa-engineer": "invoke the qa-engineer agent",
    "security-engineer": "invoke the security-engineer agent",
    "eval-judge": "invoke eval-judge (apply the docs-review / traceability skills as relevant)",
    "docs-coverage": "run scripts/docs-coverage.py --project <p>",
}

LINE_RE = re.compile(r'^([a-zA-Z0-9\-]+):\s*(\S+)\s*(.*)$')


def parse_ledger(path: Path) -> dict[str, tuple[str, str]]:
    """Return {stage: (verdict, rest_of_line)} using the LAST recorded verdict per
    stage (a re-run appends, doesn't overwrite — last entry wins, same as it should:
    a stage that failed and was re-run and passed is now positive)."""
    verdicts: dict[str, tuple[str, str]] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = LINE_RE.match(line)
        if not m:
            continue
        stage, verdict, rest = m.group(1), m.group(2).upper(), m.group(3)
        verdicts[stage] = (verdict, rest)
    return verdicts


def main() -> int:
    ap = argparse.ArgumentParser(description="Deterministic per-ticket sequencing gate.")
    ap.add_argument("--project", default=".", help="project root (default: cwd)")
    ap.add_argument("--ticket", required=True, help="ticket ID, e.g. RST-001")
    ap.add_argument("--require", default=None,
                     help="comma-separated required stages (default: %s)" % ",".join(DEFAULT_REQUIRED))
    args = ap.parse_args()

    root = Path(args.project).resolve()
    if not root.is_dir():
        print(f"CONFIG: project dir not found: {root}", file=sys.stderr)
        return 3

    ledger = root / "board" / "tickets" / f"{args.ticket}.verdicts.md"
    if not ledger.is_file():
        print(f"CONFIG: no verdict ledger for '{args.ticket}' at {ledger}", file=sys.stderr)
        print("  Nothing has been recorded yet — this is expected before any stage runs.",
              file=sys.stderr)
        return 3

    required = [s.strip() for s in args.require.split(",")] if args.require else DEFAULT_REQUIRED
    try:
        verdicts = parse_ledger(ledger)
    except OSError as e:
        print(f"CONFIG: cannot read ledger: {e}", file=sys.stderr)
        return 3

    missing: list[str] = []
    failed: list[tuple[str, str]] = []
    passed: list[str] = []

    for stage in required:
        if stage not in verdicts:
            missing.append(stage)
            continue
        verdict, _ = verdicts[stage]
        if verdict in POSITIVE.get(stage, set()):
            passed.append(stage)
        else:
            failed.append((stage, verdict))

    print(f"# Slice status — {args.ticket}")
    print(f"  ledger: {ledger.relative_to(root)}")
    print(f"  required: {', '.join(required)}")
    print()

    if not missing and not failed:
        print(f"COMPLETE: all {len(required)} required stage(s) recorded a positive verdict.")
        for s in passed:
            v, rest = verdicts[s]
            print(f"  OK  {s}: {v}" + (f"  ({rest.strip()})" if rest.strip() else ""))
        return 0

    print(f"INCOMPLETE: {len(missing)} missing, {len(failed)} failed, {len(passed)} passed "
          f"(of {len(required)} required).")
    if failed:
        print("\n  Blocking (recorded a NEGATIVE verdict — must be re-run and pass, not skipped):")
        for stage, verdict in failed:
            print(f"    FAIL  {stage}: {verdict}   -> {OWNER.get(stage, 'invoke ' + stage)}")
    if missing:
        print("\n  Not yet run:")
        for stage in missing:
            print(f"    ....  {stage}   -> {OWNER.get(stage, 'invoke ' + stage)}")
    if passed:
        print("\n  Already recorded:")
        for s in passed:
            v, _ = verdicts[s]
            print(f"    OK    {s}: {v}")
    print("\n  A slice/ticket is DONE only when this reports COMPLETE. A green gate.sh")
    print("  alone does not mean done — see the required list above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
