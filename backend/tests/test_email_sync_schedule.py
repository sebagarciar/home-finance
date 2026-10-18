from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select

from app.config import get_settings
from app.models import Account, AccountType, EmailSyncStatus, Transaction, TxnType
from app.seeds.defaults import seed
from app.services.email_ingest import scheduler
from app.services.email_ingest import sync as sync_mod


def _setup(db) -> Account:
    seed(db)
    acct = Account(
        name="Santander ES", institution="Santander", country="ES",
        type=AccountType.checking, native_currency="EUR", current_balance=Decimal("0"),
    )
    db.add(acct)
    db.flush()
    db.add(
        Transaction(
            account_id=acct.id, date=date.today(), amount=Decimal("-12"), currency="EUR",
            fx_rate_to_base=Decimal("1"), txn_type=TxnType.card_payment, category="Other",
            raw_description="CAFE X", normalized_description="cafe x", dedup_hash="h1",
            source="email",
        )
    )
    db.commit()
    return acct


def _stub(category):
    return lambda *a, **k: type("C", (), {"category": category})()


def test_recategorize_moves_other_and_is_throttled(db, monkeypatch):
    _setup(db)
    monkeypatch.setattr(sync_mod, "classify", _stub("Restaurant"))

    assert sync_mod.recategorize_recent_other(db) == 1
    assert db.execute(select(Transaction.category)).scalar_one() == "Restaurant"

    # Put it back on Other: the hourly throttle blocks an immediate retry...
    row = db.execute(select(Transaction)).scalar_one()
    row.category = "Other"
    db.commit()
    assert sync_mod.recategorize_recent_other(db) == 0
    # ...unless forced.
    assert sync_mod.recategorize_recent_other(db, force=True) == 1


def test_recategorize_leaves_still_unclassified_rows(db, monkeypatch):
    _setup(db)
    monkeypatch.setattr(sync_mod, "classify", _stub("Other"))
    assert sync_mod.recategorize_recent_other(db) == 0
    assert db.execute(select(Transaction.category)).scalar_one() == "Other"


def test_run_email_sync_records_status(db, monkeypatch):
    acct = _setup(db)
    monkeypatch.setattr(sync_mod, "fetch_santander_emails", lambda **k: [])
    monkeypatch.setattr(sync_mod, "archive_santander_emails", lambda uids, **k: None)
    monkeypatch.setattr(sync_mod, "classify", _stub("Other"))

    sync_mod.run_email_sync(db, acct.id)
    st = db.get(EmailSyncStatus, 1)
    assert st is not None and st.last_ok is True and st.last_run_at is not None

    sync_mod.record_error(db, "boom")
    st = db.get(EmailSyncStatus, 1)
    assert st.last_ok is False and st.last_error == "boom"


def test_scheduler_disabled_by_default(monkeypatch):
    monkeypatch.setattr(get_settings(), "email_sync_times", "")
    assert scheduler.start_email_sync() is None


def _at(h, m=0, day=18):
    return datetime(2026, 10, day, h, m).astimezone()


def test_is_due_catches_up_missed_slots():
    times = scheduler.parse_times("12:00, 16:00")
    assert [t.hour for t in times] == [12, 16]
    # Before the first slot of the day: yesterday's 16:00 is the latest slot.
    assert not scheduler.is_due(_at(9), _at(16, 5, day=17), True, times)
    assert scheduler.is_due(_at(9), _at(10, 0, day=17), True, times)
    # 12:00 passed, last run was this morning -> due; ran after 12:00 -> not due.
    assert scheduler.is_due(_at(12, 1), _at(8), True, times)
    assert not scheduler.is_due(_at(12, 30), _at(12, 1), True, times)
    # Mac was asleep through 12:00 and woke at 15:00 -> still due (catch-up).
    assert scheduler.is_due(_at(15), _at(8), True, times)
    # Never run -> due as soon as any slot has passed.
    assert scheduler.is_due(_at(13), None, None, times)


def test_is_due_retries_failures_after_backoff():
    times = scheduler.parse_times("12:00")
    assert not scheduler.is_due(_at(12, 10), _at(12, 1), False, times)
    assert scheduler.is_due(_at(12, 20), _at(12, 1), False, times)


def test_scheduled_run_records_failure_instead_of_raising(db, monkeypatch):
    acct = _setup(db)
    monkeypatch.setattr(scheduler, "resolve_account_id", lambda *a: acct.id)
    monkeypatch.setattr(scheduler, "is_due", lambda *a: True)
    monkeypatch.setattr(scheduler, "SessionLocal", lambda: _Ctx(db))

    def _boom(*a, **k):
        raise RuntimeError("imap exploded")

    monkeypatch.setattr(scheduler, "run_email_sync", _boom)
    scheduler._check_and_run([])  # must not raise
    st = db.get(EmailSyncStatus, 1)
    assert st.last_ok is False and "imap exploded" in st.last_error


class _Ctx:
    """Lets `with SessionLocal() as db` hand back the test session unclosed."""

    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *a):
        return False
