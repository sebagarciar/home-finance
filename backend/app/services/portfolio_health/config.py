"""Policy defaults for the Portfolio Health rules engine.

Every tunable threshold lives here as a typed constant so it can be edited in one
place (and later moved to an admin settings table) without touching engine logic.
All percentages are 0–100 (not fractions). Allocation buckets are the *policy*
buckets — current holdings are mapped into these by classify.py.
"""
from __future__ import annotations

RiskProfile = str  # "conservative" | "moderate" | "growth" | "aggressive"
RISK_PROFILES: tuple[str, ...] = ("conservative", "moderate", "growth", "aggressive")
# Rank for "take the lower of tolerance/capacity" and for capping.
RISK_RANK: dict[str, int] = {"conservative": 0, "moderate": 1, "growth": 2, "aggressive": 3}

# Maps the qualitative tolerance/capacity scale to a risk profile.
RISK_SCALE_TO_PROFILE: dict[str, str] = {
    "low": "conservative",
    "moderate": "moderate",
    "high": "growth",
    "very_high": "aggressive",
}

# Policy allocation buckets (the canonical set the engine reports against).
ALLOCATION_BUCKETS: tuple[str, ...] = (
    "cash",
    "bonds",
    "global_equities",
    "alternatives",
    "crypto",
)

# {risk_profile: {bucket: (min_pct, max_pct)}}
ALLOCATION_RANGES: dict[str, dict[str, tuple[float, float]]] = {
    "conservative": {
        "cash": (10, 25),
        "bonds": (45, 70),
        "global_equities": (15, 40),
        "alternatives": (0, 10),
        "crypto": (0, 2),
    },
    "moderate": {
        "cash": (5, 15),
        "bonds": (25, 45),
        "global_equities": (40, 65),
        "alternatives": (0, 10),
        "crypto": (0, 5),
    },
    "growth": {
        "cash": (3, 10),
        "bonds": (10, 30),
        "global_equities": (60, 85),
        "alternatives": (0, 15),
        "crypto": (0, 8),
    },
    "aggressive": {
        "cash": (0, 10),
        "bonds": (0, 20),
        "global_equities": (75, 95),
        "alternatives": (0, 20),
        "crypto": (0, 10),
    },
}

# Concentration limits (percent of total portfolio value).
CONCENTRATION_LIMITS: dict[str, float] = {
    "single_holding": 10,
    "single_stock": 10,
    "diversified_fund": 40,
    "sector": 30,
    "country": 70,
    "currency": 80,
    "employer_stock": 10,
}

# Crypto cap depends on risk profile (overrides the per-profile allocation max).
CRYPTO_MAX_BY_PROFILE: dict[str, float] = {
    "conservative": 2,
    "moderate": 5,
    "growth": 8,
    "aggressive": 10,
}

# Emergency-fund target (months of expenses), before income-stability bumps.
EMERGENCY_FUND_BASE_MONTHS: float = 3.0
# Extra months added when income is not a stable salary.
EMERGENCY_FUND_INSTABILITY_BUMP: dict[str, float] = {
    "stable": 0.0,
    "retired": 0.0,
    "variable": 3.0,
    "self_employed": 3.0,
    "unemployed": 3.0,
}
# Extra months when a large expense falls within the next 24 months.
EMERGENCY_FUND_LARGE_EXPENSE_BUMP: float = 3.0

# Default drift band before a rebalance is flagged (percentage points).
REBALANCE_THRESHOLD_PCT: float = 5.0

# Scoring weights (must sum to 1.0).
SCORE_WEIGHTS: dict[str, float] = {
    "goalAlignmentScore": 0.20,
    "riskAlignmentScore": 0.25,
    "diversificationScore": 0.20,
    "liquidityScore": 0.15,
    "costEfficiencyScore": 0.10,
    "dataQualityScore": 0.10,
}

# Penalty applied to a sub-score per finding of each severity.
SEVERITY_PENALTY: dict[str, float] = {"low": 5, "medium": 15, "high": 30}

# Which sub-score each finding category penalizes.
CATEGORY_TO_SUBSCORE: dict[str, str] = {
    "suitability": "goalAlignmentScore",
    "asset_allocation": "riskAlignmentScore",
    "volatility": "riskAlignmentScore",
    "drawdown": "riskAlignmentScore",
    "concentration": "diversificationScore",
    "sector": "diversificationScore",
    "geography": "diversificationScore",
    "currency": "diversificationScore",
    "liquidity": "liquidityScore",
    "rebalancing": "riskAlignmentScore",
    "fees": "costEfficiencyScore",
    "tax_awareness": "goalAlignmentScore",
    "data_quality": "dataQualityScore",
}

# If more than this fraction (by value) of holdings are unknown, cap data quality.
UNKNOWN_HOLDINGS_WARN_FRACTION: float = 0.25
UNKNOWN_HOLDINGS_SCORE_CAP: float = 50.0

# Stress-test shocks (Stage 2). Negative = loss; currency is a strengthening of
# the home currency (CLP) against foreign assets.
STRESS_SHOCKS: dict[str, float] = {
    "equity": -0.30,
    "bonds": -0.10,
    "crypto": -0.60,
    "largest_holding": -0.50,
    "home_currency_strength": 0.10,
}

# Stage 4 — fee thresholds (expense ratio in %, 0–100 scale).
# Above WARN → medium finding; above HIGH → high finding.
FEE_WARN_THRESHOLD: float = 0.75
FEE_HIGH_THRESHOLD: float = 1.50

# Drawdown concern threshold per risk profile (portfolio-level impact, negative = loss).
# A finding is emitted if any stress scenario breaches this threshold.
DRAWDOWN_CONCERN_THRESHOLD: dict[str, float] = {
    "conservative": -10.0,
    "moderate": -20.0,
    "growth": -30.0,
    "aggressive": -40.0,
}
