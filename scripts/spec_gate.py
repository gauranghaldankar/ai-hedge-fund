#!/usr/bin/env python3
"""
spec_gate.py — G8xx spec-review defect class checks (AgentCo gate group 8).

Scans docs, scripts, and history to mechanically flag the defect classes that
have appeared in ≥2 independent projects and earned permanent gate status.
These are check codes G801–G808; the corresponding lesson-level defect class
identifiers (G1–G7, G-LEX) live in lessons/.

Check code → lesson defect class mapping:
  G801  ← lesson G1  Tautological verification  — compare ACs with no failure-mode description
  G802  ← lesson G2  Phantom canonicalization   — "replaces X" claim with X absent from history/ as JSON key
  G805  ← lesson G5  Line-number anchoring      — protected regions anchored by line number, not content hash
  G806  ← lesson G6  Unmeasurable gates         — event-gate conditions without a named endpoint+field
  G807  ← lesson G7  Typo-class identifier drift — edit-dist ≤2 pairs in spec code blocks (typo-class only;
                                                    synonym-class drift requires human review — dist > 2)
  G808  ← lesson LEX Lexicographic sort safety  — sorted() on session/timestamp files without lex-safety comment

Reserved but not yet automated:
  G803  ← lesson G3  Incomplete generation model — human-review-only today; heuristic candidate:
                      grep deprecated-field names against `git log -S <field> framework/` to verify
                      the field appears in actual commit history (not just asserted from memory)
  G804  ← lesson G4  Undocumented partial migration — mechanization candidate: `git log --oneline
                      framework/contracts/` → find commits with zero references in docs/ or board/;
                      unreferenced contract-file commits are the half-migration signature. Calibrate
                      false-positive rate on real repos before promoting to FAIL semantics.

Namespace: G8xx is this project's group in the AgentCo spec gate. Checks
from other groups (G0xx–G7xx) live in the canonical AgentCo gate; see RFC-009
for the full group hierarchy design. G803 and G804 are reserved within G8xx —
do not assign them to other checks. Do not add checks numbered below G800 or
above G899 without coordinating with the AgentCo gate design (ticket RFC-009).

Source: lessons/lesson-20260713-spec-review-defect-classes.json

Exit codes:
  0  GREEN  — no active violations (waivers shown but not counted)
  1  RED    — one or more active violations, or an expired waiver found
  3  ERROR  — configuration or path problem

Pure stdlib. Run from the repo root or pass --root.

Usage:
  python3 scripts/spec_gate.py
  python3 scripts/spec_gate.py --root /path/to/repo
  python3 scripts/spec_gate.py --checks G801,G802,G808
  python3 scripts/spec_gate.py --json
"""
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

# Bump on any functional check change — gate.sh drift detection compares the
# project copy's content against the AgentCo master (~/.agentco/scripts/spec_gate.py)
# and warns on mismatch; this version string lets operators identify which
# generation of the gate they are running at a glance.
GATE_VERSION = "1.2.0"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def collect(root: Path, globs: list) -> list:
    paths = []
    for g in globs:
        paths.extend(root.glob(g))
    return sorted(set(paths))


def lineno(text: str, pos: int) -> int:
    return text[:pos].count("\n") + 1


def surrounding(text: str, pos: int, window: int = 300) -> str:
    return text[max(0, pos - window) : pos + window]


# ---------------------------------------------------------------------------
# G1 — Tautological verification
#
# Heuristic: checklist AC lines that describe a comparison/diff operation but
# name no failure state. The canonical instance: check-golden.sh v1 compared
# a golden fixture to the file it was copied from — the comparison could never
# fail. Only comparison verbs are flagged (compare, diff, identical, match
# against); plain existence checks ("field X exists") are out of scope.
# ---------------------------------------------------------------------------

_COMPARE_VERBS = re.compile(
    r"\b(compare(?:s| to| against| with)?|diff(?:s| against| with)?|"
    r"identic(?:al)?|match(?:es)? against|match(?:es)? the)\b",
    re.I,
)
_FAILURE_WORDS = re.compile(
    r"\b(fail|exit 1|exits 1|exits non.zero|error|wrong|must not|cannot|never|"
    r"reject|invalid|mismatch|0 hit|zero hit|not found|no match|incorrect|"
    r"real failure|failure mode)\b|!=|≠",
    re.I,
)
_AC_LINE = re.compile(r"^\s*[-*]\s+\[[ xX]\]\s+.+", re.M)


