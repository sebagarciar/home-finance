"""Email sync: fetch → parse → import, plus a throttled retry of `Other` rows.

Shared by the manual endpoint (`POST /import/email/sync`) and the background
loop in `scheduler.py`, so both behave identically.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...models import EmailSyncStatus, Transaction
from ..categorization.cascade import FALLBACK_CATEGORY, classify, load_rules
from ..importers.base import ParsedTxn
from ..importers.santander_es_email import parse_santander_email
from ..importers.service import commit_import, preview_import
from .gmail import archive_santander_emails, fetch_santander_emails

logger = logging.getLogger(__name__)

# Recent email rows still on `Other` get another pass through the cascade, so a
# merchant that missed because Ollama was down (or whose rule was learned since)
# fixes itself. Throttled so a genuinely unclassifiable merchant doesn't hit the
# LLM on every cycle.
RECATEGORIZE_WINDOW_DAYS = 3
RECATEGORIZE_MIN_INTERVAL = timedelta(hours=1)


class EmailSyncConfigError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class EmailSyncResult:
    fetched: int
    parsed: int
    imported: int
    skipped: int
    recategorized: int = 0


def resolve_account_id(account_id: int | None = None) -> int:
    settings = get_settings()
    if not settings.gmail_user or not settings.gmail_app_password:
        raise EmailSyncConfigError(
            503, "Gmail credentials not configured (set GMAIL_USER / GMAIL_APP_PASSWORD)"
        )
    target = account_id if account_id is not None else settings.santander_email_account_id
    if target is None:
        raise EmailSyncConfigError(
            400, "No account_id given and SANTANDER_EMAIL_ACCOUNT_ID is unset"
        )
    return target


def get_status(db: Session) -> EmailSyncStatus:
    row = db.get(EmailSyncStatus, 1)
    if row is None:
        row = EmailSyncStatus(id=1, last_fetched=0, last_imported=0)
        db.add(row)
        db.flush()
    return row


def record_error(db: Session, message: str) -> None:
    db.rollback()
    st = get_status(db)
    st.last_run_at = datetime.now(UTC)
    st.last_ok = False
    st.last_error = message[:512]
    db.commit()


def recategorize_recent_other(db: Session, *, force: bool = False) -> int:
    """Re-run the cascade on recent email rows still categorized `Other`.
    Returns how many moved to a real category. Manual rules always win because
    the cascade's exact lookup runs first."""
    st = get_status(db)
    now = datetime.now(UTC)
    last = st.last_recategorized_at
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    if not force and last is not None and now - last < RECATEGORIZE_MIN_INTERVAL:
        return 0

    cutoff = date.today() - timedelta(days=RECATEGORIZE_WINDOW_DAYS)
    rows = db.execute(
        select(Transaction).where(
            Transaction.source == "email",
            Transaction.archived.is_(False),
            Transaction.date >= cutoff,
            or_(Transaction.category.is_(None), Transaction.category == FALLBACK_CATEGORY),
            Transaction.normalized_description != "",
        )
    ).scalars().all()

    rules = load_rules(db)
    moved = 0
    for row in rows:
        category = classify(db, row.normalized_description, rules).category
        if category != FALLBACK_CATEGORY:
            row.category = category
            moved += 1
    st.last_recategorized_at = now
    db.commit()
    return moved


def run_email_sync(
    db: Session, account_id: int, since: date | None = None, limit: int = 200
) -> EmailSyncResult:
    """Pull Santander ES notification emails and ingest the parseable ones as
    provisional (source="email") transactions. Idempotent: re-running only adds
    genuinely new rows. Records the outcome in `email_sync_status`."""
    uid_raw_pairs = fetch_santander_emails(since=since, limit=limit)
    parsed_pairs: list[tuple[str, ParsedTxn]] = [
        (uid, p)
        for uid, raw in uid_raw_pairs
        if (p := parse_santander_email(raw)) is not None
    ]
    parsed_uids = [uid for uid, _ in parsed_pairs]
    parsed_txns = [p for _, p in parsed_pairs]
    previews = preview_import(db, account_id, parsed_txns)
    result = commit_import(db, account_id, previews, source="email")
    # Archive only emails that were parseable; leave unrecognised ones in INBOX.
    archive_santander_emails(parsed_uids)

    recategorized = recategorize_recent_other(db)

    st = get_status(db)
    st.last_run_at = datetime.now(UTC)
    st.last_ok = True
    st.last_error = None
    st.last_fetched = len(uid_raw_pairs)
    st.last_imported = result.imported
    db.commit()

    return EmailSyncResult(
        fetched=len(uid_raw_pairs),
        parsed=len(parsed_txns),
        imported=result.imported,
        skipped=result.duplicates_skipped,
        recategorized=recategorized,
    )
