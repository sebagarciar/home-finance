"""Deterministic portfolio diagnostics + finding generation (Stage 1 + 2).

`run_review(profile, policy, snapshot, ...)` is pure: it consumes the
already-fetched net-worth snapshot (current_networth() shape) plus the profile and
derived policy, and returns diagnostics, structured findings, and missing-data
flags. No clock, network, or LLM calls. Same input ⇒ identical output.

Stage 1: asset allocation vs policy ranges, concentration, risk-mismatch proxy,
         data quality.
Stage 2: liquidity / emergency fund, rebalancing drift, stress-test scenarios,
         drawdown finding.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TypedDict

from . import config as C
from . import findings as F
from .classify import HoldingClass, classify_all
from .policy import PolicyData, ProfileData
from .stress import run_stress

_ZERO = Decimal("0")


class _HoldingPct(TypedDict):
    ticker: str
    pct: float
    value_in_base: str
    bucket: str
    is_single_stock: bool

BUCKET_LABELS: dict[str, str] = {
    "cash": "Cash",
    "bonds": "Bonds",
    "global_equities": "Equities",
    "alternatives": "Alternatives",
    "crypto": "Crypto",
    "unknown": "Unclassified",
}


@dataclass(frozen=True)
class ReviewResult:
    diagnostics: dict
    findings: list[F.Finding]
    missing_data: list[str]
    flags: dict = field(default_factory=dict)

    def findings_as_dicts(self) -> list[dict]:
        return [f.to_dict() for f in self.findings]


def _pct(part: Decimal, whole: Decimal) -> float:
    if whole <= _ZERO:
        return 0.0
    return round(float(part / whole * 100), 2)


def _cash_value(snapshot: dict) -> Decimal:
    """Positive cash sleeve (the 'cash' bucket of by_asset_class; debt excluded)."""
    for row in snapshot.get("by_asset_class", []):
        if row.get("asset_class") == "cash":
            return Decimal(str(row.get("total_in_base") or "0"))
    return _ZERO


def _allocation(classes: list[HoldingClass], cash_value: Decimal, policy: PolicyData) -> tuple[dict, Decimal]:
    bucket_value: dict[str, Decimal] = dict.fromkeys(C.ALLOCATION_BUCKETS, _ZERO)
    bucket_value["unknown"] = _ZERO
    bucket_value["cash"] += cash_value
    for hc in classes:
        bucket_value[hc.policy_bucket] = bucket_value.get(hc.policy_bucket, _ZERO) + hc.value_in_base

    invested = sum(bucket_value.values(), _ZERO)
    current_pct = {b: _pct(v, invested) for b, v in bucket_value.items()}

    out_of_range: list[dict] = []
    for bucket, (lo, hi) in policy.allocation_ranges.items():
        cur = current_pct.get(bucket, 0.0)
        if cur > hi + 0.001:
            out_of_range.append({"bucket": bucket, "current_pct": cur, "range": [lo, hi], "direction": "above"})
        elif cur < lo - 0.001:
            out_of_range.append({"bucket": bucket, "current_pct": cur, "range": [lo, hi], "direction": "below"})

    allocation = {
        "portfolio_value_in_base": str(invested),
        "current_pct": current_pct,
        "current_value_in_base": {b: str(v) for b, v in bucket_value.items()},
        "target_ranges": {b: list(r) for b, r in policy.allocation_ranges.items()},
        "out_of_range": out_of_range,
    }
    return allocation, invested


def _concentration(classes: list[HoldingClass], invested: Decimal, profile: ProfileData) -> dict:
    ranked = sorted(classes, key=lambda h: (-h.value_in_base, h.ticker))
    holdings_pct: list[_HoldingPct] = [
        {"ticker": h.ticker, "pct": _pct(h.value_in_base, invested), "value_in_base": str(h.value_in_base),
         "bucket": h.policy_bucket, "is_single_stock": h.is_single_stock}
        for h in ranked
    ]

    def _top_n(n: int) -> float:
        return round(sum(r["pct"] for r in holdings_pct[:n]), 2)

    largest = holdings_pct[0] if holdings_pct else None

    # Largest single-stock position.
    stocks = [r for r in holdings_pct if r["is_single_stock"]]
    largest_stock = max(stocks, key=lambda r: r["pct"], default=None)

    crypto_pct = round(sum(_pct(h.value_in_base, invested) for h in classes if h.is_crypto), 2)

    employer_ticker = str((profile.constraints or {}).get("employer_stock_ticker") or "").strip().upper()
    employer_pct = 0.0
    if employer_ticker:
        employer_pct = round(
            sum(r["pct"] for r in holdings_pct if r["ticker"] == employer_ticker), 2
        )

    return {
        "top1_pct": _top_n(1),
        "top3_pct": _top_n(3),
        "top5_pct": _top_n(5),
        "largest_holding": largest,
        "largest_single_stock": largest_stock,
        "crypto_pct": crypto_pct,
        "employer_stock_ticker": employer_ticker or None,
        "employer_stock_pct": employer_pct,
        "holdings": holdings_pct,
    }


def _gap_severity(current: float, lo: float, hi: float) -> str:
    """Severity scales with distance outside the range (percentage points)."""
    distance = current - hi if current > hi else lo - current
    if distance >= 15:
        return "high"
    if distance >= 5:
        return "medium"
    return "low"


def _liquidity(
    cash_clp: Decimal,
    avg_monthly_expenses_clp: float,
    emergency_fund_clp: float,
    policy: PolicyData,
    large_expenses_clp: list[dict],
) -> tuple[dict, list[F.Finding]]:
    """Liquidity / emergency-fund diagnostics.

    All amounts must be pre-converted to CLP by the caller so this stays pure.
    Returns (diagnostics_dict, findings_list).  If avg_monthly_expenses_clp == 0
    (data unavailable) the EF-months calculation is skipped to avoid division by
    zero and no liquidity findings are emitted.
    """
    out: list[F.Finding] = []
    monthly_exp = Decimal(str(avg_monthly_expenses_clp)) if avg_monthly_expenses_clp > 0 else _ZERO
    ef_declared = Decimal(str(emergency_fund_clp))

    ef_months_current: float | None = None
    if monthly_exp > _ZERO:
        ef_months_current = round(float(cash_clp / monthly_exp), 2)
        ef_target = policy.emergency_fund_target_months

        if ef_months_current < 1.0:
            out.append(
                F.build(
                    "liquidity.emergency_fund_critical",
                    severity="high",
                    evidence={
                        "efMonthsCurrent": ef_months_current,
                        "efMonthsTarget": ef_target,
                        "cashCLP": str(cash_clp),
                        "monthlyExpensesCLP": str(monthly_exp),
                    },
                )
            )
        elif ef_months_current < ef_target:
            out.append(
                F.build(
                    "liquidity.emergency_fund_below_target",
                    severity="medium",
                    evidence={
                        "efMonthsCurrent": ef_months_current,
                        "efMonthsTarget": ef_target,
                        "cashCLP": str(cash_clp),
                        "monthlyExpensesCLP": str(monthly_exp),
                    },
                    ef_target_months=ef_target,
                )
            )

    # Near-term large expenses vs cash
    near_term_total = sum(
        Decimal(str(item.get("amount_clp", 0)))
        for item in large_expenses_clp
        if 0 <= float(item.get("months_away", 9999)) <= 24
    )
    cash_gap_clp = max(_ZERO, near_term_total - cash_clp) if near_term_total > _ZERO else _ZERO
    if cash_gap_clp > _ZERO:
        out.append(
            F.build(
                "liquidity.large_expense_gap",
                severity="medium",
                evidence={
                    "nearTermTotalCLP": str(near_term_total),
                    "cashCLP": str(cash_clp),
                    "gapCLP": str(cash_gap_clp),
                },
            )
        )

    diag = {
        "cash_clp": str(cash_clp),
        "monthly_expenses_clp": str(monthly_exp),
        "emergency_fund_declared_clp": str(ef_declared),
        "ef_months_current": ef_months_current,
        "ef_months_target": policy.emergency_fund_target_months,
        "near_term_large_expenses_clp": str(near_term_total),
        "cash_gap_clp": str(cash_gap_clp),
        "data_available": avg_monthly_expenses_clp > 0,
    }
    return diag, out


def _rebalancing(allocation: dict, policy: PolicyData) -> list[F.Finding]:
    """Emit a rebalancing finding for each bucket that has drifted more than the
    threshold from its target midpoint — but only when the bucket is already
    within its allocation range (outside-range drift is already covered by the
    asset_allocation findings).
    """
    out: list[F.Finding] = []
    current_pct = allocation["current_pct"]
    target_alloc = policy.target_allocation
    threshold = policy.rebalance_threshold_pct

    # Build a set of buckets that already have an allocation finding.
    out_of_range_buckets = {item["bucket"] for item in allocation["out_of_range"]}

    for bucket, target_mid in target_alloc.items():
        if bucket in out_of_range_buckets:
            continue  # allocation finding already covers this
        current = current_pct.get(bucket, 0.0)
        drift = abs(current - target_mid)
        if drift > threshold:
            out.append(
                F.build(
                    "rebalancing.drift_above_threshold",
                    severity="low",
                    evidence={
                        "bucket": bucket,
                        "currentPct": current,
                        "targetMidpointPct": target_mid,
                        "driftPct": round(drift, 2),
                        "thresholdPct": threshold,
                        "direction": "above" if current > target_mid else "below",
                    },
                    bucket_label=BUCKET_LABELS.get(bucket, bucket),
                    drift_pct=round(drift, 1),
                    threshold_pct=threshold,
                )
            )
    return out


def _sector_concentration(
    classes: list[HoldingClass], invested: Decimal, max_sector_pct: float
) -> tuple[dict, list[F.Finding]]:
    """Sector concentration for individual stocks with known sector metadata."""
    sector_values: dict[str, Decimal] = {}
    for hc in classes:
        if hc.sector and hc.is_single_stock:
            sector_values[hc.sector] = sector_values.get(hc.sector, _ZERO) + hc.value_in_base
    sector_pct = {s: _pct(v, invested) for s, v in sector_values.items()}

    findings: list[F.Finding] = []
    for sector, pct_val in sorted(sector_pct.items(), key=lambda kv: -kv[1]):
        if pct_val > max_sector_pct + 0.001:
            findings.append(
                F.build(
                    "sector.over_limit",
                    evidence={"sector": sector, "currentPercent": pct_val, "limitPercent": max_sector_pct},
                    sector=sector,
                    current_pct=pct_val,
                    limit_pct=max_sector_pct,
                )
            )
    return {"by_sector_pct": sector_pct, "max_sector_pct": max_sector_pct}, findings


def _geography_concentration(
    classes: list[HoldingClass], invested: Decimal, max_country_pct: float
) -> tuple[dict, list[F.Finding]]:
    """Country concentration for holdings with known country metadata."""
    country_values: dict[str, Decimal] = {}
    for hc in classes:
        if hc.country:
            country_values[hc.country] = country_values.get(hc.country, _ZERO) + hc.value_in_base
    country_pct = {c: _pct(v, invested) for c, v in country_values.items()}

    findings: list[F.Finding] = []
    for country, pct_val in sorted(country_pct.items(), key=lambda kv: -kv[1]):
        if pct_val > max_country_pct + 0.001:
            findings.append(
                F.build(
                    "geography.over_limit",
                    evidence={"country": country, "currentPercent": pct_val, "limitPercent": max_country_pct},
                    country=country,
                    current_pct=pct_val,
                    limit_pct=max_country_pct,
                )
            )
    return {"by_country_pct": country_pct, "max_country_pct": max_country_pct}, findings


def _currency_concentration(
    by_currency: list[dict], total_in_base: Decimal, max_currency_pct: float
) -> tuple[dict, list[F.Finding]]:
    """Currency concentration from snapshot by_currency (already computed)."""
    currency_pct: dict[str, float] = {}
    findings: list[F.Finding] = []
    for row in by_currency:
        ccy = str(row.get("currency") or "?")
        val = Decimal(str(row.get("total_in_base") or "0"))
        if val <= _ZERO:
            continue
        pct_val = _pct(val, total_in_base)
        currency_pct[ccy] = pct_val
        if pct_val > max_currency_pct + 0.001:
            findings.append(
                F.build(
                    "currency.over_limit",
                    evidence={"currency": ccy, "currentPercent": pct_val, "limitPercent": max_currency_pct},
                    currency=ccy,
                    current_pct=pct_val,
                    limit_pct=max_currency_pct,
                )
            )
    return {"by_currency_pct": currency_pct, "max_currency_pct": max_currency_pct}, findings


def _fees_analysis(
    classes: list[HoldingClass], invested: Decimal
) -> tuple[dict, list[F.Finding]]:
    """Weighted average expense ratio and cost-efficiency findings."""
    # Crypto holdings typically have no expense ratio — exclude from fee coverage check.
    non_crypto = [hc for hc in classes if not hc.is_crypto]
    known = [(hc, hc.expense_ratio) for hc in non_crypto if hc.expense_ratio is not None]
    missing_count = sum(1 for hc in non_crypto if hc.expense_ratio is None)

    findings: list[F.Finding] = []
    weighted_er: float | None = None
    fee_coverage_pct: float | None = None

    if known and invested > _ZERO:
        known_value = sum(hc.value_in_base for hc, _ in known)
        total_non_crypto = sum(hc.value_in_base for hc in non_crypto)
        fee_coverage_pct = round(float(known_value / total_non_crypto * 100), 1) if total_non_crypto > _ZERO else 0.0
        if known_value > _ZERO:
            weighted_er = round(
                sum(float(hc.value_in_base / known_value) * er for hc, er in known),
                4,
            )
        if weighted_er is not None:
            if weighted_er >= C.FEE_HIGH_THRESHOLD:
                findings.append(
                    F.build(
                        "fees.very_high_weighted_expense_ratio",
                        severity="high",
                        evidence={"weightedExpenseRatio": weighted_er, "threshold": C.FEE_HIGH_THRESHOLD},
                        avg_er=weighted_er,
                    )
                )
            elif weighted_er >= C.FEE_WARN_THRESHOLD:
                findings.append(
                    F.build(
                        "fees.high_weighted_expense_ratio",
                        severity="medium",
                        evidence={"weightedExpenseRatio": weighted_er, "threshold": C.FEE_WARN_THRESHOLD},
                        avg_er=weighted_er,
                        threshold=C.FEE_WARN_THRESHOLD,
                    )
                )

    if missing_count > 0:
        findings.append(
            F.build("fees.data_missing", evidence={"count": missing_count}, count=missing_count)
        )

    diag = {
        "weighted_expense_ratio": weighted_er,
        "fee_coverage_pct": fee_coverage_pct,
        "holdings_with_fee_data": len(known),
        "holdings_missing_fee_data": missing_count,
        "fee_warn_threshold": C.FEE_WARN_THRESHOLD,
        "fee_high_threshold": C.FEE_HIGH_THRESHOLD,
    }
    return diag, findings


def run_review(
    profile: ProfileData,
    policy: PolicyData,
    snapshot: dict,
    *,
    avg_monthly_expenses_clp: float = 0.0,
    emergency_fund_clp: float = 0.0,
    large_expenses_clp: list[dict] | None = None,
    metadata_map: dict[str, dict] | None = None,
) -> ReviewResult:
    classes = classify_all(snapshot, metadata_map)
    cash_value = _cash_value(snapshot)
    allocation, invested = _allocation(classes, cash_value, policy)
    concentration = _concentration(classes, invested, profile)

    out: list[F.Finding] = []
    missing: list[str] = []

    # --- suitability findings from policy notes ---
    for note in policy.notes:
        fid = f"suitability.{note.code}"
        if fid in F.CATALOG:
            out.append(F.build(fid, evidence=note.detail))

    # --- allocation gap findings ---
    for item in allocation["out_of_range"]:
        bucket = item["bucket"]
        lo, hi = item["range"]
        cur = item["current_pct"]
        severity = _gap_severity(cur, lo, hi)
        fid = "asset_allocation.above_range" if item["direction"] == "above" else "asset_allocation.below_range"
        # below-range never escalates past medium (it's a softer signal)
        if item["direction"] == "below":
            severity = "medium" if severity == "high" else severity
        out.append(
            F.build(
                fid,
                severity=severity,
                evidence={
                    "bucket": bucket,
                    "currentAllocationPercent": cur,
                    "targetRangePercent": [lo, hi],
                    "riskProfile": policy.risk_profile,
                },
                bucket_label=BUCKET_LABELS.get(bucket, bucket),
            )
        )

    # --- concentration findings ---
    largest = concentration["largest_holding"]
    if largest and largest["pct"] > policy.max_single_holding_pct + 0.001:
        sev = "high" if largest["pct"] > policy.max_single_holding_pct * 2 else "medium"
        out.append(
            F.build(
                "concentration.single_holding",
                severity=sev,
                evidence={
                    "ticker": largest["ticker"],
                    "currentPercent": largest["pct"],
                    "limitPercent": policy.max_single_holding_pct,
                },
                ticker=largest["ticker"],
            )
        )

    stock = concentration["largest_single_stock"]
    if stock and stock["pct"] > policy.max_single_stock_pct + 0.001:
        sev = "high" if stock["pct"] > policy.max_single_stock_pct * 2 else "medium"
        out.append(
            F.build(
                "concentration.single_stock",
                severity=sev,
                evidence={
                    "ticker": stock["ticker"],
                    "currentPercent": stock["pct"],
                    "limitPercent": policy.max_single_stock_pct,
                },
                ticker=stock["ticker"],
            )
        )

    if concentration["crypto_pct"] > policy.max_crypto_pct + 0.001:
        out.append(
            F.build(
                "concentration.crypto",
                severity="high",
                evidence={
                    "currentPercent": concentration["crypto_pct"],
                    "limitPercent": policy.max_crypto_pct,
                    "riskProfile": policy.risk_profile,
                },
                current_pct=concentration["crypto_pct"],
                limit_pct=policy.max_crypto_pct,
            )
        )

    if concentration["employer_stock_pct"] > policy.max_employer_stock_pct + 0.001:
        out.append(
            F.build(
                "concentration.employer_stock",
                severity="high",
                evidence={
                    "ticker": concentration["employer_stock_ticker"],
                    "currentPercent": concentration["employer_stock_pct"],
                    "limitPercent": policy.max_employer_stock_pct,
                },
                ticker=concentration["employer_stock_ticker"],
            )
        )

    # --- coarse risk-mismatch proxy ---
    equities_pct = allocation["current_pct"].get("global_equities", 0.0)
    crypto_pct = allocation["current_pct"].get("crypto", 0.0)
    unknown_pct = allocation["current_pct"].get("unknown", 0.0)
    risky_share = round(equities_pct + crypto_pct, 2)
    eq_ceiling = policy.allocation_ranges["global_equities"][1]
    crypto_ceiling = policy.allocation_ranges["crypto"][1]
    profile_ceiling = round(eq_ceiling + crypto_ceiling, 2)
    risk = {
        "equities_pct": equities_pct,
        "crypto_pct": crypto_pct,
        "single_stock_top_pct": (stock["pct"] if stock else 0.0),
        "unknown_pct": unknown_pct,
        "risky_share_pct": risky_share,
        "profile_ceiling_pct": profile_ceiling,
    }
    if risky_share > profile_ceiling + 5:
        out.append(
            F.build(
                "volatility.risk_above_profile",
                severity="medium",
                evidence={
                    "riskySharePercent": risky_share,
                    "profileCeilingPercent": profile_ceiling,
                    "riskProfile": policy.risk_profile,
                },
            )
        )

    # --- data quality ---
    unknown_count = sum(1 for hc in classes if not hc.asset_class_known)
    missing_price_count = sum(1 for hc in classes if hc.missing_price)
    unknown_value = sum((hc.value_in_base for hc in classes if not hc.asset_class_known), _ZERO)
    unknown_fraction = float(unknown_value / invested) if invested > _ZERO else 0.0
    data_quality_capped = unknown_fraction > C.UNKNOWN_HOLDINGS_WARN_FRACTION

    if unknown_count:
        missing.append(f"{unknown_count} holding(s) missing asset class")
        out.append(
            F.build("data_quality.unknown_asset_class", evidence={"count": unknown_count}, count=unknown_count)
        )
    if missing_price_count:
        missing.append(f"{missing_price_count} holding(s) missing price")
        out.append(
            F.build("data_quality.missing_price", evidence={"count": missing_price_count}, count=missing_price_count)
        )
    if data_quality_capped:
        out.append(
            F.build(
                "data_quality.high_unknown_fraction",
                evidence={"unknownValueFraction": round(unknown_fraction, 4)},
            )
        )

    # --- Stage 2: liquidity / emergency fund ---
    liq_diag, liq_findings = _liquidity(
        cash_clp=cash_value,
        avg_monthly_expenses_clp=avg_monthly_expenses_clp,
        emergency_fund_clp=emergency_fund_clp,
        policy=policy,
        large_expenses_clp=large_expenses_clp or [],
    )
    out.extend(liq_findings)

    # --- Stage 2: rebalancing drift ---
    out.extend(_rebalancing(allocation, policy))

    # --- Stage 2: stress scenarios + drawdown finding ---
    stress_scenarios, drawdown_findings = run_stress(
        allocation_current_pct=allocation["current_pct"],
        portfolio_value_in_base=invested,
        concentration_top1_pct=concentration["top1_pct"],
        by_currency=snapshot.get("by_currency", []),
        risk_profile=policy.risk_profile,
        base_currency=profile.base_currency,
    )
    out.extend(drawdown_findings)

    # --- Stage 4: sector / geography / currency concentration ---
    sector_diag, sector_findings = _sector_concentration(classes, invested, policy.max_sector_pct)
    out.extend(sector_findings)

    geo_diag, geo_findings = _geography_concentration(classes, invested, policy.max_country_pct)
    out.extend(geo_findings)

    total_for_currency = Decimal(str(snapshot.get("total_in_base", "0") or "0"))
    currency_total = total_for_currency if total_for_currency > _ZERO else invested
    currency_diag, currency_findings = _currency_concentration(
        snapshot.get("by_currency", []), currency_total, policy.max_currency_pct
    )
    out.extend(currency_findings)

    # --- Stage 4: fees analysis ---
    fees_diag, fees_findings = _fees_analysis(classes, invested)
    out.extend(fees_findings)

    diagnostics = {
        "allocation": allocation,
        "concentration": concentration,
        "liquidity": liq_diag,
        "stress": stress_scenarios,
        "risk": risk,
        "sector": sector_diag,
        "geography": geo_diag,
        "currency_exposure": currency_diag,
        "fees": fees_diag,
        "data_quality": {
            "unknown_count": unknown_count,
            "missing_price_count": missing_price_count,
            "unknown_value_fraction": round(unknown_fraction, 4),
            "holdings_total": len(classes),
        },
    }
    flags = {"data_quality_capped": data_quality_capped}
    return ReviewResult(diagnostics=diagnostics, findings=out, missing_data=missing, flags=flags)