def check_g1(root: Path) -> list:
    findings = []
    for path in collect(root, ["board/tickets/*.md", "docs/**/*.md"]):
        text = read_text(path)
        for m in _AC_LINE.finditer(text):
            line = m.group(0)
            if _COMPARE_VERBS.search(line) and not _FAILURE_WORDS.search(line):
                findings.append(
                    f"  G801 {path.relative_to(root)}:{lineno(text, m.start())}: "
                    f"no failure condition — {line.strip()[:120]}"
                )
    return findings


# ---------------------------------------------------------------------------
# G2 — Phantom canonicalization
#
# Heuristic: any "replaces <field>" / "renamed from <field>" claim in docs
# requires at least one occurrence of <field> in history/ output files.
# Zero hits = phantom — the rename fixes something that was never broken.
#
# Stoplist: common English words that the regex may capture but are not field
# names. Captured tokens must also look like snake_case or camelCase identifiers
# (contain at least one underscore or uppercase letter), OR be long enough (≥8
# chars) to be unambiguously a field name.
# ---------------------------------------------------------------------------

_REPLACES_PAT = re.compile(
    # require a word boundary before the captured group to avoid matching inside
    # compound identifiers like `replaced_by` → the captured part would be wrong
    r"(?:^|\s)(?:replaces?|renamed?\s+from|old\s+name[:\s]+|"
    r"supersedes?|deprecated\s+name[:\s]+)\s*[`'\"]?\b([A-Za-z]\w{3,})\b[`'\"]?",
    re.I | re.M,
)

_G2_STOPLIST = {
    # type names, English words, common programming terms — not field names
    "boolean",
    "integer",
    "string",
    "object",
    "array",
    "null",
    "number",
    "missing",
    "declared",
    "defined",
    "present",
    "added",
    "removed",
    "primary",
    "secondary",
    "comparative",
    "implementation",
    "section",
    "this",
    "that",
    "with",
    "from",
    "name",
    "field",
    "value",
    "type",
    "true",
    "false",
    "none",
    "optional",
    "required",
    "deprecated",
    # common English verbs/nouns that the ≥8-char filter catches in prose
    # but are never JSON/YAML field names:
    "generate",
    "placeholders",
    "remaining",
    "substring",
    "existing",
    "following",
    "previous",
    "instance",
    "versions",
    "standard",
    "multiple",
    "contents",
    "document",
    "elements",
    "function",
    "template",
    "variable",
}


def check_g2(root: Path) -> list:
    history_files = collect(root, ["history/*.json"])
    history_text = "\n".join(read_text(p) for p in history_files)

    findings = []
    seen = set()  # de-duplicate same field flagged in multiple files
    for path in collect(root, ["docs/**/*.md", "board/**/*.md"]):
        text = read_text(path)
        for m in _REPLACES_PAT.finditer(text):
            field = m.group(1)
            # skip stoplist words and tokens that look like plain English
            if field.lower() in _G2_STOPLIST:
                continue
            # require the token to look like a field name: snake_case, camelCase,
            # or long enough (≥8 chars) to be unambiguously a technical identifier
            is_snake = "_" in field
            is_camel = any(c.isupper() for c in field[1:])
            if not (is_snake or is_camel or len(field) >= 8):
                continue
            if field in seen:
                continue
            # Match as a JSON key ("field":) not as a raw substring — prevents
            # a prefix like "evidence" from hiding inside "evidence_sources".
            if not re.search(rf'"{re.escape(field)}"\s*:', history_text):
                seen.add(field)
                findings.append(
                    f"  G802 {path.relative_to(root)}:{lineno(text, m.start())}: "
                    f"phantom — '{field}' not found as JSON key in history/ "
                    f"(claim: '{m.group(0).strip()[:70]}')"
                )
    return findings


# ---------------------------------------------------------------------------
# G5 — Line-number anchoring of protected regions
#
# Heuristic: look for explicit statements that a region identified by line number
# "must be preserved" / "must not change". The defect is anchoring the IDENTITY
# of a protected region to its current line numbers rather than to a content hash
# — any edit above the region silently breaks the anchor.
#
# To reduce false positives, require strong protection language ("must be
# preserved", "must remain", "do not edit", "protected region") in the
# same sentence or nearby, not just any mention of "protect" or "preserve."
# Documentation that *cites* line numbers as a code reference (without claiming
# the lines must stay fixed) is not flagged.
# ---------------------------------------------------------------------------

