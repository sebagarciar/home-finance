from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class AttentionDismissal(Base):
    """A "Needs attention" item the user dismissed (e.g. "not a transfer").

    Keyed on the item's stable key (see services/attention/checks.py). Keys
    embed the state they were raised on (a balance's update date, a count),
    so an item comes back on its own once that state changes.
    """

    __tablename__ = "attention_dismissals"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    dismissed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
