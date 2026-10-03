"""Household figures derived from data instead of typed in.

The household profile (the single `assumptions` row) stores only what the data
can't tell: income, planned big expenses, an optional spending override, and
forecast settings. Everything else is computed here, so the forecast, the
Health Review and the Overview read the same numbers:

- monthly spend: average of the last ≤6 *complete* months (the running month
  is partial and would drag the average down), by the shared spending rules;
- liquid cash: bank cash plus cash-class holdings (debt excluded);
- current mix: today's assets grouped into the forecast's classes.

All money is base CLP. FX goes only through `to_base_current`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy.orm import Session

from ...models import Assumptions
from ..fx.conversion import to_base_current
from ..spending import monthly_spend

SPEND_WINDOW_MONTHS = 6

# Net-worth asset classes → the forecast's return classes. Anything volatile
# that isn't a bond is modelled as equity; unknown classes too, so a new class
# never silently earns the cash rate.
FORECAST_CLASS: dict[str, str] = {
    "cash": "cash",
    "bond": "bonds",
    "bonds": "bonds",
    "equity": "equity",
    "crypto": "equity",
    "other": "equity",
}
FORECAST_CLASSES = ("equity", "bonds", "cash")

SpendSource = Literal["override", "derived", "none"]


@dataclass(frozen=True)
class DerivedSpend:
    monthly_clp: Decimal | None
    months: list[str]  # the "YYYY-MM" months averaged, oldest first


@dataclass(frozen=True)
class EffectiveSpend:
    monthly_clp: Decimal
    source: SpendSource
    derived: DerivedSpend


def derived_monthly_spend(db: Session, today: date | None = None) -> DerivedSpend:
    today = today or date.today()
    running = today.strftime("%Y-%m")
    totals = monthly_spend(db)
    months = sorted(m for m in totals if m < running)[-SPEND_WINDOW_MONTHS:]
    if not months:
        return DerivedSpend(None, [])
    avg = sum((totals[m] for m in months), Decimal("0")) / len(months)
    return DerivedSpend(avg, months)


def effective_monthly_spend(db: Session, a: Assumptions, today: date | None = None) -> EffectiveSpend:
    """The override when set, else the derived average, else zero."""
    derived = derived_monthly_spend(db, today)
    if a.spending_override_monthly is not None:
        value = to_base_current(db, Decimal(str(a.spending_override_monthly)), a.spending_override_currency)
        return EffectiveSpend(value, "override", derived)
    if derived.monthly_clp is not None:
        return EffectiveSpend(derived.monthly_clp, "derived", derived)
    return EffectiveSpend(Decimal("0"), "none", derived)


def monthly_income_clp(db: Session, a: Assumptions) -> Decimal:
    return to_base_current(db, Decimal(str(a.income_user1)), a.income_user1_currency) + to_base_current(
        db, Decimal(str(a.income_user2)), a.income_user2_currency
    )


def current_allocation(networth: dict) -> dict[str, float]:
    """Weights per forecast class from `current_networth()` output.

    Debt is excluded: it reduces the starting net worth, it doesn't earn a
    return. With no positive assets, everything is cash.
    """
    sums = dict.fromkeys(FORECAST_CLASSES, Decimal("0"))
    for row in networth.get("by_asset_class", []):
        cls = row["asset_class"]
        if cls == "debt":
            continue
        value = Decimal(row["total_in_base"])
        if value > 0:
            sums[FORECAST_CLASS.get(cls, "equity")] += value
    total = sum(sums.values(), Decimal("0"))
    if total <= 0:
        return {"equity": 0.0, "bonds": 0.0, "cash": 1.0}
    return {k: float(v / total) for k, v in sums.items()}


def liquid_cash_clp(networth: dict) -> Decimal:
    """Bank cash plus cash-class holdings — what an emergency fund can draw on."""
    for row in networth.get("by_asset_class", []):
        if row["asset_class"] == "cash":
            return max(Decimal(row["total_in_base"]), Decimal("0"))
    return Decimal("0")


def month_offset(month: str, today: date | None = None) -> int:
    """Months from the running month to "YYYY-MM": 0 = this month, negative = past."""
    today = today or date.today()
    y, m = (int(p) for p in month.split("-"))
    return (y * 12 + m) - (today.year * 12 + today.month)


def upcoming_expenses(
    db: Session, a: Assumptions, today: date | None = None
) -> list[dict[str, Any]]:
    """Planned expenses that haven't passed, in base CLP, with `months_away`."""
    out: list[dict[str, Any]] = []
    for item in a.planned_expenses or []:
        away = month_offset(item["month"], today)
        if away < 0:
            continue
        out.append({
            "label": item.get("label", ""),
            "month": item["month"],
            "months_away": away,
            "amount_clp": to_base_current(db, Decimal(str(item["amount"])), item["currency"]),
        })
    return out