_LINE_NUM = re.compile(r"\blines?\s+\d[\d ,\-–]+", re.I)
_STRONG_ANCHOR = re.compile(
    r"\b(must\s+(?:be\s+)?preserved?|must\s+not\s+(?:change|move|be\s+edited)|"
    r"do\s+not\s+edit|protected\s+region|keep\s+intact|must\s+remain\s+unchanged|"
    r"must\s+remain\s+at)\b",
    re.I,
)
_HASH_CTX = re.compile(r"\b(sha256|content.?hash|hash of|checksum|digest)\b", re.I)


def check_g5(root: Path) -> list:
    findings = []
    for path in collect(root, ["docs/**/*.md", "board/**/*.md", "framework/**/*.md"]):
        text = read_text(path)
        for m in _LINE_NUM.finditer(text):
            # narrow 150-char window for the strong-anchor check (same sentence)
            ctx = surrounding(text, m.start(), window=150)
            if _STRONG_ANCHOR.search(ctx) and not _HASH_CTX.search(ctx):
                findings.append(
                    f"  G805 {path.relative_to(root)}:{lineno(text, m.start())}: "
                    f"line-number anchor without content hash — '{m.group(0).strip()}'"
                )
    return findings


# ---------------------------------------------------------------------------
# G6 — Unmeasurable gates
#
# Heuristic: text describing an event-gate exit condition without a named API
# endpoint visible anywhere in the same Markdown section (between ## headings).
# A gate that can't be mechanically read is a ticking clock, not a gate.
#
# Section-level search: the endpoint may be defined anywhere in the same
# section that specifies the gate condition — not just within a 500-char window.
# This avoids the false positive of ADR-001 where the endpoint IS documented
# in the same "Alias-Drop Condition" section but more than 500 chars away.
# ---------------------------------------------------------------------------

_EVENT_GATE = re.compile(
    # Only match language that DEFINES when to remove/drop an alias or close a gate —
    # not mere references to the fact that such a gate exists. This avoids flagging
    # every narrative mention of "event-gated" in Consequences or Alternatives sections.
    r"\b(gate\s+condition[:\s]|exit\s+condition[:\s]|"
    r"(?:remove|drop)\s+alias(?:es)?\s+(?:when|once|after)|"
    r"alias(?:es)?\s+(?:are\s+)?removed?\s+(?:when|once)|"
    r"alias.drop\s+condition\s*:|"
    r"aliases?\s+may\s+be\s+removed\s+when)\b",
    re.I,
)
_ENDPOINT = re.compile(
    r"(GET|POST|PUT|PATCH|DELETE)\s+/\S+|/api/\S+|\bstatus\s+endpoint\b", re.I
)
_SECTION_BREAK = re.compile(r"^#{1,3}\s+", re.M)


def _extract_section(text: str, pos: int) -> str:
    """Return the text of the Markdown section (## block) containing pos."""
    # find start of current section
    starts = [m.start() for m in _SECTION_BREAK.finditer(text) if m.start() <= pos]
    sec_start = starts[-1] if starts else 0
    # find end of current section (next heading at same/higher level)
    ends = [m.start() for m in _SECTION_BREAK.finditer(text) if m.start() > pos]
    sec_end = ends[0] if ends else len(text)
    return text[sec_start:sec_end]


def check_g6(root: Path) -> list:
    findings = []
    for path in collect(root, ["docs/**/*.md", "board/**/*.md", "framework/**/*.md"]):
        text = read_text(path)
        for m in _EVENT_GATE.finditer(text):
            section = _extract_section(text, m.start())
            if not _ENDPOINT.search(section):
                findings.append(
                    f"  G806 {path.relative_to(root)}:{lineno(text, m.start())}: "
                    f"event gate without named endpoint in section — '{m.group(0).strip()}'"
                )
    return findings


