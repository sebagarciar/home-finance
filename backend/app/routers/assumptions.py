"""Assumptions CRUD (Phase 7).

A single-row table holds every input the forecast engine reads. This router
exposes it for the Assumptions page:

- GET  /assumptions — the current row.
- PUT  /assumptions — partial update (only the provided fields change).

The forecast page reads these values; changing them and re-running shifts the
bands. Money fields are serialized as strings (like the rest of the API); rates,
ρ, horizon and the per-asset-class dicts are plain JSON numbers.
"""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Assumptions

router = APIRouter(prefix="/assumptions", tags=["assumptions"])


def _opt_currency() -> str | None:
    return Field(default=None, min_length=3, max_length=3)


class AssumptionsOut(BaseModel):
    income_user1: str
    income_user1_currency: str
    income_user2: str
    income_user2_currency: str
    income_growth_rate: float
    income_noise_sigma: float
    spending_baseline_monthly: str
    spending_baseline_currency: str
    spending_growth_rate: float
    return_assumptions: dict[str, float]
    asset_allocation: dict[str, float]
    horizon_years: int
    correlation_rho: float
    inflation_rate: float
    fx_drift_annual: float

    @classmethod
    def from_model(cls, a: Assumptions) -> AssumptionsOut:
        return cls(
            income_user1=str(a.income_user1),
            income_user1_currency=a.income_user1_currency,
            income_user2=str(a.income_user2),
            income_user2_currency=a.income_user2_currency,
            income_growth_rate=float(a.income_growth_rate),
            income_noise_sigma=float(a.income_noise_sigma),
            spending_baseline_monthly=str(a.spending_baseline_monthly),
            spending_baseline_currency=a.spending_baseline_currency,
            spending_growth_rate=float(a.spending_growth_rate),
            return_assumptions={k: float(v) for k, v in a.return_assumptions.items()},
            asset_allocation={k: float(v) for k, v in a.asset_allocation.items()},
            horizon_years=a.horizon_years,
            correlation_rho=float(a.correlation_rho),
            inflation_rate=float(a.inflation_rate),
            fx_drift_annual=float(a.fx_drift_annual),
        )


class AssumptionsUpdate(BaseModel):
    """All fields optional — only what's sent is updated."""

    income_user1: Decimal | None = Field(default=None, ge=0)
    income_user1_currency: str | None = _opt_currency()
    income_user2: Decimal | None = Field(default=None, ge=0)
    income_user2_currency: str | None = _opt_currency()
    income_growth_rate: float | None = Field(default=None, ge=-0.5, le=1.0)
    income_noise_sigma: float | None = Field(default=None, ge=0, le=2.0)
    spending_baseline_monthly: Decimal | None = Field(default=None, ge=0)
    spending_baseline_currency: str | None = _opt_currency()
    spending_growth_rate: float | None = Field(default=None, ge=-0.5, le=1.0)
    return_assumptions: dict[str, float] | None = None
    asset_allocation: dict[str, float] | None = None
    horizon_years: int | None = Field(default=None, ge=1, le=60)
    correlation_rho: float | None = Field(default=None, ge=0, le=1)
    inflation_rate: float | None = Field(default=None, ge=-0.1, le=0.5)
    fx_drift_annual: float | None = Field(default=None, ge=-0.2, le=0.2)


def _get_row(db: Session) -> Assumptions:
    a = db.execute(select(Assumptions).limit(1)).scalar_one_or_none()
    if a is None:
        raise HTTPException(status_code=404, detail="No assumptions row — seed the database.")
    return a


@router.get("", response_model=AssumptionsOut)
def get_assumptions(db: Session = Depends(get_session)):
    return AssumptionsOut.from_model(_get_row(db))


@router.put("", response_model=AssumptionsOut)
def update_assumptions(payload: AssumptionsUpdate, db: Session = Depends(get_session)):
    a = _get_row(db)
    data = payload.model_dump(exclude_unset=True)

    # Currencies upper-cased for consistency with the rest of the system.
    for key in ("income_user1_currency", "income_user2_currency", "spending_baseline_currency"):
        if key in data and data[key] is not None:
            data[key] = data[key].upper()

    # The two per-asset-class dicts must agree on keys, and allocation must be
    # non-negative. The engine renormalizes weights, but reject empty/garbage.
    for key in ("return_assumptions", "asset_allocation"):
        if key in data and data[key] is not None:
            if not data[key]:
                raise HTTPException(status_code=422, detail=f"{key} cannot be empty")
            if any(v < 0 for v in data[key].values()):
                raise HTTPException(status_code=422, detail=f"{key} values must be non-negative")

    for field, value in data.items():
        setattr(a, field, value)
    db.commit()
    db.refresh(a)
    return AssumptionsOut.from_model(a)
