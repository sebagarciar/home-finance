"""Household profile (the single `assumptions` row).

The profile stores only what the data can't tell: income, an optional
spending override, planned big expenses, and forecast settings.

- GET  /assumptions         — the stored row.
- PUT  /assumptions         — partial update (only the provided fields change).
  Send `spending_override_monthly: null` to go back to the derived average.
- GET  /assumptions/derived — what the data says: average monthly spend (and the
  months it covers), liquid cash, the current asset mix. Separate because it
  prices holdings, so the form doesn't wait on it.

Money fields are serialized as strings (like the rest of the API); rates, ρ and
horizon are plain JSON numbers.
"""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Assumptions
from ..services.household import (
    current_allocation,
    effective_monthly_spend,
    liquid_cash_clp,
)
from ..services.networth import current_networth

router = APIRouter(prefix="/assumptions", tags=["assumptions"])


def _opt_currency() -> str | None:
    return Field(default=None, min_length=3, max_length=3)


class PlannedExpense(BaseModel):
    label: str = Field(default="", max_length=80)
    amount: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM")


class AssumptionsOut(BaseModel):
    income_user1: str
    income_user1_currency: str
    income_user2: str
    income_user2_currency: str
    income_growth_rate: float
    income_noise_sigma: float
    spending_override_monthly: str | None
    spending_override_currency: str
    spending_growth_rate: float
    planned_expenses: list[PlannedExpense]
    return_assumptions: dict[str, float]
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
            spending_override_monthly=(
                str(a.spending_override_monthly) if a.spending_override_monthly is not None else None
            ),
            spending_override_currency=a.spending_override_currency,
            spending_growth_rate=float(a.spending_growth_rate),
            planned_expenses=[PlannedExpense(**e) for e in a.planned_expenses or []],
            return_assumptions={k: float(v) for k, v in a.return_assumptions.items()},
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
    spending_override_monthly: Decimal | None = Field(default=None, ge=0)
    spending_override_currency: str | None = _opt_currency()
    spending_growth_rate: float | None = Field(default=None, ge=-0.5, le=1.0)
    planned_expenses: list[PlannedExpense] | None = None
    return_assumptions: dict[str, float] | None = None
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
    for key in ("income_user1_currency", "income_user2_currency", "spending_override_currency"):
        if key in data and data[key] is not None:
            data[key] = data[key].upper()
    # The override is the only nullable field: an explicit null clears it.
    for key, value in list(data.items()):
        if value is None and key != "spending_override_monthly":
            del data[key]

    rets = data.get("return_assumptions")
    if rets is not None:
        if not rets:
            raise HTTPException(status_code=422, detail="return_assumptions cannot be empty")

    if "planned_expenses" in data:
        data["planned_expenses"] = [
            {
                "label": e["label"].strip(),
                "amount": str(e["amount"]),
                "currency": e["currency"].upper(),
                "month": e["month"],
            }
            for e in sorted(data["planned_expenses"], key=lambda e: e["month"])
        ]

    for field, value in data.items():
        setattr(a, field, value)
    db.commit()
    db.refresh(a)
    return AssumptionsOut.from_model(a)


@router.get("/derived")
def get_derived(db: Session = Depends(get_session)):
    a = _get_row(db)
    spend = effective_monthly_spend(db, a)
    networth = current_networth(db)
    return {
        "currency": "CLP",
        "spending": {
            "derived_monthly": (
                str(spend.derived.monthly_clp) if spend.derived.monthly_clp is not None else None
            ),
            "months": spend.derived.months,
            "effective_monthly": str(spend.monthly_clp),
            "source": spend.source,
        },
        "liquid_cash": str(liquid_cash_clp(networth)),
        "allocation": current_allocation(networth),
    }