# ---------------------------------------------------------------------------
# G7 — Typo-class identifier drift (edit-distance ≤2)
#
# Heuristic: extract snake_case identifiers from fenced code blocks in spec docs
# and flag any pair with Levenshtein edit distance 1–2. These are typo-class
# duplicates: advisor_run vs advisors_run, framework_versions vs framework_version.
#
# SCOPE LIMIT: this check does NOT catch synonym-class drift, where two names
# for the same concept have edit distance > 2 (canonical_ingestions vs
# canonical_only_files = dist 7). Synonym-class requires a human reviewer who
# understands which concepts the identifiers denote — not automatable by
# distance metric. G7 is intentionally narrow; do not expand the threshold
# above 2 without a false-positive audit (naming families like borda_* or
# execution_metadata_* would generate unbounded noise).
# ---------------------------------------------------------------------------

_CODE_BLOCK = re.compile(r"```[^\n]*\n(.*?)```", re.S)
_IDENTIFIER = re.compile(
    r"\b[a-z][a-z0-9]{2,}(?:_[a-z0-9]+)+\b"
)  # snake_case, ≥2 segments


def _levenshtein(a: str, b: str) -> int:
    """Classic DP edit distance."""
    if a == b:
        return 0
    if len(a) > len(b):
        a, b = b, a
    row = list(range(len(a) + 1))
    for cb in b:
        nr = [row[0] + 1]
        for i, ca in enumerate(a, 1):
            nr.append(min(row[i] + 1, nr[i - 1] + 1, row[i - 1] + (ca != cb)))
        row = nr
    return row[-1]


def check_g7(root: Path) -> list:
    findings = []
    for path in collect(root, ["docs/**/*.md", "board/**/*.md"]):
        text = read_text(path)
        # flagged_pairs is per-file: same pair in multiple code blocks reports once
        flagged_pairs: set = set()
        for bm in _CODE_BLOCK.finditer(text):
            block = bm.group(1)
            ids = sorted(set(_IDENTIFIER.findall(block)))
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    a, b = ids[i], ids[j]
                    if (a, b) in flagged_pairs:
                        continue
                    dist = _levenshtein(a, b)
                    if not (1 <= dist <= 2):
                        continue
                    # Skip ordinal naming families: check_g1/check_g2, phase_1/phase_2 —
                    # identifiers that differ only by a single digit substitution in the
                    # same position are a numbered family, not a near-duplicate label.
                    if dist == 1 and len(a) == len(b):
                        diffs = [(ca, cb) for ca, cb in zip(a, b) if ca != cb]
                        if (
                            len(diffs) == 1
                            and diffs[0][0].isdigit()
                            and diffs[0][1].isdigit()
                        ):
                            continue
                    flagged_pairs.add((a, b))
                    findings.append(
                        f"  G807 {path.relative_to(root)}:{lineno(text, bm.start())}: "
                        f"typo-class pair (dist={dist}): '{a}' vs '{b}'"
                    )
    return findings


# ---------------------------------------------------------------------------
# LEX — Lexicographic sort safety
#
# Heuristic: sorted() applied to a glob / listing that produces files whose
# names contain timestamps, session IDs, or date strings — without a co-located
# comment that justifies why alphabetical order equals chronological order.
#
# The safe case (YYYYMMDD-HHMMSS zero-padded fixed-width filenames) must be
# documented. Absence of the comment is the flag.
#
# Narrow trigger: the sorted() argument must contain a glob pattern that
# references typical session-named files (council-decision, history,
# YYYYMMDD, timestamp) — NOT generic *.md or *.py globs (which are not
# timestamp-ordered).
# ---------------------------------------------------------------------------

_SORTED_CALL = re.compile(r"\bsorted\s*\([^)]{0,200}\)", re.I)
_SESSION_GLOB = re.compile(
    r"council.decision|history/|YYYYMMDD|\*\d|\d{8}|\btimestamp\b|"
    r"session|replay|decision",
    re.I,
)
_LEX_COMMENT = re.compile(
    r"#.{0,200}(?:lex(?:ico(?:graphic)?)?|alphabetical).{0,80}"
    r"(?:chron|order|safe|correct|equal|same)|"
    r"#.{0,200}zero.?pad|"
    r"#.{0,200}fixed.?width|"
    r"#.{0,200}YYYYMMDD",
    re.I,
)

# Bash sort pattern: `ls <session-path> | sort` or `sort` applied to session-named
# files. The canonical bad case: `ls history/ | sort | tail -1`.
# Only flag when the sort target references session/timestamp-hint words — not
# generic `sort` calls on arbitrary data.
_BASH_SORT = re.compile(
    r"ls\s+[^\n|]*(?:history|council.decision|session|decision)[^\n|]*\|\s*sort\b|"
    r"\bsort\b[^\n]*(?:history|council.decision|session|decision)",
    re.I,
)


