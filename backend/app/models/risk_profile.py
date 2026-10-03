"""Risk & goal answers that set the target mix (Forecast → Profile).

History-preserving: each save adds a row; the latest one is active. Money is
not asked here — it lives in the household profile or comes from the data.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class RiskProfile(Base):
    __tablename__ = "risk_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    time_horizon: Mapped[str] = mapped_column(String(16), nullable=False)
    risk_tolerance: Mapped[str] = mapped_column(String(16), nullable=False)
    risk_capacity: Mapped[str] = mapped_column(String(16), nullable=False)
    loss_reaction: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
