from sqlalchemy import JSON, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class Assumptions(Base):
    """Single-row table holding household forecast inputs."""

    __tablename__ = "assumptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Income
    income_user1: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    income_user1_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="CLP")
    income_user2: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    income_user2_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    income_growth_rate: Mapped[float] = mapped_column(Numeric(8, 6), nullable=False, default=0.02)
    income_noise_sigma: Mapped[float] = mapped_column(Numeric(8, 6), nullable=False, default=0.05)

    # Spending
    spending_baseline_monthly: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    spending_baseline_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="CLP")
    spending_growth_rate: Mapped[float] = mapped_column(Numeric(8, 6), nullable=False, default=0.03)

    # Returns per asset class (annualized expectation, used for non-bootstrap fallback)
    return_assumptions: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=lambda: {"equity": 0.07, "bonds": 0.03, "cash": 0.01}
    )
    asset_allocation: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=lambda: {"equity": 0.7, "bonds": 0.2, "cash": 0.1}
    )

    # Forecast
    horizon_years: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    correlation_rho: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False, default=0.3)
    inflation_rate: Mapped[float] = mapped_column(Numeric(8, 6), nullable=False, default=0.03)

    # FX scenario: annual drift of CLP vs major peers (0 = flat, default)
    fx_drift_annual: Mapped[float] = mapped_column(Numeric(8, 6), nullable=False, default=0.0)
