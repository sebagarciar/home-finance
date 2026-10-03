"""Spending rules shared by the spending endpoints and the household profile.

One definition of "spending", so the dashboard, the forecast and the
emergency-fund check can never disagree:
- every non-archived transaction counts (txn_type is informational);
- categories flagged `is_income` are excluded (their inflows are income);
- amounts are netted in base CLP, spend-positive.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Category, Transaction


def income_categories(db: Session) -> set[str]:
    """Categories whose positive inflows count as income (and are excluded from
    the spending series). Driven by Category.is_income — not hardcoded names —
    so renaming a category can't silently break the split. Everything else
    stays in spending, even if it nets negative."""
    return set(db.execute(select(Category.name).where(Category.is_income.is_(True))).scalars().all())


def spend_base(t: Transaction) -> Decimal:
    """Spend-positive CLP value: outflows positive, inflows negative."""
    amt = Decimal(str(t.amount)) * Decimal(str(t.fx_rate_to_base))
    return -amt


def monthly_spend(db: Session) -> dict[str, Decimal]:
    """Net spend per "YYYY-MM" month, in base CLP, by the rules above."""
    income = income_categories(db)
    out: dict[str, Decimal] = {}
    rows = db.execute(select(Transaction).where(Transaction.archived.is_(False))).scalars()
    for t in rows:
        if (t.category or "Uncategorized") in income:
            continue
        month = t.date.strftime("%Y-%m")
        out[month] = out.get(month, Decimal("0")) + spend_base(t)
    return out
