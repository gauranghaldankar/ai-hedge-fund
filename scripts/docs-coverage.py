#!/usr/bin/env python3
"""docs-coverage.py — deterministic documentation coverage gate.

Sibling to traceability.py. Where traceability proves every AC has a test, this
proves every public API surface (HTTP route) is referenced by a doc. It is an
EXISTENCE check only: it proves a doc mentions the route, NOT that the doc is
correct, current, or useful — that judgment is the eval-judge's docs-review pass.
Existence is the floor (nothing user-facing ships undocumented); quality is the
ceiling and is not scriptable.

Ground truth = routes declared in source (the code is authoritative, not a
hand-written doc index — an agent can't hide an undocumented route by omitting it).
Coverage = the route's static path appears somewhere under docs/.

Exemptions: a route with an inline `# docs:internal` or `# docs:skip` marker on the
decorator line (or the line above) is exempt — for health/metrics/internal endpoints.
A small built-in ignore set covers the usual framework/observability paths. Justify
exemptions the way you'd justify a deviation ADR: an exemption is a decision, not a default.

Exit codes:
  0  GREEN   — every public route is documented or exempt
  1  RED     — at least one public route has no doc reference
  3  CONFIG  — bad invocation (project/docs dir missing, or no source found)
(3, not 2 — 2 is reserved for gate.sh's ESCALATE, matching traceability.py.)

Usage:
  python3 scripts/docs-coverage.py [--project <dir>] [--docs <dir>]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Python route decorators: @router.get("/x"), @app.post('/x'), @api.route("/x")
PY_ROUTE = re.compile(
    r'@\s*\w+\.(?:get|post|put|patch|delete|head|options|route)\s*\(\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
# JS/TS route calls: app.get('/x'), router.post("/x")
JS_ROUTE = re.compile(
    r'\b\w+\.(?:get|post|put|patch|delete)\s*\(\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
EXEMPT_MARKER = re.compile(r'docs:(?:internal|skip)', re.IGNORECASE)
PARAM_SPLIT = re.compile(r'[{:<]')  # first path parameter token: {id} / :id / <id>

# Framework/observability paths that are not user-facing product surface.
BUILTIN_IGNORE = {
    "/", "/health", "/healthz", "/livez", "/readyz", "/ready", "/live", "/ping",
    "/metrics", "/openapi.json", "/docs", "/redoc", "/favicon.ico", "/robots.txt",
}

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist",
             "build", "target", ".agentco", "docs"}


def static_lead(path: str) -> str:
    """Longest leading static segment of a route path (up to the first parameter)."""
    lead = PARAM_SPLIT.split(path, 1)[0].rstrip("/")
    return lead


def find_routes(root: Path) -> list[tuple[str, Path, int]]:
    """Return (path, file, lineno) for every route declaration in source."""
    out: list[tuple[str, Path, int]] = []
    for f in root.rglob("*"):
        if not f.is_file():
            continue
        if any(part in SKIP_DIRS for part in f.parts):
            continue
        if f.suffix == ".py":
            rx = PY_ROUTE
        elif f.suffix in (".js", ".ts", ".mjs", ".cjs"):
            rx = JS_ROUTE
        else:
            continue
        try:
            lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines):
            for m in rx.finditer(line):
                path = m.group(1)
                if not path.startswith("/"):
                    continue  # not an absolute route path (e.g. a URL, a glob)
                # exempt if marker on this line or the line above
                ctx = line + (lines[i - 1] if i > 0 else "")
                exempt = bool(EXEMPT_MARKER.search(ctx))
                out.append((path, f, i + 1) if not exempt else (f"!EXEMPT!{path}", f, i + 1))
    return out


def docs_corpus(docs_dir: Path) -> str:
    """All doc text concatenated (markdown + text under docs/)."""
    buf: list[str] = []
    for f in docs_dir.rglob("*"):
        if f.is_file() and f.suffix in (".md", ".mdx", ".rst", ".txt", ".html"):
            try:
                buf.append(f.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                pass
    return "\n".join(buf)


def main() -> int:
    ap = argparse.ArgumentParser(description="Deterministic documentation coverage gate.")
    ap.add_argument("--project", default=".", help="project root (default: cwd)")
    ap.add_argument("--docs", default=None, help="docs dir (default: <project>/docs)")
    args = ap.parse_args()

    root = Path(args.project).resolve()
    if not root.is_dir():
        print(f"CONFIG: project dir not found: {root}", file=sys.stderr)
        return 3
    docs_dir = Path(args.docs).resolve() if args.docs else root / "docs"
    if not docs_dir.is_dir():
        print(f"CONFIG: docs dir not found: {docs_dir} (create docs/ or pass --docs)", file=sys.stderr)
        return 3

    routes = find_routes(root)
    if not routes:
        print("CONFIG: no HTTP routes found in source — nothing to cover "
              "(this gate targets public API surface).", file=sys.stderr)
        return 3

    corpus = docs_corpus(docs_dir)

    covered: list[str] = []
    exempt: list[str] = []
    uncovered: list[tuple[str, Path, int]] = []
    unmatchable: list[tuple[str, Path, int]] = []
    seen: set[str] = set()

    for raw, f, ln in routes:
        is_exempt = raw.startswith("!EXEMPT!")
        path = raw[len("!EXEMPT!"):] if is_exempt else raw
        lead = static_lead(path)
        key = f"{path}"
        if key in seen:
            continue
        seen.add(key)
        if is_exempt or lead.lower() in BUILTIN_IGNORE or path.lower() in BUILTIN_IGNORE:
            exempt.append(path)
            continue
        if len(lead.lstrip("/")) < 2:
            # too generic to substring-match reliably (e.g. "/{id}") — flag, don't false-pass
            unmatchable.append((path, f, ln))
            continue
        if lead in corpus:
            covered.append(path)
        else:
            uncovered.append((path, f, ln))

    # write report
    report_dir = root / "docs" / "traceability"
    report_dir.mkdir(parents=True, exist_ok=True)
    lines = ["# Documentation Coverage", "",
             "> Mechanical floor: proves each route's static path is referenced in docs/.",
             "> A sub-route under a documented parent path counts as covered here — whether",
             "> the sub-action is actually described is the eval-judge's docs-review (semantic) job.",
             "",
             f"- routes found: {len(seen)}",
             f"- covered: {len(covered)}",
             f"- exempt: {len(exempt)}",
             f"- unmatchable (document manually): {len(unmatchable)}",
             f"- UNCOVERED: {len(uncovered)}", ""]
    if uncovered:
        lines += ["## Uncovered routes (no doc references them)", ""]
        lines += [f"- `{p}`  — {f.relative_to(root)}:{ln}" for p, f, ln in uncovered]
        lines.append("")
    if unmatchable:
        lines += ["## Unmatchable routes (static path too generic — verify a doc covers them)", ""]
        lines += [f"- `{p}`  — {f.relative_to(root)}:{ln}" for p, f, ln in unmatchable]
        lines.append("")
    (report_dir / "DOCS_COVERAGE.md").write_text("\n".join(lines))

    if uncovered:
        print(f"RED: {len(uncovered)} public route(s) undocumented "
              f"(of {len(seen)} found). See docs/traceability/DOCS_COVERAGE.md.")
        for p, f, ln in uncovered:
            print(f"  UNDOCUMENTED  {p}   ({f.relative_to(root)}:{ln})")
        print("  Add a doc under docs/ that references each path, or mark internal "
              "routes with '# docs:internal'.")
        return 1

    msg = f"GREEN: {len(covered)} route(s) documented"
    if exempt:
        msg += f", {len(exempt)} exempt"
    if unmatchable:
        msg += f"; {len(unmatchable)} unmatchable (verify manually — see report)"
    print(msg + ".")
    return 0


if __name__ == "__main__":
    sys.exit(main())
