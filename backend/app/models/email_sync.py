from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class EmailSyncStatus(Base):
    """Single-row (id=1) record of the latest email sync, scheduled or manual.

    Lets the Update panel show "synced 8 min ago" and surfaces failures the
    background loop would otherwise only log.
    """

    __tablename__ = "email_sync_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_ok: Mapped[bool | None] = mapped_column()
    last_error: Mapped[str | None] = mapped_column(String(512))
    last_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_imported: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Throttle for the "retry Other rows" pass (see services/email_ingest/sync.py).
    last_recategorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
