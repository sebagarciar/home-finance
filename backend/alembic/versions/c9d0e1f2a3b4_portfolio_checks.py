"""portfolio checks: replace the scored Health Review with a live mix check

- Drops portfolio_findings, portfolio_health_reviews, investment_policy_profiles
  and security_metadata (stored reviews and yfinance metadata are not used by
  the live check; their rows are not recoverable on downgrade).
- investor_profiles keeps only the answers that set the target mix
  (horizon, tolerance, capacity, loss reaction) and becomes risk_profiles.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-10-03 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: str | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Answers that only fed the removed checks: (name, type, server default for downgrade).
_DROPPED_ANSWERS = (
    ("primary_goal", sa.String(32), "long_term_growth"),
    ("income_stability", sa.String(16), "stable"),
    ("investment_knowledge", sa.String(12), "intermediate"),
    ("tax_residence", sa.String(2), ""),
    ("base_currency", sa.String(3), "CLP"),
    ("constraints", sa.JSON(), "{}"),
)


def upgrade() -> None:
    op.drop_table("portfolio_findings")
    op.drop_table("portfolio_health_reviews")
    op.drop_table("investment_policy_profiles")
    op.drop_table("security_metadata")
    with op.batch_alter_table("investor_profiles") as b:
        for name, _, _ in _DROPPED_ANSWERS:
            b.drop_column(name)
        b.drop_column("updated_at")
    op.rename_table("investor_profiles", "risk_profiles")


def downgrade() -> None:
    op.rename_table("risk_profiles", "investor_profiles")
    with op.batch_alter_table("investor_profiles") as b:
        for name, type_, default in _DROPPED_ANSWERS:
            b.add_column(sa.Column(name, type_, nullable=False, server_default=default))
        b.add_column(sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(),
        ))

    op.create_table(
        "investment_policy_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("investor_profile_id", sa.Integer(),
                  sa.ForeignKey("investor_profiles.id", ondelete="CASCADE"), nullable=False),
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
        sa.Column("investor_profile_id", sa.Integer(),
                  sa.ForeignKey("investor_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("investment_policy_profile_id", sa.Integer(),
                  sa.ForeignKey("investment_policy_profiles.id", ondelete="CASCADE"), nullable=False),
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
        sa.Column("review_id", sa.Integer(),
                  sa.ForeignKey("portfolio_health_reviews.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(length=24), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("finding", sa.String(length=512), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("why_it_matters", sa.String(length=512), nullable=False),
        sa.Column("educational_guidance", sa.String(length=512), nullable=False),
        sa.Column("prohibited_specific_advice", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
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
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
