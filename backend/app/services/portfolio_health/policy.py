"""Deterministic Investor Profile -> Investment Policy Profile mapping.

`derive_policy` is pure: same profile in -> same policy out. It returns the risk
profile, allocation ranges + target midpoints, concentration limits, the
emergency-fund target (in months), the rebalance threshold, and a list of
*policy notes* — the caps/conflicts that fired, so the engine can cite them as
suitability findings.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import config as C


@dataclass(frozen=True)
class ProfileData:
    """Plain, engine-facing view of an InvestorProfile (no ORM dependency)."""

    primary_goal: str
    time_horizon: str
    risk_tolerance: str
    risk_capacity: str
    loss_reaction: str
    income_stability: str
    investment_knowledge: str
    monthly_income: float
    monthly_expenses: float
    emergency_fund_amount: float
    expected_large_expenses: list[dict] = field(default_factory=list)
    constraints: dict = field(default_factory=dict)
    base_currency: str = "CLP"
    tax_residence: str = ""


@dataclass(frozen=True)
class PolicyNote:
    code: str
    detail: dict


@dataclass(frozen=True)
class PolicyData:
    risk_profile: str
    target_allocation: dict[str, float]
    allocation_ranges: dict[str, list[float]]
    max_single_holding_pct: float
    max_single_stock_pct: float
    max_sector_pct: float
    max_country_pct: float
    max_currency_pct: float
    max_crypto_pct: float
    max_employer_stock_pct: float
    emergency_fund_target_months: float
    rebalance_threshold_pct: float
    notes: list[PolicyNote] = field(default_factory=list)


def _cap(profile: str, ceiling: str) -> str:
    """Return the lower-risk of two profiles."""
    if C.RISK_RANK[profile] <= C.RISK_RANK[ceiling]:
        return profile
    return ceiling


def _has_near_term_large_expense(profile: ProfileData, within_months: int = 24) -> bool:
    for item in profile.expected_large_expenses or []:
        try:
            months_away = float(item.get("months_away", 0))
            amount = float(item.get("amount", 0))
        except (TypeError, ValueError):
            continue
        if amount > 0 and 0 <= months_away <= within_months:
            return True
    return False


def derive_policy(profile: ProfileData) -> PolicyData:
    notes: list[PolicyNote] = []

    tol = C.RISK_SCALE_TO_PROFILE.get(profile.risk_tolerance, "moderate")
    cap = C.RISK_SCALE_TO_PROFILE.get(profile.risk_capacity, "moderate")

    # 1. Base: the lower of tolerance and capacity. Record any conflict.
    risk_profile = tol if C.RISK_RANK[tol] <= C.RISK_RANK[cap] else cap
    if tol != cap:
        notes.append(
            PolicyNote(
                "tolerance_capacity_conflict",
                {
                    "risk_tolerance": profile.risk_tolerance,
                    "risk_capacity": profile.risk_capacity,
                    "resolved_to": risk_profile,
                },
            )
        )

    # 2. Short horizon caps at conservative, unless very-high capacity and no
    #    near-term liquidity need (then moderate is allowed).
    if profile.time_horizon in ("lt_1y", "1_3y"):
        near_term = _has_near_term_large_expense(profile)
        if profile.risk_capacity == "very_high" and not near_term:
            ceiling = "moderate"
        else:
            ceiling = "conservative"
        capped = _cap(risk_profile, ceiling)
        if capped != risk_profile:
            notes.append(
                PolicyNote(
                    "horizon_cap",
                    {"time_horizon": profile.time_horizon, "capped_to": ceiling},
                )
            )
            risk_profile = capped

    # 3. Low tolerance or panic-sell reaction caps at moderate.
    if profile.risk_tolerance == "low" or profile.loss_reaction == "sell_after_10":
        capped = _cap(risk_profile, "moderate")
        if capped != risk_profile:
            notes.append(
                PolicyNote(
                    "loss_reaction_cap",
                    {
                        "risk_tolerance": profile.risk_tolerance,
                        "loss_reaction": profile.loss_reaction,
                        "capped_to": "moderate",
                    },
                )
            )
            risk_profile = capped

    # Allocation ranges + target midpoints for the resolved profile.
    ranges = C.ALLOCATION_RANGES[risk_profile]
    allocation_ranges = {k: [float(v[0]), float(v[1])] for k, v in ranges.items()}
    target_allocation = {k: round((v[0] + v[1]) / 2, 2) for k, v in ranges.items()}

    # Concentration limits (profile-driven crypto cap; constraint overrides if tighter).
    crypto_max = float(C.CRYPTO_MAX_BY_PROFILE[risk_profile])
    single_stock_max = float(C.CONCENTRATION_LIMITS["single_stock"])
    constraints = profile.constraints or {}
    if _is_number(constraints.get("max_crypto_pct")):
        crypto_max = min(crypto_max, float(constraints["max_crypto_pct"]))
    if _is_number(constraints.get("max_single_stock_pct")):
        single_stock_max = min(single_stock_max, float(constraints["max_single_stock_pct"]))

    # 4 & 5. Emergency-fund target: base + instability bump + near-term-expense bump.
    ef_months = C.EMERGENCY_FUND_BASE_MONTHS
    ef_months += C.EMERGENCY_FUND_INSTABILITY_BUMP.get(profile.income_stability, 0.0)
    if _has_near_term_large_expense(profile):
        ef_months += C.EMERGENCY_FUND_LARGE_EXPENSE_BUMP
        notes.append(PolicyNote("liquidity_target_raised", {"reason": "near_term_large_expense"}))

    return PolicyData(
        risk_profile=risk_profile,
        target_allocation=target_allocation,
        allocation_ranges=allocation_ranges,
        max_single_holding_pct=float(C.CONCENTRATION_LIMITS["single_holding"]),
        max_single_stock_pct=single_stock_max,
        max_sector_pct=float(C.CONCENTRATION_LIMITS["sector"]),
        max_country_pct=float(C.CONCENTRATION_LIMITS["country"]),
        max_currency_pct=float(C.CONCENTRATION_LIMITS["currency"]),
        max_crypto_pct=crypto_max,
        max_employer_stock_pct=float(C.CONCENTRATION_LIMITS["employer_stock"]),
        emergency_fund_target_months=ef_months,
        rebalance_threshold_pct=C.REBALANCE_THRESHOLD_PCT,
        notes=notes,
    )


def _is_number(v: object) -> bool:
    if v is None:
        return False
    try:
        float(v)  # type: ignore[arg-type]
        return True
    except (TypeError, ValueError):
        return False
