"""security metadata table (Stage 4)

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-11 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "security_metadata",
        sa.Column("ticker", sa.String(length=24), primary_key=True),
        sa.Column("asset_class", sa.String(length=32), nullable=True),
        sa.Column("sector", sa.String(length=64), nullable=True),
        sa.Column("region", sa.String(length=32), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("product_type", sa.String(length=32), nullable=True),
        sa.Column("expense_ratio", sa.Float(), nullable=True),
        sa.Column("diversified_fund", sa.Boolean(), nullable=True),
        sa.Column("liquidity_level", sa.String(length=16), nullable=True),
        sa.Column("source", sa.String(length=8), nullable=False, server_default="auto"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("security_metadata")
