"""portfolio health review tables

Revision ID: a1b2c3d4e5f6
Revises: f6a7b8c9d0e1
Create Date: 2026-06-02 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "investor_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("primary_goal", sa.String(length=32), nullable=False),
        sa.Column("time_horizon", sa.String(length=16), nullable=False),
        sa.Column("risk_tolerance", sa.String(length=16), nullable=False),
        sa.Column("risk_capacity", sa.String(length=16), nullable=False),
        sa.Column("loss_reaction", sa.String(length=24), nullable=False),
        sa.Column("monthly_income", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("monthly_income_currency", sa.String(length=3), nullable=False, server_default="CLP"),
        sa.Column("monthly_expenses", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("monthly_expenses_currency", sa.String(length=3), nullable=False, server_default="CLP"),
        sa.Column("emergency_fund_amount", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("emergency_fund_currency", sa.String(length=3), nullable=False, server_default="CLP"),
        sa.Column("expected_large_expenses", sa.JSON(), nullable=False),
        sa.Column("income_stability", sa.String(length=16), nullable=False),
        sa.Column("investment_knowledge", sa.String(length=12), nullable=False),
        sa.Column("tax_residence", sa.String(length=2), nullable=False, server_default=""),
        sa.Column("base_currency", sa.String(length=3), nullable=False, server_default="CLP"),
        sa.Column("constraints", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "investment_policy_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "investor_profile_id",
            sa.Integer(),
            sa.ForeignKey("investor_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("risk_profile", sa.String(length=16), nullable=False),
        sa.Column("target_allocation", sa.JSON(), nullable=False),
        sa.Column("allocation_ranges", sa.JSON(), nullable=False),
        sa.Column("max_single_holding_pct", sa.Numeric(6, 2), nullable=False),
        sa.Column("max_sector_pct", sa.Numeric(6, 2), nullable=False),
        sa.Column("max_country_pct", sa.Numeric(6, 2), nullable=False),
        sa.Column("max_currency_pct", sa.Numeric(6, 2), nullable=False),
        sa.Column("max_crypto_pct", sa.Numeric(6, 2), nullable=False),
        sa.Column("max_employer_stock_pct", sa.Numeric(6, 2), nullable=False),
        sa.Column("emergency_fund_target_months", sa.Numeric(5, 2), nullable=False),
        sa.Column("rebalance_threshold_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "portfolio_health_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "investor_profile_id",
            sa.Integer(),
            sa.ForeignKey("investor_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "investment_policy_profile_id",
            sa.Integer(),
            sa.ForeignKey("investment_policy_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("portfolio_snapshot", sa.JSON(), nullable=False),
        sa.Column("overall_score", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("sub_scores", sa.JSON(), nullable=False),
        sa.Column("diagnostics", sa.JSON(), nullable=False),
        sa.Column("missing_data", sa.JSON(), nullable=False),
        sa.Column("ai_explanation", sa.JSON(), nullable=True),
        sa.Column("rules_engine_version", sa.String(length=8), nullable=False),
        sa.Column("ai_prompt_version", sa.String(length=8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "portfolio_findings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "review_id",
            sa.Integer(),
            sa.ForeignKey("portfolio_health_reviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(length=24), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("finding", sa.String(length=512), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("why_it_matters", sa.String(length=512), nullable=False),
        sa.Column("educational_guidance", sa.String(length=512), nullable=False),
        sa.Column("prohibited_specific_advice", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("portfolio_findings")
    op.drop_table("portfolio_health_reviews")
    op.drop_table("investment_policy_profiles")
    op.drop_table("investor_profiles")
