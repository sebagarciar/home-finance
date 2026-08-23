"""Portfolio Health Review models.

Single-tenant (one household) — no user_id anywhere. The four tables form the
audit trail of a Portfolio Health Review:

- InvestorProfile: the user's self-reported answers (questionnaire). Kept as
  history; the latest row is the active profile.
- InvestmentPolicyProfile: deterministically derived from an InvestorProfile —
  risk profile, target allocation ranges, concentration limits, liquidity target.
- PortfolioHealthReview: one run of the rules engine — captured portfolio
  snapshot, computed diagnostics, scores, and (Stage 3) the AI explanation.
- PortfolioFinding: the structured findings produced by the engine for a review.

All money is Numeric(18, 4); JSON columns use the generic SQLAlchemy JSON type so
the schema is portable to Postgres.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


class InvestorProfile(Base):
    """User questionnaire answers. History-preserving: latest row is active."""

    __tablename__ = "investor_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    primary_goal: Mapped[str] = mapped_column(String(32), nullable=False)
    time_horizon: Mapped[str] = mapped_column(String(16), nullable=False)
    risk_tolerance: Mapped[str] = mapped_column(String(16), nullable=False)
    risk_capacity: Mapped[str] = mapped_column(String(16), nullable=False)
    loss_reaction: Mapped[str] = mapped_column(String(24), nullable=False)

    monthly_income: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    monthly_income_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="CLP")
    monthly_expenses: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    monthly_expenses_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="CLP")
    emergency_fund_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    emergency_fund_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="CLP")

    # List of {label, amount, currency, months_away}
    expected_large_expenses: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    income_stability: Mapped[str] = mapped_column(String(16), nullable=False)
    investment_knowledge: Mapped[str] = mapped_column(String(12), nullable=False)
    tax_residence: Mapped[str] = mapped_column(String(2), nullable=False, default="")
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="CLP")

    # {esg, max_crypto_pct, max_single_stock_pct, employer_stock_ticker,
    #  restricted_sectors[], prefer_low_cost_index, notes} — all optional
    constraints: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class InvestmentPolicyProfile(Base):
    """Deterministically derived policy. Re-derived whenever the profile changes."""

    __tablename__ = "investment_policy_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    investor_profile_id: Mapped[int] = mapped_column(
        ForeignKey("investor_profiles.id", ondelete="CASCADE"), nullable=False
    )

    risk_profile: Mapped[str] = mapped_column(String(16), nullable=False)

    # {cash, bonds, global_equities, alternatives, crypto} midpoints (percent)
    target_allocation: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # {class: [min, max]} in percent
    allocation_ranges: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    max_single_holding_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    max_sector_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    max_country_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    max_currency_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    max_crypto_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    max_employer_stock_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)

    emergency_fund_target_months: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    rebalance_threshold_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PortfolioHealthReview(Base):
    """One run of the rules engine. Full audit trail of inputs + outputs."""

    __tablename__ = "portfolio_health_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    investor_profile_id: Mapped[int] = mapped_column(
        ForeignKey("investor_profiles.id", ondelete="CASCADE"), nullable=False
    )
    investment_policy_profile_id: Mapped[int] = mapped_column(
        ForeignKey("investment_policy_profiles.id", ondelete="CASCADE"), nullable=False
    )

    # The current_networth() dict captured at review time.
    portfolio_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    overall_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    sub_scores: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Computed allocation/concentration/liquidity/stress numbers (engine inputs).
    diagnostics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    missing_data: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # null until Stage 3 (AI explanation layer)
    ai_explanation: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    rules_engine_version: Mapped[str] = mapped_column(String(8), nullable=False)
    ai_prompt_version: Mapped[str | None] = mapped_column(String(8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    findings = relationship(
        "PortfolioFinding",
        back_populates="review",
        cascade="all, delete-orphan",
        order_by="PortfolioFinding.id",
    )


class PortfolioFinding(Base):
    """A single structured finding produced by the rules engine."""

    __tablename__ = "portfolio_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[int] = mapped_column(
        ForeignKey("portfolio_health_reviews.id", ondelete="CASCADE"), nullable=False
    )

    category: Mapped[str] = mapped_column(String(24), nullable=False)
    severity: Mapped[str] = mapped_column(String(8), nullable=False)
    finding: Mapped[str] = mapped_column(String(512), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    why_it_matters: Mapped[str] = mapped_column(String(512), nullable=False)
    educational_guidance: Mapped[str] = mapped_column(String(512), nullable=False)
    prohibited_specific_advice: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    review = relationship("PortfolioHealthReview", back_populates="findings")


class SecurityMetadata(Base):
    """yfinance-enriched metadata for individual tickers.

    Cached per ticker with a 7-day TTL for auto-enriched rows. Manual
    overrides (source='manual') are never overwritten by auto-enrichment.
    Absence of a row means "not yet enriched"; every field except ticker and
    source is nullable — partial data is valid.
    """

    __tablename__ = "security_metadata"

    ticker: Mapped[str] = mapped_column(String(24), primary_key=True)
    asset_class: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(64), nullable=True)
    region: Mapped[str | None] = mapped_column(String(32), nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    product_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    expense_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    diversified_fund: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    liquidity_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source: Mapped[str] = mapped_column(String(8), nullable=False, default="auto")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
