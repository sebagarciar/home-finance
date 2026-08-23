"""Portfolio Health Review API.

Single-tenant: one household, no user scoping. The flow:

  PUT  /portfolio-health/profile  -> save questionnaire, derive + persist policy
  GET  /portfolio-health/profile  -> latest investor profile
  GET  /portfolio-health/policy   -> latest derived policy
  POST /portfolio-health/review   -> run the deterministic engine, persist a review
  GET  /portfolio-health/review/latest
  GET  /portfolio-health/reviews  -> history

Guardrail: if no investor profile exists, the review endpoint returns a factual
portfolio summary only (no scores, no suitability) and asks the user to complete
the profile. The AI explanation layer + advanced diagnostics arrive in later
stages.
"""
from __future__ import annotations

from datetime import UTC
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import (
    InvestmentPolicyProfile,
    InvestorProfile,
    PortfolioFinding,
    PortfolioHealthReview,
    SecurityMetadata,
)
from ..services.fx.conversion import to_base_current
from ..services.networth.snapshot import current_networth
from ..services.portfolio_health import AI_PROMPT_VERSION, RULES_ENGINE_VERSION, scoring
from ..services.portfolio_health import classify as classify_mod
from ..services.portfolio_health.engine import BUCKET_LABELS, run_review
from ..services.portfolio_health.enrich import enrich_all, metadata_to_dict
from ..services.portfolio_health.explanation import OllamaExplanationProvider, explain_review
from ..services.portfolio_health.policy import ProfileData, derive_policy

router = APIRouter(prefix="/portfolio-health", tags=["portfolio-health"])


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
Goal = Literal[
    "long_term_growth", "retirement", "capital_preservation", "income",
    "home_purchase", "education", "other",
]
Horizon = Literal["lt_1y", "1_3y", "3_7y", "7_15y", "gt_15y"]
RiskScale = Literal["low", "moderate", "high", "very_high"]
LossReaction = Literal["sell_after_10", "hold_uncomfortable", "invest_more", "unsure"]
IncomeStability = Literal["stable", "variable", "self_employed", "unemployed", "retired"]
Knowledge = Literal["beginner", "intermediate", "advanced"]


class LargeExpense(BaseModel):
    label: str = ""
    amount: Decimal = Decimal("0")
    currency: str = Field(default="CLP", min_length=3, max_length=3)
    months_away: int = 0


class Constraints(BaseModel):
    esg: bool = False
    max_crypto_pct: float | None = None
    max_single_stock_pct: float | None = None
    employer_stock_ticker: str | None = None
    restricted_sectors: list[str] = Field(default_factory=list)
    prefer_low_cost_index: bool = False
    notes: str = ""


class ProfileIn(BaseModel):
    primary_goal: Goal
    time_horizon: Horizon
    risk_tolerance: RiskScale
    risk_capacity: RiskScale
    loss_reaction: LossReaction
    monthly_income: Decimal = Decimal("0")
    monthly_income_currency: str = Field(default="CLP", min_length=3, max_length=3)
    monthly_expenses: Decimal = Decimal("0")
    monthly_expenses_currency: str = Field(default="CLP", min_length=3, max_length=3)
    emergency_fund_amount: Decimal = Decimal("0")
    emergency_fund_currency: str = Field(default="CLP", min_length=3, max_length=3)
    expected_large_expenses: list[LargeExpense] = Field(default_factory=list)
    income_stability: IncomeStability
    investment_knowledge: Knowledge
    tax_residence: str = Field(default="", max_length=2)
    base_currency: str = Field(default="CLP", min_length=3, max_length=3)
    constraints: Constraints = Field(default_factory=Constraints)