def check_lex(root: Path) -> list:
    findings = []
    for path in collect(root, ["scripts/*.py", "scripts/*.sh", "framework/**/*.py"]):
        text = read_text(path)
        lines = text.splitlines()
        if path.suffix == ".sh":
            # Bash: flag `ls history/ | sort` patterns without a lex-safety comment.
            for i, line in enumerate(lines):
                if not _BASH_SORT.search(line):
                    continue
                window = "\n".join(lines[max(0, i - 2) : min(len(lines), i + 4)])
                if not _LEX_COMMENT.search(window):
                    findings.append(
                        f"  G808 {path.relative_to(root)}:{i + 1}: "
                        f"bash sort on session/timestamp files without lex-safety comment — "
                        f"'{line.strip()[:110]}'"
                    )
        else:
            # Python: flag sorted() calls on session-named file globs.
            for i, line in enumerate(lines):
                m = _SORTED_CALL.search(line)
                if not m:
                    continue
                arg = m.group(0)
                # only flag if the glob/call references session/timestamp-named files
                if not _SESSION_GLOB.search(arg):
                    continue
                # check 2 lines before and 3 lines after for the safety comment
                window = "\n".join(lines[max(0, i - 2) : min(len(lines), i + 4)])
                if not _LEX_COMMENT.search(window):
                    findings.append(
                        f"  G808 {path.relative_to(root)}:{i + 1}: "
                        f"sorted() on session/timestamp files without lex-safety comment — "
                        f"'{line.strip()[:110]}'"
                    )
    return findings


# ---------------------------------------------------------------------------
# Waiver mechanism (S3)
#
# Known, ticketed, accepted findings should not trigger RED and train
# RED-blindness. A `.spec_gate_waivers.json` file at the repo root can
# declare accepted findings with a ticket reference and expiry date.
#
# Schema (array of objects):
#   check        — G-code string ("G1", "G2", "G5", ...)
#   path         — substring matched against the finding path (e.g. "RFC-004.md")
#   line_pattern — regex matched against the full finding string
#   reason       — human-readable rationale
#   ticket       — ticket that will resolve this finding
#   expires      — YYYYMMDD; waiver hard-fails after this date (forces cleanup)
#
# Waived findings are printed as WAIVED and excluded from the exit code.
# Expired waivers cause exit 1 with an "EXPIRED WAIVER" message regardless
# of other results — carrying an expired waiver is a gate violation itself.
# ---------------------------------------------------------------------------

_WAIVER_FILE = ".spec_gate_waivers.json"


def load_waivers(root: Path) -> list:
    wf = root / _WAIVER_FILE
    if not wf.exists():
        return []
    try:
        return json.loads(wf.read_text(encoding="utf-8"))
    except Exception as e:
        print(
            f"spec_gate: warning — could not parse {_WAIVER_FILE}: {e}", file=sys.stderr
        )
        return []


def done_ticket_waiver_warns(root: Path, waivers: list) -> list:
    """Return WARN strings for waivers that reference a ticket with status: done.

    A done-ticket waiver is silent dead code: the violation it was suppressing
    should either be gone (clean it up) or still present (assign a new ticket).
    This converts that silent state into an actionable cleanup signal without
    changing the gate exit code.
    """
    warns = []
    tickets_dir = root / "board" / "tickets"
    seen = set()
    for w in waivers:
        ticket = w.get("ticket", "")
        if not ticket or ticket in seen:
            continue
        ticket_file = tickets_dir / f"{ticket}.md"
        if not ticket_file.exists():
            continue
        text = read_text(ticket_file)
        if re.search(r"^status:\s*done", text, re.M | re.I):
            seen.add(ticket)
            warns.append(
                f"  WARN  waiver for {ticket} references a completed ticket "
                f"— review waivers and remove or re-ticket"
            )
    return warns


