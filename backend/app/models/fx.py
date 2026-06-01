from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class FxRate(Base):
    __tablename__ = "fx_rates"
    __table_args__ = (
        UniqueConstraint("date", "base_currency", "quote_currency", name="uq_fx_rates_date_pair"),
        Index("ix_fx_rates_pair_date", "base_currency", "quote_currency", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # rate: 1 base = `rate` quote
    rate: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