# --------------------------------------------------------------------------- #
# Serialization helpers
# --------------------------------------------------------------------------- #
def _profile_to_dict(p: InvestorProfile) -> dict:
    return {
        "id": p.id,
        "primary_goal": p.primary_goal,
        "time_horizon": p.time_horizon,
        "risk_tolerance": p.risk_tolerance,
        "risk_capacity": p.risk_capacity,
        "loss_reaction": p.loss_reaction,
        "monthly_income": str(p.monthly_income),
        "monthly_income_currency": p.monthly_income_currency,
        "monthly_expenses": str(p.monthly_expenses),
        "monthly_expenses_currency": p.monthly_expenses_currency,
        "emergency_fund_amount": str(p.emergency_fund_amount),
        "emergency_fund_currency": p.emergency_fund_currency,
        "expected_large_expenses": p.expected_large_expenses or [],
        "income_stability": p.income_stability,
        "investment_knowledge": p.investment_knowledge,
        "tax_residence": p.tax_residence,
        "base_currency": p.base_currency,
        "constraints": p.constraints or {},
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _policy_to_dict(pp: InvestmentPolicyProfile) -> dict:
    return {
        "id": pp.id,
        "investor_profile_id": pp.investor_profile_id,
        "risk_profile": pp.risk_profile,
        "target_allocation": pp.target_allocation,
        "allocation_ranges": pp.allocation_ranges,
        "max_single_holding_pct": float(pp.max_single_holding_pct),
        "max_sector_pct": float(pp.max_sector_pct),
        "max_country_pct": float(pp.max_country_pct),
        "max_currency_pct": float(pp.max_currency_pct),
        "max_crypto_pct": float(pp.max_crypto_pct),
        "max_employer_stock_pct": float(pp.max_employer_stock_pct),
        "emergency_fund_target_months": float(pp.emergency_fund_target_months),
        "rebalance_threshold_pct": float(pp.rebalance_threshold_pct),
        "version": pp.version,
    }


def _profile_data(p: InvestorProfile) -> ProfileData:
    return ProfileData(
        primary_goal=p.primary_goal,
        time_horizon=p.time_horizon,
        risk_tolerance=p.risk_tolerance,
        risk_capacity=p.risk_capacity,
        loss_reaction=p.loss_reaction,
        income_stability=p.income_stability,
        investment_knowledge=p.investment_knowledge,
        monthly_income=float(p.monthly_income or 0),
        monthly_expenses=float(p.monthly_expenses or 0),
        emergency_fund_amount=float(p.emergency_fund_amount or 0),
        expected_large_expenses=p.expected_large_expenses or [],
        constraints=p.constraints or {},
        base_currency=p.base_currency,
        tax_residence=p.tax_residence,
    )


def _latest_profile(db: Session) -> InvestorProfile | None:
    return db.execute(
        select(InvestorProfile).order_by(InvestorProfile.id.desc()).limit(1)
    ).scalar_one_or_none()


def _latest_policy(db: Session) -> InvestmentPolicyProfile | None:
    return db.execute(
        select(InvestmentPolicyProfile).order_by(InvestmentPolicyProfile.id.desc()).limit(1)
    ).scalar_one_or_none()


def _policy_row_matches(row: InvestmentPolicyProfile, pdata) -> bool:
    """True when the stored policy row equals the freshly-derived policy on every
    persisted field. A mismatch means derive_policy changed since the row was
    written — the review must then re-persist so the policy it displays is the
    one the engine actually ran on.
    """
    return (
        row.risk_profile == pdata.risk_profile
        and row.target_allocation == pdata.target_allocation
        and row.allocation_ranges == pdata.allocation_ranges
        and float(row.max_single_holding_pct) == pdata.max_single_holding_pct
        and float(row.max_sector_pct) == pdata.max_sector_pct
        and float(row.max_country_pct) == pdata.max_country_pct
        and float(row.max_currency_pct) == pdata.max_currency_pct
        and float(row.max_crypto_pct) == pdata.max_crypto_pct
        and float(row.max_employer_stock_pct) == pdata.max_employer_stock_pct
        and float(row.emergency_fund_target_months) == pdata.emergency_fund_target_months
        and float(row.rebalance_threshold_pct) == pdata.rebalance_threshold_pct
    )


def _persist_policy(db: Session, profile: InvestorProfile) -> InvestmentPolicyProfile:
    """Derive the policy deterministically and persist a new versioned row."""
    pdata = derive_policy(_profile_data(profile))
    prev = _latest_policy(db)
    version = (prev.version + 1) if prev else 1
    pp = InvestmentPolicyProfile(
        investor_profile_id=profile.id,
        risk_profile=pdata.risk_profile,
        target_allocation=pdata.target_allocation,
        allocation_ranges=pdata.allocation_ranges,
        max_single_holding_pct=Decimal(str(pdata.max_single_holding_pct)),
        max_sector_pct=Decimal(str(pdata.max_sector_pct)),
        max_country_pct=Decimal(str(pdata.max_country_pct)),
        max_currency_pct=Decimal(str(pdata.max_currency_pct)),
        max_crypto_pct=Decimal(str(pdata.max_crypto_pct)),
        max_employer_stock_pct=Decimal(str(pdata.max_employer_stock_pct)),
        emergency_fund_target_months=Decimal(str(pdata.emergency_fund_target_months)),
        rebalance_threshold_pct=Decimal(str(pdata.rebalance_threshold_pct)),
        version=version,
    )
    db.add(pp)
    db.flush()
    return pp


def _review_to_dict(r: PortfolioHealthReview) -> dict:
    return {
        "id": r.id,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "overall_score": float(r.overall_score),
        "sub_scores": r.sub_scores,
        "diagnostics": r.diagnostics,
        "missing_data": r.missing_data,
        "ai_explanation": r.ai_explanation,
        "rules_engine_version": r.rules_engine_version,
        "ai_prompt_version": r.ai_prompt_version,
        "investor_profile_id": r.investor_profile_id,
        "investment_policy_profile_id": r.investment_policy_profile_id,
        "findings": [
            {
                "id": f.id,
                "category": f.category,
                "severity": f.severity,
                "finding": f.finding,
                "evidence": f.evidence,
                "whyItMatters": f.why_it_matters,
                "educationalGuidance": f.educational_guidance,
                "prohibitedSpecificAdvice": f.prohibited_specific_advice,
            }
            for f in r.findings
        ],
        "profile_incomplete": False,
    }


def _factual_summary(snapshot: dict) -> dict:
    """No-profile fallback: current allocation + concentration, no scores."""
    classes = classify_mod.classify_all(snapshot)
    # cash sleeve
    cash = Decimal("0")
    for row in snapshot.get("by_asset_class", []):
        if row.get("asset_class") == "cash":
            cash = Decimal(str(row.get("total_in_base") or "0"))
    bucket_value: dict[str, Decimal] = {"cash": cash}
    for hc in classes:
        bucket_value[hc.policy_bucket] = bucket_value.get(hc.policy_bucket, Decimal("0")) + hc.value_in_base
    invested = sum(bucket_value.values(), Decimal("0"))

    def pct(v: Decimal) -> float:
        return round(float(v / invested * 100), 2) if invested > 0 else 0.0

    ranked = sorted(classes, key=lambda h: (-h.value_in_base, h.ticker))
    return {
        "profile_incomplete": True,
        "factual_summary": {
            "portfolio_value_in_base": str(invested),
            "allocation_pct": {b: pct(v) for b, v in bucket_value.items()},
            "bucket_labels": BUCKET_LABELS,
            "top_holdings": [
                {"ticker": h.ticker, "pct": pct(h.value_in_base), "value_in_base": str(h.value_in_base),
                 "bucket": h.policy_bucket}
                for h in ranked[:5]
            ],
            "by_currency": snapshot.get("by_currency", []),
        },
    }


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@router.get("/profile")
def get_profile(db: Session = Depends(get_session)):
    p = _latest_profile(db)
    if p is None:
        return {"profile": None}
    return {"profile": _profile_to_dict(p)}


@router.put("/profile")
def put_profile(payload: ProfileIn, db: Session = Depends(get_session)):
    p = InvestorProfile(
        primary_goal=payload.primary_goal,
        time_horizon=payload.time_horizon,
        risk_tolerance=payload.risk_tolerance,
        risk_capacity=payload.risk_capacity,
        loss_reaction=payload.loss_reaction,
        monthly_income=payload.monthly_income,
        monthly_income_currency=payload.monthly_income_currency.upper(),
        monthly_expenses=payload.monthly_expenses,
        monthly_expenses_currency=payload.monthly_expenses_currency.upper(),
        emergency_fund_amount=payload.emergency_fund_amount,
        emergency_fund_currency=payload.emergency_fund_currency.upper(),
        expected_large_expenses=[e.model_dump(mode="json") for e in payload.expected_large_expenses],
        income_stability=payload.income_stability,
        investment_knowledge=payload.investment_knowledge,
        tax_residence=(payload.tax_residence or "").upper(),
        base_currency=payload.base_currency.upper(),
        constraints=payload.constraints.model_dump(mode="json"),
    )
    db.add(p)
    db.flush()
    pp = _persist_policy(db, p)
    db.commit()
    db.refresh(p)
    db.refresh(pp)
    return {"profile": _profile_to_dict(p), "policy": _policy_to_dict(pp)}


@router.get("/policy")
def get_policy(db: Session = Depends(get_session)):
    pp = _latest_policy(db)
    if pp is None:
        return {"policy": None}
    return {"policy": _policy_to_dict(pp)}


@router.post("/review")
def create_review(db: Session = Depends(get_session)):
    snapshot = current_networth(db)
    profile = _latest_profile(db)
    if profile is None:
        # Guardrail: no profile -> factual summary only, no suitability review.
        return _factual_summary(snapshot)

    pdata = derive_policy(_profile_data(profile))

    policy_row = _latest_policy(db)
    if (
        policy_row is None
        or policy_row.investor_profile_id != profile.id
        or not _policy_row_matches(policy_row, pdata)
    ):
        # No row, stale profile, or derive_policy changed since the row was
        # written — persist a new version so engine input == displayed policy.
        policy_row = _persist_policy(db, profile)

    # Convert profile spending/liquidity amounts to base CLP so the engine stays
    # pure. FX failures degrade to 0 (the engine then skips the affected
    # diagnostics) but are reported in missing_data, never swallowed silently.
    fx_failures: list[str] = []

    def _to_clp(amount: Decimal | None, currency: str | None, label: str) -> float:
        if not amount or amount <= Decimal("0"):
            return 0.0
        ccy = (currency or "CLP").upper()
        try:
            return float(to_base_current(db, amount, ccy))
        except Exception:  # noqa: BLE001 — FX unavailable; graceful degrade
            fx_failures.append(f"{label}: {ccy}->CLP conversion failed; treated as unavailable")
            return 0.0

    monthly_expenses_clp = _to_clp(
        profile.monthly_expenses, profile.monthly_expenses_currency, "monthly_expenses"
    )
    emergency_fund_clp = _to_clp(
        profile.emergency_fund_amount, profile.emergency_fund_currency, "emergency_fund"
    )

    large_expenses_clp: list[dict] = []
    for item in profile.expected_large_expenses or []:
        label = str(item.get("label", "")) or "large_expense"
        try:
            amt = Decimal(str(item.get("amount", 0)))
            ccy = str(item.get("currency", "CLP")).upper()
            amt_clp = _to_clp(amt, ccy, f"large_expense '{label}'")
            large_expenses_clp.append({
                "label": item.get("label", ""),
                "amount_clp": amt_clp,
                "months_away": float(item.get("months_away", 0)),
            })
        except Exception:  # noqa: BLE001
            fx_failures.append(f"large_expense '{label}': unreadable amount; skipped")

    # --- Stage 4: enrich holding metadata and pass to engine ---
    tickers = [h["ticker"] for h in snapshot.get("holdings", []) if h.get("ticker")]
    enriched_map = enrich_all(tickers, db)
    # Serialise ORM rows to plain dicts so the engine stays pure.
    metadata_map = {ticker: metadata_to_dict(row) for ticker, row in enriched_map.items()}

    result = run_review(
        _profile_data(profile),
        pdata,
        snapshot,
        avg_monthly_expenses_clp=monthly_expenses_clp,
        emergency_fund_clp=emergency_fund_clp,
        large_expenses_clp=large_expenses_clp,
        metadata_map=metadata_map,
    )
    sc = scoring.score(result.findings, result.flags)
    status = scoring.overall_status(sc["overall"], result.findings)

    diagnostics = {
        **result.diagnostics,
        "score_explanation": sc["score_explanation"],
        "weights": sc["weights"],
        "status": status,
        "policy": _policy_to_dict(policy_row),
        "flags": result.flags,
    }

    review = PortfolioHealthReview(
        investor_profile_id=profile.id,
        investment_policy_profile_id=policy_row.id,
        portfolio_snapshot=snapshot,
        overall_score=Decimal(str(sc["overall"])),
        sub_scores=sc["sub_scores"],
        diagnostics=diagnostics,
        missing_data=result.missing_data + fx_failures,
        ai_explanation=None,
        rules_engine_version=RULES_ENGINE_VERSION,
        ai_prompt_version=None,
    )
    for f in result.findings:
        review.findings.append(
            PortfolioFinding(
                category=f.category,
                severity=f.severity,
                finding=f.finding,
                evidence=f.evidence,
                why_it_matters=f.why_it_matters,
                educational_guidance=f.educational_guidance,
                prohibited_specific_advice=f.prohibited_specific_advice,
            )
        )
    db.add(review)
    db.flush()  # get review.id + findings.id before explanation

    # Build the structured dict that explain_review receives (findings-only,
    # no raw holdings — the provider prompt prevents open-ended evaluation).
    review_for_ai = {
        "primary_goal": profile.primary_goal,
        "time_horizon": profile.time_horizon,
        "risk_profile": diagnostics.get("policy", {}).get("risk_profile"),
        "overall_score": float(sc["overall"]),
        "sub_scores": sc["sub_scores"],
        "status": status,
        "findings": [
            {
                "id": f.fid,
                "category": f.category,
                "severity": f.severity,
                "finding": f.finding,
                "whyItMatters": f.why_it_matters,
            }
            for f in result.findings
        ],
        "missing_data": result.missing_data + fx_failures,
    }
    explanation, prompt_ver = explain_review(review_for_ai, OllamaExplanationProvider())
    review.ai_explanation = explanation
    review.ai_prompt_version = prompt_ver or AI_PROMPT_VERSION

    db.commit()
    db.refresh(review)
    return _review_to_dict(review)


@router.get("/review/latest")
def latest_review(db: Session = Depends(get_session)):
    r = db.execute(
        select(PortfolioHealthReview).order_by(PortfolioHealthReview.id.desc()).limit(1)
    ).scalar_one_or_none()
    if r is None:
        return {"review": None}
    return {"review": _review_to_dict(r)}


@router.get("/reviews")
def list_reviews(db: Session = Depends(get_session)):
    rows = db.execute(
        select(PortfolioHealthReview).order_by(PortfolioHealthReview.id.desc())
    ).scalars().all()
    return [
        {
            "id": r.id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "overall_score": float(r.overall_score),
            "status": (r.diagnostics or {}).get("status"),
            "rules_engine_version": r.rules_engine_version,
            "ai_prompt_version": r.ai_prompt_version,
        }
        for r in rows
    ]


# --------------------------------------------------------------------------- #
# Metadata endpoints (Stage 4)
# --------------------------------------------------------------------------- #

class MetadataIn(BaseModel):
    asset_class: str | None = None
    sector: str | None = None
    region: str | None = None
    country: str | None = Field(default=None, max_length=2)
    currency: str | None = Field(default=None, max_length=3)
    product_type: str | None = None
    expense_ratio: float | None = None
    diversified_fund: bool | None = None
    liquidity_level: str | None = None


@router.get("/metadata")
def list_metadata(db: Session = Depends(get_session)):
    """Return all cached security metadata rows."""
    rows = db.execute(select(SecurityMetadata).order_by(SecurityMetadata.ticker)).scalars().all()
    return [metadata_to_dict(r) for r in rows]


@router.get("/metadata/{ticker}")
def get_metadata(ticker: str, db: Session = Depends(get_session)):
    """Return metadata for one ticker, or 404 if not cached."""
    row = db.get(SecurityMetadata, ticker.upper())
    if row is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"No metadata cached for {ticker.upper()}")
    return metadata_to_dict(row)


