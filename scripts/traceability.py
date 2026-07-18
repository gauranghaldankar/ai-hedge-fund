#!/usr/bin/env python3
"""
traceability.py — the DETERMINISTIC coverage gate for spec-driven builds.

It does not trust an agent's hand-written matrix. It reads ground truth straight
from the spec files: every acceptance-criterion ID that appears in <project>/docs/spec/
must be (a) cited by a ticket in board/tickets/ and (b) named by a test. Anything
uncovered or partial fails the gate (exit 1), unless an ADR marks the AC as deviated.

Exit codes:
  0  GREEN   — every AC is covered or deviated
  1  RED     — uncovered or partial ACs remain
  3  CONFIG  — no specs found or no AC IDs (not 2, which is gate.sh's ESCALATE)

Pure stdlib. The eval-judge runs the SEPARATE semantic pass (does the test actually
assert the behavior); this script only proves a citing, named test EXISTS.

Usage:
  python3 scripts/traceability.py --project path/to/project
  python3 scripts/traceability.py --project P --pattern 'AC-\\d+' --tests 'Tests/**/*.swift'
"""
import argparse, csv, re, sys
from pathlib import Path

DEFAULT_TEST_GLOBS = [
    "**/test_*.py", "**/*_test.py", "**/tests/**/*.py",
    "**/*.test.js", "**/*.test.ts", "**/*.spec.ts", "**/*_test.go",
    "**/*Tests.swift", "**/*Test.swift", "**/test_*.rs",
]
DEVIATION_WORDS = re.compile(r"deviat|amend|supersede|reject|waiv", re.I)


def read_files(paths):
    out = {}
    for p in paths:
        try:
            out[p] = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            out[p] = ""
    return out


def find_acs_in_specs(spec_dir: Path, pat: re.Pattern):
    """Authority for which ACs exist = IDs found in the individual spec files."""
    acs = {}  # id -> source spec filename
    master = None
    for f in sorted(spec_dir.glob("*.md")):
        if f.name.upper().startswith("MASTER_SPEC"):
            master = f
            continue
        for m in pat.finditer(f.read_text(encoding="utf-8", errors="ignore")):
            acs.setdefault(m.group(0), f.name)
    return acs, master


def load_registry(analysis_dir: Path):
    reg = {}
    csvf = analysis_dir / "ac-registry.csv"
    if csvf.exists():
        try:
            for row in csv.DictReader(csvf.open(encoding="utf-8")):
                ac = (row.get("AC_ID") or "").strip()
                if ac:
                    reg[ac] = row
        except Exception:
            pass
    return reg


def cited_in(text_by_file, ac):
    return [p.name for p, t in text_by_file.items() if ac in t]


def main():
    ap = argparse.ArgumentParser(description="Deterministic AC coverage gate.")
    ap.add_argument("--project", required=True, help="path to the product folder")
    ap.add_argument("--pattern", default=r"AC-\d+", help="AC ID regex (default AC-\\d+)")
    ap.add_argument("--tests", action="append", help="extra test glob(s); repeatable")
    ap.add_argument("--strict-registry", action="store_true",
                    help="also fail if the registry and specs disagree")
    args = ap.parse_args()

    proj = Path(args.project).resolve()
    spec_dir = proj / "docs" / "spec"
    if not spec_dir.is_dir():
        print(f"traceability: no specs at {spec_dir}", file=sys.stderr)
        return 3
    pat = re.compile(args.pattern)

    acs, master = find_acs_in_specs(spec_dir, pat)
    if not acs:
        print(f"traceability: no AC IDs matching /{args.pattern}/ in {spec_dir}", file=sys.stderr)
        return 3

    tickets = read_files(sorted((proj / "board" / "tickets").glob("*.md")))
    test_globs = DEFAULT_TEST_GLOBS + (args.tests or [])
    test_paths = []
    for g in test_globs:
        test_paths += list(proj.glob(g))
    tests = read_files(sorted(set(test_paths)))
    adrs = read_files(sorted((proj / "docs" / "adr").glob("*.md")))
    # best-effort source-cite map (engineers may tag code with the AC ID)
    src_paths = [p for p in proj.rglob("*")
                 if p.is_file() and p.suffix in {".py", ".js", ".ts", ".swift", ".go", ".rs"}
                 and "test" not in p.name.lower()]
    srcs = read_files(src_paths)
    registry = load_registry(proj / "docs" / "analysis")

    rows, covered, partial, uncovered, deviated = [], 0, 0, 0, 0
    for ac in sorted(acs):
        spec = acs[ac]
        t_cites = cited_in(tickets, ac)
        x_cites = cited_in(tests, ac)
        s_cites = cited_in(srcs, ac)
        dev_adrs = [n for n, txt in ((p.name, t) for p, t in adrs.items())
                    if ac in txt and DEVIATION_WORDS.search(txt)]
        if dev_adrs:
            status, deviated = f"deviated ({','.join(dev_adrs)})", deviated + 1
        elif t_cites and x_cites:
            status, covered = "covered", covered + 1
        elif t_cites or x_cites:
            status, partial = "partial", partial + 1
        else:
            status, uncovered = "uncovered", uncovered + 1
        desc = (registry.get(ac, {}).get("description", "") or "").strip()
        rows.append((spec, ac, desc, ";".join(t_cites) or "—",
                     ";".join(x_cites) or "—", ";".join(s_cites) or "—", status))

    # registry drift (warn, or fail under --strict-registry)
    reg_only = sorted(set(registry) - set(acs))
    spec_only = sorted(set(acs) - set(registry)) if registry else []

    out_dir = proj / "docs" / "traceability"
    out_dir.mkdir(parents=True, exist_ok=True)
    total = len(acs)
    pct = 100.0 * covered / total if total else 0.0
    lines = ["# Traceability matrix", "",
             f"- Total ACs: **{total}**  ·  covered: **{covered}**  ·  partial: **{partial}**  "
             f"·  uncovered: **{uncovered}**  ·  deviated: **{deviated}**",
             f"- Coverage: **{pct:.1f}%**  (covered / total)", "",
             "| Spec | AC | Description | Ticket | Test | Source (cited) | Status |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append("| " + " | ".join(c.replace("|", "\\|") for c in r) + " |")
    if reg_only or spec_only:
        lines += ["", "## Registry drift (warning)"]
        if reg_only:  lines.append(f"- In registry but not in any spec: {', '.join(reg_only)}")
        if spec_only: lines.append(f"- In specs but missing from registry: {', '.join(spec_only)}")
    (out_dir / "TRACEABILITY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"traceability: {total} ACs | covered {covered} | partial {partial} | "
          f"uncovered {uncovered} | deviated {deviated} | {pct:.1f}%")
    print(f"  matrix -> {out_dir / 'TRACEABILITY.md'}")
    if reg_only or spec_only:
        print(f"  registry drift: +reg {reg_only or '—'}  +spec {spec_only or '—'}")

    fail = uncovered > 0 or partial > 0
    if args.strict_registry and (reg_only or spec_only):
        fail = True
    if fail:
        bad = [r[1] for r in rows if r[6] in ("uncovered", "partial")]
        print(f"GATE: RED — not fully covered: {', '.join(bad) or '(registry drift)'}")
        print("  Every AC needs a citing ticket AND a test naming it (or a deviation ADR).")
        return 1
    print("GATE: GREEN — every AC is covered or deviated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
