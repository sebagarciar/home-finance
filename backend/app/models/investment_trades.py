import enum
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


class TradeKind(str, enum.Enum):
    # Seeds basis without full history ("I held N units at avg P"). Behaves like
    # a buy; at most one per holding and it must be the earliest row.
    opening = "opening"
    buy = "buy"
    sell = "sell"
    dividend = "dividend"
    fee = "fee"


class InvestmentTrade(Base):
    """Cost-basis ledger for a holding.

    `Holding.quantity` stays the (manual) source of truth for valuation; this
    ledger only supplies basis and returns. See services/performance/.
    """

    __tablename__ = "investment_trades"
    __table_args__ = (Index("ix_investment_trades_holding_date", "holding_id", "date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    holding_id: Mapped[int] = mapped_column(
        ForeignKey("holdings.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[TradeKind] = mapped_column(Enum(TradeKind), nullable=False)
    # Always >= 0; direction comes from `kind`. 0 for dividend/fee.
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=0)
    # Per-unit price in `currency`. Unused for dividend/fee.
    price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    # Cash amount for dividend/fee rows, native.
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    # Commission on buy/sell, native.
    fees: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    # Must equal holding.price_currency at write time; stored so a later
    # currency edit on the holding is detectable rather than silently wrong.
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # 1 `currency` = fx_rate_to_base CLP on `date` (captured via to_base).
    fx_rate_to_base: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    note: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    holding = relationship("Holding", back_populates="trades")
