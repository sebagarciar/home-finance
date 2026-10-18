"""email sync status

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-10-18 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: str | None = "d0e1f2a3b4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_sync_status",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_ok", sa.Boolean()),
        sa.Column("last_error", sa.String(length=512)),
        sa.Column("last_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_imported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_recategorized_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("email_sync_status")
