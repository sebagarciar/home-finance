from datetime import date
from decimal import Decimal

from sqlalchemy import JSON, Date, Integer, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class NetworthSnapshot(Base):
    __tablename__ = "networth_snapshots"
    __table_args__ = (UniqueConstraint("date", name="uq_networth_snapshots_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    total_networth_in_base: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    breakdown: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