def apply_waivers(findings: list, waivers: list, check_code: str):
    """Split findings into (active, waived, expired_waiver_msgs)."""
    today = datetime.date.today()
    active, waived, expired = [], [], []
    for finding in findings:
        matched = None
        for w in waivers:
            if w.get("check", "").upper() != check_code:
                continue
            if w.get("path", "") not in finding:
                continue
            if not re.search(w.get("line_pattern", ""), finding, re.I):
                continue
            matched = w
            break
        if matched is None:
            active.append(finding)
        else:
            expires_str = str(matched.get("expires", "99991231"))
            try:
                exp_date = datetime.date(
                    int(expires_str[:4]), int(expires_str[4:6]), int(expires_str[6:8])
                )
            except ValueError:
                exp_date = datetime.date(9999, 12, 31)
            if exp_date < today:
                expired.append(
                    f"  EXPIRED WAIVER ({matched.get('ticket', '?')}): {finding.strip()}"
                )
            else:
                waived.append(
                    f"  WAIVED ({matched.get('ticket', '?')}, expires {expires_str}): "
                    f"{finding.strip()[:120]}"
                )
    return active, waived, expired


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

ALL_CHECKS = {
    "G801": ("Tautological verification", check_g1),
    "G802": ("Phantom canonicalization", check_g2),
    "G805": ("Line-number anchoring of protected regions", check_g5),
    "G806": ("Unmeasurable gates", check_g6),
    "G807": ("Typo-class identifier drift (edit-distance ≤2)", check_g7),
    "G808": ("Lexicographic sort safety", check_lex),
}


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Permanent G-code spec-gate: automated defect-class checks.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--root", default=".", help="repo root (default: current working directory)"
    )
    ap.add_argument(
        "--checks",
        default=",".join(ALL_CHECKS),
        help=(
            f"comma-separated checks to run (default: all). "
            f"Available: {', '.join(ALL_CHECKS)}"
        ),
    )
    ap.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="emit results as JSON to stdout instead of human-readable text",
    )
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"spec_gate: root not found: {root}", file=sys.stderr)
        return 3

    requested = [c.strip().upper() for c in args.checks.split(",") if c.strip()]
    unknown = [c for c in requested if c not in ALL_CHECKS]
    if unknown:
        print(
            f"spec_gate: unknown check(s): {', '.join(unknown)}. "
            f"Available: {', '.join(ALL_CHECKS)}",
            file=sys.stderr,
        )
        return 3

    waivers = load_waivers(root)

    results = {}
    total_violations = 0
    total_waived = 0
    all_expired: list = []
    for code in requested:
        name, fn = ALL_CHECKS[code]
        raw_findings = fn(root)
        active, waived_msgs, expired_msgs = apply_waivers(raw_findings, waivers, code)
        results[code] = {
            "name": name,
            "violations": len(active),
            "waived": len(waived_msgs),
            "findings": active,
            "waived_findings": waived_msgs,
        }
        total_violations += len(active)
        total_waived += len(waived_msgs)
        all_expired.extend(expired_msgs)

    done_warns = done_ticket_waiver_warns(root, waivers)

    if args.as_json:
        print(json.dumps(results, indent=2))
    else:
        print(f"spec_gate v{GATE_VERSION}: root={root}")
        if waivers:
            print(f"  waivers loaded: {len(waivers)} from {_WAIVER_FILE}")
        print()
        for code, r in results.items():
            parts = []
            if r["violations"] > 0:
                parts.append(f"FAIL ({r['violations']})")
            elif r["waived"] > 0:
                parts.append(f"WAIVED ({r['waived']})")
            else:
                parts.append("PASS")
            status = " ".join(parts)
            print(f"  {code:<4}  {status:<20}  {r['name']}")
            for f in r["findings"]:
                print(f)
            for f in r["waived_findings"]:
                print(f)
        if all_expired:
            print()
            print("EXPIRED WAIVERS — these must be resolved before the gate can pass:")
            for e in all_expired:
                print(e)
        if done_warns:
            print()
            print(
                "Done-ticket waivers (review for cleanup — does not affect exit code):"
            )
            for w in done_warns:
                print(w)
        print()
        if all_expired:
            print("GATE: RED — expired waiver(s) must be cleaned up.")
        elif total_violations == 0:
            suffix = f" ({total_waived} waived)" if total_waived else ""
            print(f"GATE: GREEN — no active violations{suffix}.")
        else:
            print(
                f"GATE: RED — {total_violations} violation(s) across "
                f"{sum(1 for r in results.values() if r['violations'] > 0)} check(s). "
                f"Fix before merging."
            )

    if all_expired:
        return 1
    return 0 if total_violations == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
