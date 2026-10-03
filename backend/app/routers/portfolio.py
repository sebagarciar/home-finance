"""Portfolio checks.

- GET /portfolio/risk-profile — latest risk answers (or null).
- PUT /portfolio/risk-profile — save a new version of the answers.
- GET /portfolio/checks      — the target policy derived from the answers (and
  near-term planned expenses), and today's mix against it.

Everything is computed live and deterministically; nothing about the check
is persisted. Educational, not advice.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Assumptions, RiskProfile
from ..services.household import upcoming_expenses
from ..services.networth import current_networth
from ..services.portfolio import Policy, RiskAnswers, derive_policy, mix_check

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

Horizon = Literal["lt_1y", "1_3y", "3_7y", "7_15y", "gt_15y"]
RiskScale = Literal["low", "moderate", "high", "very_high"]
LossReaction = Literal["sell_after_10", "hold_uncomfortable", "invest_more", "unsure"]


class RiskProfileIn(BaseModel):
    time_horizon: Horizon
    risk_tolerance: RiskScale
    risk_capacity: RiskScale
    loss_reaction: LossReaction


def _latest(db: Session) -> RiskProfile | None:
    return db.execute(select(RiskProfile).order_by(RiskProfile.id.desc()).limit(1)).scalar_one_or_none()


def _profile_out(p: RiskProfile) -> dict:
    return {
        "id": p.id,
        "time_horizon": p.time_horizon,
        "risk_tolerance": p.risk_tolerance,
        "risk_capacity": p.risk_capacity,
        "loss_reaction": p.loss_reaction,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _policy(db: Session, p: RiskProfile) -> Policy:
    household = db.execute(select(Assumptions).limit(1)).scalar_one_or_none()
    planned = upcoming_expenses(db, household) if household is not None else []
    return derive_policy(RiskAnswers(
        time_horizon=p.time_horizon,
        risk_tolerance=p.risk_tolerance,
        risk_capacity=p.risk_capacity,
        loss_reaction=p.loss_reaction,
        planned_expenses=[{"amount": e["amount_clp"], "months_away": e["months_away"]} for e in planned],
    ))


def _policy_out(policy: Policy) -> dict:
    return {
        "risk_profile": policy.risk_profile,
        "target_allocation": policy.target_allocation,
        "allocation_ranges": {k: list(v) for k, v in policy.allocation_ranges.items()},
        "notes": [{"code": n.code, **n.detail} for n in policy.notes],
    }


@router.get("/risk-profile")
def get_risk_profile(db: Session = Depends(get_session)):
    p = _latest(db)
    return {"profile": _profile_out(p) if p else None}


@router.put("/risk-profile")
def put_risk_profile(payload: RiskProfileIn, db: Session = Depends(get_session)):
    p = RiskProfile(**payload.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return {"profile": _profile_out(p), "policy": _policy_out(_policy(db, p))}


@router.get("/checks")
def get_checks(db: Session = Depends(get_session)):
    p = _latest(db)
    if p is None:
        return {"profile": None, "policy": None, "mix": None}
    policy = _policy(db, p)
    mix = mix_check(current_networth(db), policy)
    return {
        "profile": _profile_out(p),
        "policy": _policy_out(policy),
        "mix": {
            "currency": "CLP",
            "total": str(mix.total_base),
            "out_of_range": mix.out_of_range,
            "drifting": mix.drifting,
            "buckets": [
                {
                    "bucket": b.bucket,
                    "label": b.label,
                    "value": str(b.value_base),
                    "current_pct": b.current_pct,
                    "target_pct": b.target_pct,
                    "min_pct": b.min_pct,
                    "max_pct": b.max_pct,
                    "status": b.status,
                    "drift_pp": b.drift_pp,
                    "drifting": b.drifting,
                }
                for b in mix.buckets
            ],
        },
    }
