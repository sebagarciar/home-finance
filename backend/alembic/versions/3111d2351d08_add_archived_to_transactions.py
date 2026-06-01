"""add archived to transactions

Revision ID: 3111d2351d08
Revises: f1fa72cf5c82
Create Date: 2026-05-28 00:48:47.757966

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3111d2351d08'
down_revision: Union[str, None] = 'f1fa72cf5c82'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default '0' so existing rows backfill to False without violating NOT NULL.
    op.add_column(
        "transactions",
        sa.Column("archived", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("transactions", "archived")
