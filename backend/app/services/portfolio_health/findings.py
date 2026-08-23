"""Finding catalog + Finding dataclass.

Findings are data-driven: every finding has a stable `fid` (finding id) and
templated prose in CATALOG, so wording is consistent and testable, and the
scorer can map score penalties back to the findings that caused them. Evidence
and (where dynamic) severity are filled by the engine.

Educational framing only — every finding sets prohibited_specific_advice=True
and the guidance is phrased as a review point, never a buy/sell instruction.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Finding:
    fid: str
    category: str
    severity: str  # low | medium | high
    finding: str
    evidence: dict = field(default_factory=dict)
    why_it_matters: str = ""
    educational_guidance: str = ""
    prohibited_specific_advice: bool = True

    def to_dict(self) -> dict:
        return {
            "id": self.fid,
            "category": self.category,
            "severity": self.severity,
            "finding": self.finding,
            "evidence": self.evidence,
            "whyItMatters": self.why_it_matters,
            "educationalGuidance": self.educational_guidance,
            "prohibitedSpecificAdvice": self.prohibited_specific_advice,
        }


# Static text keyed by finding id. {placeholders} are filled by the engine.
# severity here is the *default*; the engine may override (e.g. by gap distance).
CATALOG: dict[str, dict] = {
    # --- suitability ---
    "suitability.tolerance_capacity_conflict": {
        "category": "suitability",
        "severity": "medium",
        "finding": "Stated risk tolerance and risk capacity disagree; the lower of the two was used.",
        "whyItMatters": (
            "Risk tolerance is how much volatility feels comfortable; risk capacity is how much "
            "the finances can absorb. When they diverge, a portfolio set to the higher level can "
            "exceed what the situation can safely support."
        ),
        "educationalGuidance": (
            "The user may want to review which of the two answers best reflects their situation "
            "before relying on the assigned risk profile."
        ),
    },
    "suitability.horizon_cap": {
        "category": "suitability",
        "severity": "medium",
        "finding": "A short investment time horizon limited the suitable risk profile.",
        "whyItMatters": (
            "Money needed within a few years has little time to recover from a market decline, so "
            "a lower-risk profile is generally more appropriate over short horizons."
        ),
        "educationalGuidance": (
            "The user may want to confirm the time horizon is accurate, since it constrains how "
            "much market risk is appropriate."
        ),
    },
    "suitability.loss_reaction_cap": {
        "category": "suitability",
        "severity": "medium",
        "finding": "Low risk tolerance or a sell-on-drop reaction limited the suitable risk profile.",
        "whyItMatters": (
            "Selling after a drop locks in losses. If the likely reaction to a decline is to sell, "
            "a lower-risk profile reduces the chance of that scenario."
        ),
        "educationalGuidance": (
            "The user may want to review whether the portfolio's risk matches how they would "
            "actually behave in a downturn."
        ),
    },
    # --- asset allocation ---
    "asset_allocation.above_range": {
        "category": "asset_allocation",
        "severity": "medium",
        "finding": "{bucket_label} allocation is above the target range for this profile.",
        "whyItMatters": (
            "Holding more of a higher-risk asset class than the profile targets can increase "
            "drawdown risk during market declines."
        ),
        "educationalGuidance": (
            "The user may want to review whether their selected risk profile still matches their "
            "actual portfolio, or whether the allocation has drifted."
        ),
    },
    "asset_allocation.below_range": {
        "category": "asset_allocation",
        "severity": "low",
        "finding": "{bucket_label} allocation is below the target range for this profile.",
        "whyItMatters": (
            "Holding less of an asset class than the profile targets can mean the portfolio is "
            "taking on more or less risk than intended for its goals."
        ),
        "educationalGuidance": (
            "The user may want to review whether this gap is intentional or a sign the portfolio "
            "has drifted from its targets."
        ),
    },
    # --- concentration ---
    "concentration.single_holding": {
        "category": "concentration",
        "severity": "medium",
        "finding": "A single holding ({ticker}) exceeds the concentration limit for one position.",
        "whyItMatters": (
            "A large position in one holding ties the portfolio's outcome to a single asset, which "
            "raises the impact of any problem specific to it."
        ),
        "educationalGuidance": (
            "The user may want to review how much of the portfolio depends on this one position."
        ),
    },
    "concentration.single_stock": {
        "category": "concentration",
        "severity": "medium",
        "finding": "Individual-stock exposure ({ticker}) exceeds the single-stock limit.",
        "whyItMatters": (
            "Individual stocks carry company-specific risk that diversified funds spread out. A "
            "large single-stock position concentrates that risk."
        ),
        "educationalGuidance": (
            "The user may want to review the role of individual stocks relative to diversified "
            "funds in the portfolio."
        ),
    },
    "concentration.crypto": {
        "category": "concentration",
        "severity": "high",
        "finding": "Crypto exposure ({current_pct}%) exceeds the policy limit ({limit_pct}%).",
        "whyItMatters": (
            "Crypto is highly volatile and can fall sharply and quickly. A large allocation "
            "increases the portfolio's overall swing and concentration risk."
        ),
        "educationalGuidance": (
            "The user may want to review whether the crypto allocation reflects the volatility and "
            "concentration they intend to carry."
        ),
    },
    "concentration.employer_stock": {
        "category": "concentration",
        "severity": "high",
        "finding": "Employer-stock exposure ({ticker}) exceeds the employer-stock limit.",
        "whyItMatters": (
            "When a large holding is also the employer, salary and investments depend on the same "
            "company — a setback there can affect both at once."
        ),
        "educationalGuidance": (
            "The user may want to review how concentrated their finances are in their employer."
        ),
    },
    # --- risk mismatch ---
    "volatility.risk_above_profile": {
        "category": "volatility",
        "severity": "medium",
        "finding": "The portfolio's risk proxies look higher than the assigned risk profile implies.",
        "whyItMatters": (
            "When equity, crypto, and single-stock exposure are high relative to the profile, the "
            "portfolio can experience larger swings than the profile is meant to allow."
        ),
        "educationalGuidance": (
            "The user may want to review whether the portfolio's actual risk matches the profile "
            "they selected."
        ),
    },
    # --- data quality ---
    "data_quality.unknown_asset_class": {
        "category": "data_quality",
        "severity": "low",
        "finding": "{count} holding(s) could not be classified into an asset class.",
        "whyItMatters": (
            "Unclassified holdings are left out of the allocation and concentration analysis, so "
            "the review is less complete."
        ),
        "educationalGuidance": (
            "The user may want to set an asset class for these holdings to improve the review's "
            "accuracy."
        ),
    },
    "data_quality.missing_price": {
        "category": "data_quality",
        "severity": "low",
        "finding": "{count} holding(s) have no current price and were valued at zero.",
        "whyItMatters": (
            "Holdings without a price do not contribute to the totals, so allocation and "
            "concentration percentages may be understated."
        ),
        "educationalGuidance": (
            "The user may want to set a manual price for these holdings so they are included."
        ),
    },
    "data_quality.high_unknown_fraction": {
        "category": "data_quality",
        "severity": "medium",
        "finding": "More than 25% of the portfolio (by value) could not be classified.",
        "whyItMatters": (
            "When a large share of the portfolio is unclassified, the allocation, concentration, "
            "and risk findings are based on partial data."
        ),
        "educationalGuidance": (
            "The review accuracy is limited. The user may want to classify these holdings before "
            "relying on the results."
        ),
    },
    # --- liquidity ---
    "liquidity.emergency_fund_critical": {
        "category": "liquidity",
        "severity": "high",
        "finding": "Cash covers less than one month of expenses — a critical liquidity shortfall.",
        "whyItMatters": (
            "With less than a month of expenses in cash, an unexpected bill or income disruption "
            "could force selling investments at an inopportune time."
        ),
        "educationalGuidance": (
            "Building at least a few months of expenses in a liquid, low-risk account is typically "
            "the first priority before increasing investment exposure."
        ),
    },
    "liquidity.emergency_fund_below_target": {
        "category": "liquidity",
        "severity": "medium",
        "finding": "Emergency fund is below the target of {ef_target_months:.1f} months of expenses.",
        "whyItMatters": (
            "An emergency fund creates a buffer that lets the investment portfolio stay invested "
            "through short-term disruptions without forced liquidation."
        ),
        "educationalGuidance": (
            "The user may want to review whether the cash buffer matches their income stability "
            "and any upcoming large expenses."
        ),
    },
    "liquidity.large_expense_gap": {
        "category": "liquidity",
        "severity": "medium",
        "finding": "Cash reserves appear insufficient to cover near-term planned expenses.",
        "whyItMatters": (
            "If planned expenses exceed available cash, investments may need to be sold to cover "
            "them — potentially at an inconvenient time."
        ),
        "educationalGuidance": (
            "The user may want to review whether the cash available aligns with expected outflows "
            "in the next 24 months."
        ),
    },
    # --- rebalancing ---
    "rebalancing.drift_above_threshold": {
        "category": "rebalancing",
        "severity": "low",
        "finding": "{bucket_label} allocation has drifted {drift_pct:.1f}pp from its target midpoint.",
        "whyItMatters": (
            "Drift from target allocation changes the portfolio's risk-return profile relative to "
            "what the investor policy specifies."
        ),
        "educationalGuidance": (
            "The user may want to review whether the drift is intentional or a signal that "
            "rebalancing is worth considering."
        ),
    },
    # --- sector (Stage 4) ---
    "sector.over_limit": {
        "category": "sector",
        "severity": "medium",
        "finding": "{sector} sector exposure ({current_pct:.1f}%) exceeds the {limit_pct:.0f}% concentration limit.",
        "whyItMatters": (
            "A large allocation to a single sector ties the portfolio to the performance and risks "
            "of that industry. Sector downturns can be deep and prolonged."
        ),
        "educationalGuidance": (
            "The user may want to review whether the sector concentration is intentional or a sign "
            "that diversification across industries would reduce risk."
        ),
    },
    # --- geography (Stage 4) ---
    "geography.over_limit": {
        "category": "geography",
        "severity": "medium",
        "finding": "{country} country exposure ({current_pct:.1f}%) exceeds the {limit_pct:.0f}% limit.",
        "whyItMatters": (
            "Heavy concentration in one country creates exposure to that country's economic, "
            "political, and currency risks all at once."
        ),
        "educationalGuidance": (
            "The user may want to review whether geographic diversification would reduce single-country "
            "risk relative to their goals."
        ),
    },
    # --- currency (Stage 4) ---
    "currency.over_limit": {
        "category": "currency",
        "severity": "medium",
        "finding": "{currency} currency exposure ({current_pct:.1f}%) exceeds the {limit_pct:.0f}% limit.",
        "whyItMatters": (
            "Large exposure to a single foreign currency means the portfolio's value in the home "
            "currency fluctuates with that exchange rate, adding FX risk on top of market risk."
        ),
        "educationalGuidance": (
            "The user may want to review whether the FX exposure is consistent with their income, "
            "spending currency, and goals."
        ),
    },
    # --- fees (Stage 4) ---
    "fees.high_weighted_expense_ratio": {
        "category": "fees",
        "severity": "medium",
        "finding": "Weighted-average expense ratio of {avg_er:.2f}% is above the {threshold:.2f}% reference level.",
        "whyItMatters": (
            "Ongoing fund fees are deducted from returns every year. A difference of half a percent "
            "compounds into a material drag on long-term growth."
        ),
        "educationalGuidance": (
            "The user may want to review whether lower-cost index funds or ETFs could achieve a "
            "similar allocation at a lower cost."
        ),
    },
    "fees.very_high_weighted_expense_ratio": {
        "category": "fees",
        "severity": "high",
        "finding": "Weighted-average expense ratio of {avg_er:.2f}% is high and will significantly erode returns over time.",
        "whyItMatters": (
            "At high expense ratios the drag from fees becomes a dominant factor in long-term "
            "outcomes — a 1.5% annual fee can reduce a portfolio's final value by 25–40% over "
            "30 years relative to a 0.1% fee alternative."
        ),
        "educationalGuidance": (
            "The user may want to review whether the fee level is justified by active management "
            "or whether lower-cost alternatives exist for the same exposure."
        ),
    },
    "fees.data_missing": {
        "category": "fees",
        "severity": "low",
        "finding": "{count} holding(s) have no fee data; the cost-efficiency score is based on partial information.",
        "whyItMatters": (
            "Without expense ratios for all holdings the weighted-average fee calculation is "
            "incomplete, so the cost-efficiency score may understate the true cost."
        ),
        "educationalGuidance": (
            "The user may want to add expense ratio data for these holdings via the metadata editor "
            "to get a more accurate fee picture."
        ),
    },
    # --- drawdown ---
    "drawdown.worst_case_exceeds_threshold": {
        "category": "drawdown",
        "severity": "medium",
        "finding": (
            "A stress scenario suggests a potential portfolio loss of ~{impact_pct:.0f}%, "
            "which exceeds the ~{threshold_pct:.0f}% concern threshold for this risk profile."
        ),
        "whyItMatters": (
            "Large drawdowns can be psychologically difficult to ride out and may coincide with "
            "other financial stress, increasing the chance of selling at a loss."
        ),
        "educationalGuidance": (
            "These are estimates based on historical shock magnitudes, not predictions. The user "
            "may want to review whether the portfolio's downside risk feels consistent with the "
            "risk profile they selected."
        ),
    },
}


def build(fid: str, *, evidence: dict | None = None, severity: str | None = None, **fmt: object) -> Finding:
    """Construct a Finding from the catalog, formatting prose with **fmt."""
    spec = CATALOG[fid]
    return Finding(
        fid=fid,
        category=spec["category"],
        severity=severity or spec["severity"],
        finding=spec["finding"].format(**fmt) if fmt else spec["finding"],
        evidence=evidence or {},
        why_it_matters=spec["whyItMatters"],
        educational_guidance=spec["educationalGuidance"],
    )
