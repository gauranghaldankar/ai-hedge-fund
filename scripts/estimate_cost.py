#!/usr/bin/env python3
"""
AgentCo cost estimator — projects the spend of a full lifecycle pass BEFORE you run it.

Pure stdlib. Edit PRICING and the STAGES table to match your real routing and
measured token use. Numbers here are deliberate estimates for a single feature
slice; treat them as a planning model, not a quote.

Usage:
  python3 scripts/estimate_cost.py                 # one "medium" slice, build chain only
  python3 scripts/estimate_cost.py --scale large   # bigger feature
  python3 scripts/estimate_cost.py --teams 3       # 3x Agent-Teams parallel overhead on dev
  python3 scripts/estimate_cost.py --cache         # apply prompt caching to the stable prefix
  python3 scripts/estimate_cost.py --business      # include marketing/sales/finance/etc.
  python3 scripts/estimate_cost.py --slices-per-day 4   # extrapolate to a monthly figure
  python3 scripts/estimate_cost.py --batch         # 50% off (async stages only — see note)

Pricing last set from Anthropic's pricing page (June 2026). Verify at claude.com/pricing.
"""
import argparse

# --- editable pricing (USD per 1,000,000 tokens) -------------------------------
PRICING = {
    "opus":   {"in": 5.0, "out": 25.0},   # Opus 4.8
    "sonnet": {"in": 3.0, "out": 15.0},   # Sonnet 4.6
    "haiku":  {"in": 1.0, "out": 5.0},    # Haiku 4.5
}
OPENROUTER_FEE = 0.055   # credit-purchase fee (passthrough inference + ~5.5%)
CACHE_READ_MULT = 0.10   # cached input billed at 0.1x base input
CACHEABLE_FRACTION = 0.50  # share of input that is the stable CLAUDE.md + agent + skill prefix
BATCH_MULT = 0.50        # async batch discount (only valid for non-interactive stages)

SCALE = {"small": 0.6, "medium": 1.0, "large": 1.8}

# stage label, agent, model, input_K, output_K, calls, group
STAGES = [
    ("1   Vision/plan",        "ceo",                  "opus",   8,  2,  1, "build"),
    ("2-3 Requirements",       "product-manager",      "sonnet", 15, 5,  1, "build"),
    ("4-6 Architecture+spec",  "architect",            "opus",   30, 12, 1, "build"),
    ("7   UX design",          "ux-designer",          "sonnet", 18, 6,  1, "build"),
    ("8   Decompose",          "eng-manager",          "sonnet", 12, 3,  1, "build"),
    ("8   Backend dev",        "backend-engineer",     "sonnet", 45, 15, 1, "build"),
    ("8   Frontend dev",       "frontend-engineer",    "sonnet", 40, 14, 1, "build"),
    ("8   DB/migrations",      "database-engineer",    "sonnet", 20, 6,  1, "build"),
    ("9   Code review",        "code-reviewer",        "opus",   25, 5,  1, "build"),
    ("10  Testing",            "qa-engineer",          "sonnet", 30, 8,  1, "build"),
    ("11  Security review",    "security-engineer",    "opus",   25, 7,  1, "build"),
    ("12  Performance",        "performance-engineer", "sonnet", 20, 5,  1, "build"),
    ("13  Documentation",      "docs-writer",          "haiku",  22, 10, 1, "build"),
    ("14  Release prep",       "release-manager",      "sonnet", 12, 3,  1, "build"),
    ("15  DevOps/deploy",      "devops-sre",           "sonnet", 25, 8,  1, "build"),
    ("--  Eval (per gate)",    "eval-judge",           "opus",   8,  2,  10, "build"),
    # business / post-launch — only with --business
    ("16  Support",            "support",              "sonnet", 15, 6,  1, "business"),
    ("17  Marketing",          "marketing",            "sonnet", 25, 12, 1, "business"),
    ("18  Sales prep",         "sales",                "sonnet", 15, 8,  1, "business"),
    ("19  Finance",            "finance",              "sonnet", 12, 4,  1, "business"),
    ("--  Analytics",          "data-analyst",         "sonnet", 18, 5,  1, "business"),
    ("--  Legal drafts",       "legal",                "opus",   20, 10, 1, "business"),
]

# Spec-driven variant: no CEO/UX, adds spec-analyst + traceability
STAGES_SPEC = [
    ("0a  Spec intake (A)",    "spec-analyst",         "opus",   20, 8,  1, "build"),
    ("0b  Spec intake (B)",    "spec-analyst",         "opus",   12, 5,  1, "build"),
    ("4-6 Architecture+spec",  "architect",            "opus",   30, 12, 1, "build"),
    ("8   Decompose",          "eng-manager",          "sonnet", 12, 3,  1, "build"),
    ("8   Backend dev",        "backend-engineer",     "sonnet", 45, 15, 1, "build"),
    ("8   Frontend dev",       "frontend-engineer",    "sonnet", 40, 14, 1, "build"),
    ("8   DB/migrations",      "database-engineer",    "sonnet", 20, 6,  1, "build"),
    ("9   Code review",        "code-reviewer",        "opus",   25, 5,  1, "build"),
    ("10  Testing",            "qa-engineer",          "sonnet", 30, 8,  1, "build"),
    ("11  Security review",    "security-engineer",    "opus",   25, 7,  1, "build"),
    ("12  Performance",        "performance-engineer", "sonnet", 20, 5,  1, "build"),
    ("13  Documentation",      "docs-writer",          "haiku",  22, 10, 1, "build"),
    ("14  Release prep",       "release-manager",      "sonnet", 12, 3,  1, "build"),
    ("15  DevOps/deploy",      "devops-sre",           "sonnet", 25, 8,  1, "build"),
    ("--  Traceability",       "eval-judge",           "opus",   10, 3,  1, "build"),
    ("--  Eval (per gate)",    "eval-judge",           "opus",   8,  2,  8, "build"),
    # business / post-launch — only with --business
    ("16  Support",            "support",              "sonnet", 15, 6,  1, "business"),
    ("17  Marketing",          "marketing",            "sonnet", 25, 12, 1, "business"),
    ("18  Sales prep",         "sales",                "sonnet", 15, 8,  1, "business"),
    ("19  Finance",            "finance",              "sonnet", 12, 4,  1, "business"),
    ("--  Analytics",          "data-analyst",         "sonnet", 18, 5,  1, "business"),
    ("--  Legal drafts",       "legal",                "opus",   20, 10, 1, "business"),
]


