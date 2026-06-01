"""email ingest: transactions.source

Revision ID: f6a7b8c9d0e1
Revises: 87f228100fee
Create Date: 2026-05-31 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "87f228100fee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column(
            "source",
            sa.String(length=16),
            nullable=False,
            server_default="statement",
        ),
    )


def downgrade() -> None:
    op.drop_column("transactions", "source")
