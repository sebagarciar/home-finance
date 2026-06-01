from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


class Holding(Base):
    __tablename__ = "holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    price_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    asset_class: Mapped[str] = mapped_column(String(32), nullable=False, default="equity")
    manual_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    manual_price_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    account = relationship("Account", back_populates="holdings")
