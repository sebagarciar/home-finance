"""account current_balance

Revision ID: 87f228100fee
Revises: 3111d2351d08
Create Date: 2026-05-28 20:56:32.384602

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '87f228100fee'
down_revision: Union[str, None] = '3111d2351d08'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.add_column(
            sa.Column("current_balance", sa.Numeric(18, 4), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("balance_updated_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.drop_column("balance_updated_at")
        batch_op.drop_column("current_balance")
