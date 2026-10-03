"""Target-mix policy: risk profiles and the allocation range each one allows.

All percentages are 0–100. Holdings map into the buckets via their
`asset_class`; bank cash is the cash bucket.
"""
from __future__ import annotations

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

ALLOCATION_BUCKETS: tuple[str, ...] = ("cash", "bonds", "global_equities", "alternatives", "crypto")

BUCKET_LABELS: dict[str, str] = {
    "cash": "Cash",
    "bonds": "Bonds",
    "global_equities": "Equities",
    "alternatives": "Alternatives",
    "crypto": "Crypto",
    "unclassified": "Unclassified",
}

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

# Holding.asset_class (lowercased) -> bucket. Anything else is "unclassified".
ASSET_CLASS_TO_BUCKET: dict[str, str] = {
    "cash": "cash",
    "money_market": "cash",
    "bond": "bonds",
    "bonds": "bonds",
    "fixed_income": "bonds",
    "equity": "global_equities",
    "equities": "global_equities",
    "stock": "global_equities",
    "etf": "global_equities",
    "fund": "global_equities",
    "crypto": "crypto",
    "real_estate": "alternatives",
    "commodity": "alternatives",
    "other": "alternatives",
}

# A bucket inside its range but this far (pp) from the target midpoint is
# reported as drifting.
REBALANCE_THRESHOLD_PCT: float = 5.0

# A planned expense this close (months) counts as near-term for the horizon cap.
NEAR_TERM_MONTHS: int = 24
