"""household profile: one source for income, spending and planned expenses

- assumptions.spending_baseline_* → spending_override_* (nullable; NULL = use
  the average derived from statements). A stored 0 meant "not set" → NULL;
  any real figure is kept as an override.
- assumptions.asset_allocation dropped: the forecast uses the current mix.
- assumptions.planned_expenses added, seeded from the latest investor
  profile's expected_large_expenses (months_away → a "YYYY-MM" month counted
  from when that profile was saved).
- investor_profiles money columns dropped (derived or in the household profile).

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-10-03 00:00:00.000000

"""
from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa

from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: str | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROFILE_MONEY = (
    ("monthly_income", sa.Numeric(18, 4), "0"),
    ("monthly_income_currency", sa.String(3), "CLP"),
    ("monthly_expenses", sa.Numeric(18, 4), "0"),
    ("monthly_expenses_currency", sa.String(3), "CLP"),
    ("emergency_fund_amount", sa.Numeric(18, 4), "0"),
    ("emergency_fund_currency", sa.String(3), "CLP"),
)

assumptions = sa.table(
    "assumptions",
    sa.column("id", sa.Integer),
    sa.column("spending_override_monthly", sa.Numeric(18, 4)),
    sa.column("spending_baseline_monthly", sa.Numeric(18, 4)),
    sa.column("planned_expenses", sa.JSON),
)
profiles = sa.table(
    "investor_profiles",
    sa.column("id", sa.Integer),
    sa.column("created_at", sa.DateTime),
    sa.column("expected_large_expenses", sa.JSON),
)


def _add_months(d: datetime, n: int) -> str:
    total = d.year * 12 + (d.month - 1) + n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def _planned_from_latest_profile(bind) -> list[dict]:
    row = bind.execute(
        sa.select(profiles.c.created_at, profiles.c.expected_large_expenses)
        .order_by(profiles.c.id.desc())
        .limit(1)
    ).first()
    if row is None:
        return []
    created, items = row
    if isinstance(items, str):
        items = json.loads(items)
    if isinstance(created, str):
        created = datetime.fromisoformat(created)
    created = created or datetime.now()
    out = []
    for it in items or []:
        try:
            amount = float(it.get("amount", 0))
            months = int(float(it.get("months_away", 0)))
        except (TypeError, ValueError):
            continue
        if amount <= 0:
            continue
        out.append({
            "label": str(it.get("label", ""))[:80],
            "amount": str(amount),
            "currency": str(it.get("currency", "CLP")).upper()[:3],
            "month": _add_months(created, months),
        })
    return out


def upgrade() -> None:
    bind = op.get_bind()
    planned = _planned_from_latest_profile(bind)

    with op.batch_alter_table("assumptions") as b:
        b.alter_column(
            "spending_baseline_monthly",
            new_column_name="spending_override_monthly",
            existing_type=sa.Numeric(18, 4),
            nullable=True,
        )
        b.alter_column(
            "spending_baseline_currency",
            new_column_name="spending_override_currency",
            existing_type=sa.String(3),
        )
        b.drop_column("asset_allocation")
        b.add_column(sa.Column("planned_expenses", sa.JSON(), nullable=False, server_default="[]"))

    bind.execute(
        assumptions.update()
        .where(assumptions.c.spending_override_monthly == 0)
        .values(spending_override_monthly=None)
    )
    if planned:
        bind.execute(assumptions.update().values(planned_expenses=planned))

    with op.batch_alter_table("investor_profiles") as b:
        for name, _, _ in _PROFILE_MONEY:
            b.drop_column(name)
        b.drop_column("expected_large_expenses")


def downgrade() -> None:
    with op.batch_alter_table("investor_profiles") as b:
        for name, type_, default in _PROFILE_MONEY:
            b.add_column(sa.Column(name, type_, nullable=False, server_default=default))
        b.add_column(
            sa.Column("expected_large_expenses", sa.JSON(), nullable=False, server_default="[]")
        )

    bind = op.get_bind()
    bind.execute(
        assumptions.update()
        .where(assumptions.c.spending_override_monthly.is_(None))
        .values(spending_override_monthly=0)
    )
    with op.batch_alter_table("assumptions") as b:
        b.drop_column("planned_expenses")
        b.add_column(
            sa.Column(
                "asset_allocation",
                sa.JSON(),
                nullable=False,
                server_default='{"equity": 0.7, "bonds": 0.2, "cash": 0.1}',
            )
        )
        b.alter_column(
            "spending_override_currency",
            new_column_name="spending_baseline_currency",
            existing_type=sa.String(3),
        )
        b.alter_column(
            "spending_override_monthly",
            new_column_name="spending_baseline_monthly",
            existing_type=sa.Numeric(18, 4),
            nullable=False,
        )
