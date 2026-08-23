"""Spending aggregates.

Returns net per category in BASE currency (CLP). The UI applies one
base->display conversion at render time using the latest FX rate.

Model:
- The only row filter is `archived=false` (plus optional date/account). Every
  non-archived transaction contributes — `txn_type` is informational and never
  gates aggregation. Internal bank-to-bank moves the user wants hidden are
  archived manually.
- Categories are netted (signed-base sum). A category with a negative net is
  still shown — that surfaces a miscategorized inflow or a date-window edge
  case the user can fix, instead of silently disappearing.
- Categories flagged `is_income` (seeded: Salary) are excluded from the
  spending series; their positive inflows feed `by_month_income` instead.
- Aggregation is deliberately in Python, not SQL GROUP BY: month bucketing
  needs dialect-specific date functions (strftime vs date_trunc), which the
  generic-ORM rule forbids, and the measured cost at household scale is ~12 ms
  for ~1.4k rows. Revisit only if the row count grows by orders of magnitude.
"""
from __future__ import annotations

import datetime as _dt
from datetime import date as date_type
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Category, Transaction
from ._validation import validate_date_range

router = APIRouter(prefix="/spending", tags=["spending"])


def _income_categories(db: Session) -> set[str]:
    """Categories whose positive inflows count as income (and are excluded from
    the spending series). Driven by Category.is_income — not hardcoded names —
    so renaming a category can't silently break the split. Everything else
    stays in spending, even if it nets negative."""
    return set(db.execute(select(Category.name).where(Category.is_income.is_(True))).scalars().all())


def _signed_base(t: Transaction) -> Decimal:
    """Spend-positive CLP value: outflows positive, inflows negative."""
    amt = Decimal(str(t.amount)) * Decimal(str(t.fx_rate_to_base))
    return -amt


def _query(db: Session, start, end, account_id) -> list[Transaction]:
    q = select(Transaction).where(Transaction.archived.is_(False))
    if start is not None:
        q = q.where(Transaction.date >= start)
    if end is not None:
        q = q.where(Transaction.date <= end)
    if account_id is not None:
        q = q.where(Transaction.account_id == account_id)
    return list(db.execute(q).scalars().all())


@router.get("/pace")
def pace(
    through_day: int = Query(..., ge=1, le=31),
    trailing_months: int = Query(6, ge=1, le=24),
    account_id: int | None = Query(None),
    db: Session = Depends(get_session),
):
    """Average spend from day 1 to `through_day` across the last N complete months.

    Unlike `usualSpend × (day/daysInMonth)`, this captures lumpy day-of-month
    payments (rent, subscriptions, etc.) correctly — a housing payment that falls
    on day 1 is counted when through_day >= 1, regardless of monthly totals.
    Current month is excluded so we only sample complete reference months.
    """
    current_month = _dt.date.today().strftime("%Y-%m")
    income_categories = _income_categories(db)

    q = select(Transaction).where(Transaction.archived.is_(False))
    if account_id is not None:
        q = q.where(Transaction.account_id == account_id)
    rows = list(db.execute(q).scalars().all())

    # Partial-month totals: day 1..through_day, past months only.
    partial: dict[str, Decimal] = {}
    for t in rows:
        cat = t.category or "Uncategorized"
        if cat in income_categories:
            continue
        month = t.date.strftime("%Y-%m")
        if month == current_month:
            continue
        if t.date.day > through_day:
            continue
        partial[month] = partial.get(month, Decimal("0")) + _signed_base(t)

    recent = sorted(partial.keys())[-trailing_months:]
    if not recent:
        return {"currency": "CLP", "expected_by_day": None, "months_sampled": 0}

    avg = sum(partial[m] for m in recent) / len(recent)
    return {
        "currency": "CLP",
        "expected_by_day": str(avg),
        "months_sampled": len(recent),
    }


@router.get("/summary")
def summary(
    start: date_type | None = Query(None),
    end: date_type | None = Query(None),
    account_id: int | None = Query(None),
    db: Session = Depends(get_session),
):
    validate_date_range(start, end)
    rows = _query(db, start, end, account_id)
    income_categories = _income_categories(db)

    by_category: dict[str, Decimal] = {}
    by_month: dict[str, Decimal] = {}
    by_account: dict[int, Decimal] = {}
    by_month_category: dict[tuple[str, str], Decimal] = {}
    by_month_income: dict[str, Decimal] = {}

    for t in rows:
        cat = t.category or "Uncategorized"
        month = t.date.strftime("%Y-%m")
        if cat in income_categories:
            native = Decimal(str(t.amount)) * Decimal(str(t.fx_rate_to_base))
            if native > 0:
                by_month_income[month] = by_month_income.get(month, Decimal("0")) + native
            continue
        amt = _signed_base(t)
        by_category[cat] = by_category.get(cat, Decimal("0")) + amt
        by_month[month] = by_month.get(month, Decimal("0")) + amt
        by_account[t.account_id] = by_account.get(t.account_id, Decimal("0")) + amt
        key = (month, cat)
        by_month_category[key] = by_month_category.get(key, Decimal("0")) + amt

    total = sum(by_category.values(), Decimal("0"))

    return {
        "currency": "CLP",
        "total_spent": str(total),
        "by_category": [
            {"category": k, "total": str(v)}
            for k, v in sorted(by_category.items(), key=lambda kv: -kv[1])
        ],
        "by_month": [
            {"month": k, "total": str(v)}
            for k, v in sorted(by_month.items())
        ],
        "by_account": [
            {"account_id": k, "total": str(v)}
            for k, v in sorted(by_account.items())
        ],
        "by_month_category": [
            {"month": m, "category": c, "total": str(v)}
            for (m, c), v in sorted(by_month_category.items())
        ],
        "by_month_income": [
            {"month": k, "total": str(v)}
            for k, v in sorted(by_month_income.items())
        ],
        "count": len(rows),
    }
