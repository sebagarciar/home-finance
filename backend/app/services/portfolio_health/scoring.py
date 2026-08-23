"""Explainable Portfolio Health scoring.

Each sub-score starts at 100 and is penalized by the findings mapped to it
(SEVERITY_PENALTY, clamped >= 0). The overall score is the weighted sum
(SCORE_WEIGHTS). `score_explanation` records, per sub-score, which finding ids
caused which penalties — so the number is always traceable to findings.

The score is a diagnostic estimate based on available data, not a precise truth.
"""
from __future__ import annotations

from . import config as C
from . import findings as F


def score(findings: list[F.Finding], flags: dict | None = None) -> dict:
    flags = flags or {}
    sub_scores: dict[str, float] = dict.fromkeys(C.SCORE_WEIGHTS, 100.0)
    explanation: dict[str, list[dict]] = {k: [] for k in C.SCORE_WEIGHTS}

    for f in findings:
        sub = C.CATEGORY_TO_SUBSCORE.get(f.category)
        if sub is None:
            continue
        penalty = C.SEVERITY_PENALTY.get(f.severity, 0)
        sub_scores[sub] = max(0.0, sub_scores[sub] - penalty)
        explanation[sub].append({"finding_id": f.fid, "severity": f.severity, "penalty": penalty})

    # When too much of the portfolio is unclassified, cap data quality.
    if flags.get("data_quality_capped"):
        capped = min(sub_scores["dataQualityScore"], C.UNKNOWN_HOLDINGS_SCORE_CAP)
        if capped < sub_scores["dataQualityScore"]:
            explanation["dataQualityScore"].append(
                {"finding_id": "data_quality.high_unknown_fraction", "cap": C.UNKNOWN_HOLDINGS_SCORE_CAP}
            )
        sub_scores["dataQualityScore"] = capped

    sub_scores = {k: round(v, 2) for k, v in sub_scores.items()}
    overall = round(sum(sub_scores[k] * w for k, w in C.SCORE_WEIGHTS.items()), 2)

    return {
        "overall": overall,
        "sub_scores": sub_scores,
        "score_explanation": explanation,
        "weights": C.SCORE_WEIGHTS,
    }


def overall_status(overall: float, findings: list[F.Finding]) -> str:
    """Map score + worst severity to a status label for the UI banner."""
    has_high = any(f.severity == "high" for f in findings)
    if has_high and overall < 60:
        return "High risk mismatch"
    if overall < 60 or has_high:
        return "Review recommended"
    if overall < 80:
        return "Monitor"
    return "Looks aligned"
