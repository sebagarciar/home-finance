import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


class AccountType(str, enum.Enum):
    checking = "checking"
    credit = "credit"
    savings = "savings"
    investment = "investment"
    debt = "debt"


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    institution: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str] = mapped_column(String(2), nullable=False)  # ISO 3166-1 alpha-2
    type: Mapped[AccountType] = mapped_column(Enum(AccountType), nullable=False)
    native_currency: Mapped[str] = mapped_column(String(3), nullable=False)  # ISO 4217
    # Manual cash balance in `native_currency`. Source of truth for net-worth —
    # not derived from transactions, since transaction history is partial.
    # Debt accounts store a positive number here (loan balance); net-worth
    # subtracts it.
    current_balance: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0, server_default="0")
    balance_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    transactions = relationship("Transaction", back_populates="account", cascade="all, delete-orphan")
    holdings = relationship("Holding", back_populates="account", cascade="all, delete-orphan")