def stage_cost(in_k, out_k, calls, model, scale, teams_mult, use_cache, use_batch):
    in_tok = in_k * 1000 * scale * calls * teams_mult
    out_tok = out_k * 1000 * scale * calls * teams_mult
    p = PRICING[model]
    if use_cache:
        cached = in_tok * CACHEABLE_FRACTION
        fresh = in_tok - cached
        in_cost = (fresh * p["in"] + cached * p["in"] * CACHE_READ_MULT) / 1e6
    else:
        in_cost = in_tok * p["in"] / 1e6
    out_cost = out_tok * p["out"] / 1e6
    cost = in_cost + out_cost
    if use_batch:
        cost *= BATCH_MULT
    return in_tok, out_tok, cost


def main():
    ap = argparse.ArgumentParser(description="Estimate the cost of an AgentCo lifecycle pass.")
    ap.add_argument("--scale", choices=SCALE, default="medium")
    ap.add_argument("--teams", type=float, default=1.0, help="Agent-Teams parallel multiplier on dev stages")
    ap.add_argument("--cache", action="store_true", help="apply prompt caching to the stable prefix")
    ap.add_argument("--batch", action="store_true", help="50%% async batch discount (async stages only)")
    ap.add_argument("--business", action="store_true", help="include marketing/sales/finance/etc.")
    ap.add_argument("--spec", action="store_true", help="use spec-driven pipeline stages (no CEO/UX, adds spec-analyst + traceability)")
    ap.add_argument("--slices-per-day", type=float, default=0, help="extrapolate to a monthly figure")
    args = ap.parse_args()

    scale = SCALE[args.scale]
    stages = STAGES_SPEC if args.spec else STAGES
    rows, totals = [], {"in": 0, "out": 0, "api": 0.0}
    for label, agent, model, in_k, out_k, calls, group in stages:
        if group == "business" and not args.business:
            continue
        teams_mult = args.teams if group == "build" and agent.endswith("engineer") else 1.0
        in_tok, out_tok, cost = stage_cost(in_k, out_k, calls, model, scale,
                                           teams_mult, args.cache, args.batch)
        rows.append((label, agent, model, in_tok, out_tok, cost))
        totals["in"] += in_tok
        totals["out"] += out_tok
        totals["api"] += cost

    w = 22
    mode = "spec-driven" if args.spec else "greenfield"
    print(f"\nAgentCo lifecycle cost estimate  "
          f"[mode={mode}  scale={args.scale}  teams={args.teams}x  cache={'on' if args.cache else 'off'}"
          f"  batch={'on' if args.batch else 'off'}]\n")
    print(f"{'Stage':<{w}}{'Agent':<22}{'Model':<8}{'In(K)':>8}{'Out(K)':>8}{'API $':>9}")
    print("-" * (w + 22 + 8 + 8 + 8 + 9))
    for label, agent, model, in_tok, out_tok, cost in rows:
        print(f"{label:<{w}}{agent:<22}{model:<8}"
              f"{in_tok/1000:>8.1f}{out_tok/1000:>8.1f}{cost:>9.3f}")
    print("-" * (w + 22 + 8 + 8 + 8 + 9))

    api = totals["api"]
    openrouter = api * (1 + OPENROUTER_FEE)
    print(f"{'TOTAL (one pass)':<{w}}{'':<22}{'':<8}"
          f"{totals['in']/1000:>8.1f}{totals['out']/1000:>8.1f}{api:>9.2f}")
    print()
    print(f"  Anthropic API (direct, metered) : ${api:0.2f}")
    print(f"  OpenRouter (+{OPENROUTER_FEE*100:.1f}% credit fee) : ${openrouter:0.2f}")
    print(f"  Max subscription (marginal)     : ~$0.00  (flat fee already paid; burns usage window)")

    if args.slices_per_day:
        monthly = api * args.slices_per_day * 30
        print(f"\n  At {args.slices_per_day:g} slices/day -> ~${monthly:0.0f}/mo on metered API.")
        for plan, price in (("Max 5x", 100), ("Max 20x", 200)):
            verdict = "subscription wins" if monthly > price else "metered API is cheaper"
            print(f"    vs {plan} (${price}/mo): {verdict}")

    print("\nNotes: estimates, not a quote — replace token figures with measured values.")
    print("OpenRouter fee is on credit purchases; for an Anthropic-only stack it adds cost, not value.")
    print("--batch only applies to genuinely async (non-interactive) stages; don't assume it for the live chain.\n")


if __name__ == "__main__":
    main()