@router.put("/metadata/{ticker}")
def put_metadata(ticker: str, payload: MetadataIn, db: Session = Depends(get_session)):
    """Upsert a manual metadata override for a ticker.

    All fields are optional; only sent fields are updated. The row is marked
    source='manual' so auto-enrichment never overwrites it.
    """
    from datetime import datetime
    t = ticker.strip().upper()
    row = db.get(SecurityMetadata, t)
    if row is None:
        row = SecurityMetadata(ticker=t, source="manual")
        db.add(row)

    data = payload.model_dump(exclude_none=True)
    for k, v in data.items():
        setattr(row, k, v)
    row.source = "manual"
    row.updated_at = datetime.now(tz=UTC)

    db.commit()
    db.refresh(row)
    return metadata_to_dict(row)


@router.delete("/metadata/{ticker}")
def delete_metadata(ticker: str, db: Session = Depends(get_session)):
    """Remove a metadata row, resetting the ticker to 'not enriched'."""
    row = db.get(SecurityMetadata, ticker.upper())
    if row is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"No metadata for {ticker.upper()}")
    db.delete(row)
    db.commit()
    return {"deleted": ticker.upper()}


@router.post("/enrich")
def trigger_enrich(db: Session = Depends(get_session)):
    """Trigger yfinance enrichment for all current holdings.

    Idempotent — already-fresh rows (< 7 days old, manual) are skipped.
    Returns the updated metadata map.
    """
    snapshot = current_networth(db)
    tickers = [h["ticker"] for h in snapshot.get("holdings", []) if h.get("ticker")]
    enriched = enrich_all(tickers, db)
    db.commit()
    return [metadata_to_dict(r) for r in enriched.values()]
