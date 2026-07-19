"""
Composite score computation and threshold/shortlist logic.

The composite is a weighted average of 6 sub-scores.
Weights are passed in at call-time (from a WeightProfile) so stored sub-scores
can be re-combined client-side or server-side without re-running the screener.

Weight profiles (normalised to sum=1.0):
  medium_long: Valuation 30%, Fundamentals 25%, Jhunjhunwala 20%, Growth 15%, Insider 10%, Technical 0%
  short_term:  Technical 35%, Fundamentals 20%, Valuation 15%, Growth 15%, Insider 10%, Jhunjhunwala 5%
  custom:      user-defined (validated to sum=100%)

AC-0102, AC-0109 (weight profiles + threshold modes)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ThresholdMode = Literal["top25", "top5pct", "score60"]


@dataclass
class WeightProfile:
    name: str
    valuation: float
    fundamentals: float
    jhunjhunwala: float
    growth: float
    insider: float
    technical: float

    def __post_init__(self) -> None:
        total = (
            self.valuation
            + self.fundamentals
            + self.jhunjhunwala
            + self.growth
            + self.insider
            + self.technical
        )
        if not (0.999 < total < 1.001):
            raise ValueError(f"Weights must sum to 1.0, got {total:.4f}")


# Pre-defined profiles
MEDIUM_LONG = WeightProfile(
    name="medium_long",
    valuation=0.30,
    fundamentals=0.25,
    jhunjhunwala=0.20,
    growth=0.15,
    insider=0.10,
    technical=0.00,
)

SHORT_TERM = WeightProfile(
    name="short_term",
    valuation=0.15,
    fundamentals=0.20,
    jhunjhunwala=0.05,
    growth=0.15,
    insider=0.10,
    technical=0.35,
)

PROFILES: dict[str, WeightProfile] = {
    "medium_long": MEDIUM_LONG,
    "short_term": SHORT_TERM,
}


def compute_composite(
    valuation: float,
    fundamentals: float,
    jhunjhunwala: float,
    growth: float,
    insider: float,
    technical: float,
    profile: WeightProfile | None = None,
) -> float:
    """
    Compute composite score from 6 sub-scores using a WeightProfile.
    Defaults to MEDIUM_LONG if no profile supplied.
    """
    p = profile or MEDIUM_LONG
    return (
        p.valuation * valuation
        + p.fundamentals * fundamentals
        + p.jhunjhunwala * jhunjhunwala
        + p.growth * growth
        + p.insider * insider
        + p.technical * technical
    )


def apply_threshold(
    results: list[dict],
    mode: ThresholdMode,
) -> list[dict]:
    """
    Mark is_shortlisted on each result dict in-place (sorted by composite_score desc).
    Returns the same list with is_shortlisted set.

    AC-0109
    """
    sorted_results = sorted(results, key=lambda r: r.get("composite_score", 0.0), reverse=True)
    n = len(sorted_results)

    if mode == "top25":
        cutoff = 25
        for i, r in enumerate(sorted_results):
            r["is_shortlisted"] = i < cutoff
    elif mode == "top5pct":
        cutoff = max(1, round(n * 0.05))
        for i, r in enumerate(sorted_results):
            r["is_shortlisted"] = i < cutoff
    else:  # score60
        for r in sorted_results:
            r["is_shortlisted"] = r.get("composite_score", 0.0) >= 60.0

    return sorted_results


def colour_band(score: float) -> str:
    """Return colour band label for a composite score."""
    if score >= 80:
        return "deep_green"
    elif score >= 60:
        return "green"
    elif score >= 40:
        return "yellow"
    else:
        return "red"
