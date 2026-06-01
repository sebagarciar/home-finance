import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class RuleSource(str, enum.Enum):
    rule = "rule"
    learned = "learned"
    manual = "manual"
    llm = "llm"


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("name", name="uq_categories_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class CategoryRule(Base):
    """Maps a normalized merchant pattern to a category. Acts as the learned map."""

    __tablename__ = "category_rules"
    __table_args__ = (UniqueConstraint("normalized_description", name="uq_category_rules_norm"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    normalized_description: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[RuleSource] = mapped_column(Enum(RuleSource), nullable=False, default=RuleSource.rule)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
