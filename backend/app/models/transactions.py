import enum
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


class TxnType(str, enum.Enum):
    card_payment = "card_payment"
    transfer = "transfer"
    deposit = "deposit"
    refund = "refund"
    direct_debit = "direct_debit"
    fee = "fee"
    other = "other"


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("dedup_hash", name="uq_transactions_dedup_hash"),
        Index("ix_transactions_account_date", "account_id", "date"),
        # The spending dashboard filters by date range without an account
        # predicate, so the composite above doesn't cover it.
        Index("ix_transactions_date", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)  # native currency, signed
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # FX rate from this txn's currency to base (CLP) on `date`.
    fx_rate_to_base: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    txn_type: Mapped[TxnType] = mapped_column(
        Enum(TxnType), nullable=False, default=TxnType.card_payment
    )
    category: Mapped[str | None] = mapped_column(String(64))
    raw_description: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    normalized_description: Mapped[str] = mapped_column(String(512), nullable=False, default="", index=True)
    dedup_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Where this row came from: "statement" (an uploaded bank file — the source of
    # truth) or "email" (a provisional row ingested from a transaction-notification
    # email). A statement import archives any overlapping "email" rows so the
    # statement wins. See services/importers/service.py:commit_import.
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="statement", server_default="statement")
    # Soft-delete / archive flag. Archived rows are hidden from totals and from the
    # default transactions list, but kept on disk so the user can restore them.
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

    account = relationship("Account", back_populates="transactions")
