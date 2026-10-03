"""Risk answers -> target mix. Pure: same answers in, same policy out.

The risk profile is the lower of tolerance and capacity, then capped by a
short horizon (unless capacity is very high and nothing big is planned soon)
and by a low tolerance or a sell-after-a-drop reaction. `notes` records each
rule that fired so the UI can say why the target is what it is.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import config as C


@dataclass(frozen=True)
class RiskAnswers:
    time_horizon: str  # lt_1y | 1_3y | 3_7y | 7_15y | gt_15y
    risk_tolerance: str  # low | moderate | high | very_high
    risk_capacity: str
    loss_reaction: str  # sell_after_10 | hold_uncomfortable | invest_more | unsure
    # Upcoming planned expenses ({amount, months_away}) from the household profile.
    planned_expenses: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class PolicyNote:
    code: str
    detail: dict


@dataclass(frozen=True)
class Policy:
    risk_profile: str
    target_allocation: dict[str, float]  # bucket -> midpoint pct
    allocation_ranges: dict[str, tuple[float, float]]
    notes: list[PolicyNote] = field(default_factory=list)


def _cap(profile: str, ceiling: str) -> str:
    """The lower-risk of two profiles."""
    return profile if C.RISK_RANK[profile] <= C.RISK_RANK[ceiling] else ceiling


def _near_term_expense(answers: RiskAnswers) -> bool:
    return any(
        float(e.get("amount", 0)) > 0 and 0 <= float(e.get("months_away", 0)) <= C.NEAR_TERM_MONTHS
        for e in answers.planned_expenses
    )


def derive_policy(answers: RiskAnswers) -> Policy:
    notes: list[PolicyNote] = []

    tol = C.RISK_SCALE_TO_PROFILE.get(answers.risk_tolerance, "moderate")
    cap = C.RISK_SCALE_TO_PROFILE.get(answers.risk_capacity, "moderate")

    # 1. The lower of tolerance and capacity.
    profile = _cap(tol, cap)
    if tol != cap:
        notes.append(PolicyNote("tolerance_capacity_conflict", {"resolved_to": profile}))

    # 2. A short horizon caps at conservative, unless capacity is very high and
    #    nothing big is planned soon (then moderate).
    if answers.time_horizon in ("lt_1y", "1_3y"):
        ceiling = (
            "moderate"
            if answers.risk_capacity == "very_high" and not _near_term_expense(answers)
            else "conservative"
        )
        capped = _cap(profile, ceiling)
        if capped != profile:
            notes.append(PolicyNote("horizon_cap", {"time_horizon": answers.time_horizon, "capped_to": ceiling}))
            profile = capped

    # 3. Low tolerance or selling after a drop caps at moderate.
    if answers.risk_tolerance == "low" or answers.loss_reaction == "sell_after_10":
        capped = _cap(profile, "moderate")
        if capped != profile:
            notes.append(PolicyNote("loss_reaction_cap", {"capped_to": "moderate"}))
            profile = capped

    ranges = C.ALLOCATION_RANGES[profile]
    return Policy(
        risk_profile=profile,
        target_allocation={k: round((lo + hi) / 2, 2) for k, (lo, hi) in ranges.items()},
        allocation_ranges=dict(ranges),
        notes=notes,
    )
