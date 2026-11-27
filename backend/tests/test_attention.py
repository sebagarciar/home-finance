"""Needs-attention checks + endpoint."""
from __future__ import annotations

import itertools
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_session
from app.main import app
from app.models import Account, AccountType, Holding, PriceCacheEntry, Transaction
from app.services.attention import checks

TODAY = date(2026, 10, 3)
_ids = itertools.count(1)


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture
def db(session_factory):
    s = session_factory()
    yield s
    s.close()


@pytest.fixture
def client(session_factory):
    def override():
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override
    yield TestClient(app)
    app.dependency_overrides.pop(get_session, None)


def _account(db, name="Santander", type_=AccountType.checking, ccy="EUR",
             balance="100", updated: date | None = TODAY) -> Account:
    a = Account(
        name=name, country="ES", type=type_, native_currency=ccy,
        current_balance=Decimal(balance),
        balance_updated_at=datetime(updated.year, updated.month, updated.day, tzinfo=UTC) if updated else None,
    )
    db.add(a)
    db.flush()
    return a


def _txn(db, account: Account, d: date, amount: str, *, ccy="EUR", source="statement",
         category: str | None = "Supermarket", archived=False, desc="x") -> Transaction:
    t = Transaction(
        account_id=account.id, date=d, amount=Decimal(amount), currency=ccy,
        fx_rate_to_base=Decimal("1000"), category=category, raw_description=desc,
        normalized_description=desc, dedup_hash=f"h{next(_ids)}", source=source, archived=archived,
    )
    db.add(t)
    db.flush()
    return t


# ── stale balances ────────────────────────────────────────────────────────────

def test_stale_balance_flags_old_and_never_set(db):
    _account(db, "fresh", updated=TODAY - timedelta(days=10))
    old = _account(db, "old", updated=TODAY - timedelta(days=40))
    never = _account(db, "never", updated=None)
    _account(db, "broker", type_=AccountType.investment, balance="0", updated=None)
    _account(db, "Manual", balance="0", updated=None)  # seeded catch-all: nothing to track
    zero_set = _account(db, "emptied", balance="0", updated=TODAY - timedelta(days=40))
    cash_broker = _account(db, "broker cash", type_=AccountType.investment, balance="5", updated=None)

    items = checks.stale_balances(db, TODAY)

    assert {i.data["account_id"] for i in items} == {old.id, never.id, cash_broker.id, zero_set.id}
    by_id = {i.data["account_id"]: i for i in items}
    assert by_id[old.id].data["age_days"] == 40
    assert by_id[never.id].key == f"stale_balance:{never.id}:never"


def test_stale_balance_key_changes_after_update(db):
    a = _account(db, updated=TODAY - timedelta(days=40))
    first = checks.stale_balances(db, TODAY)[0].key
    a.balance_updated_at = datetime(2026, 9, 30, tzinfo=UTC)
    later = checks.stale_balances(db, TODAY + timedelta(days=60))[0].key
    assert first != later  # a dismissal doesn't silence the next staleness


# ── statements ───────────────────────────────────────────────────────────────

def test_missing_statement_for_closed_email_only_month(db):
    a = _account(db)
    b = _account(db, "Revolut")
    _txn(db, a, date(2026, 8, 12), "-10", source="email")
    _txn(db, a, date(2026, 8, 20), "-20", source="email")
    # b's August has a statement → fine
    _txn(db, b, date(2026, 8, 5), "-5", source="email")
    _txn(db, b, date(2026, 8, 6), "-6", source="statement")
    # current month: statement not out yet → skipped
    _txn(db, a, date(2026, 10, 1), "-7", source="email")
    # superseded email rows are archived → not counted
    _txn(db, a, date(2026, 7, 3), "-8", source="email", archived=True)

    items = checks.missing_statements(db, TODAY)

    assert [(i.data["account_id"], i.data["month"], i.data["email_rows"]) for i in items] == [
        (a.id, "2026-08", 2),
    ]


def test_bank_sync_rows_count_as_month_coverage(db):
    a = _account(db)
    # leftover email row, but the bank's booked rows cover the month → not missing
    _txn(db, a, date(2026, 8, 12), "-10", source="email")
    _txn(db, a, date(2026, 8, 12), "-10", source="bank_sync")
    # a month with email rows only is still flagged
    _txn(db, a, date(2026, 7, 3), "-8", source="email")

    assert [i.data["month"] for i in checks.missing_statements(db, TODAY)] == ["2026-07"]


def test_missing_statement_handles_december(db):
    a = _account(db)
    _txn(db, a, date(2025, 12, 31), "-1", source="email")
    _txn(db, a, date(2026, 1, 2), "-1", source="statement")  # next month's statement doesn't count
    assert [i.data["month"] for i in checks.missing_statements(db, TODAY)] == ["2025-12"]


# ── uncategorized ────────────────────────────────────────────────────────────

def test_uncategorized_counts_recent_other_and_null(db):
    a = _account(db)
    _txn(db, a, TODAY - timedelta(days=5), "-1", category="Other")
    _txn(db, a, TODAY - timedelta(days=5), "-1", category=None)
    _txn(db, a, TODAY - timedelta(days=5), "-1", category="Other", archived=True)
    _txn(db, a, TODAY - timedelta(days=400), "-1", category="Other")
    _txn(db, a, TODAY - timedelta(days=5), "-1", category="Restaurant")

    [item] = checks.uncategorized(db, TODAY)
    assert item.data["count"] == 2
    assert item.key == "uncategorized:2"


def test_uncategorized_empty(db):
    _account(db)
    assert checks.uncategorized(db, TODAY) == []


# ── transfer pairs ───────────────────────────────────────────────────────────

def test_transfer_pair_same_currency_opposite_amounts(db):
    a = _account(db, "Santander")
    b = _account(db, "Revolut")
    out = _txn(db, a, TODAY - timedelta(days=10), "-250.00")
    inn = _txn(db, b, TODAY - timedelta(days=9), "250")

    [item] = checks.transfer_pairs(db, TODAY)
    assert item.data["out"]["id"] == out.id
    assert item.data["in"]["id"] == inn.id
    assert item.key == f"transfer_pair:{min(out.id, inn.id)}:{max(out.id, inn.id)}"


@pytest.mark.parametrize("case", ["same_account", "too_far", "other_currency", "archived", "too_old"])
def test_transfer_pair_rejections(db, case):
    a = _account(db, "Santander")
    b = _account(db, "Revolut")
    d = TODAY - timedelta(days=10)
    _txn(db, a, d, "-250")
    if case == "same_account":
        _txn(db, a, d, "250")
    elif case == "too_far":
        _txn(db, b, d + timedelta(days=4), "250")
    elif case == "other_currency":
        _txn(db, b, d, "250", ccy="CLP")
    elif case == "archived":
        _txn(db, b, d, "250", archived=True)
    elif case == "too_old":
        db.query(Transaction).update({Transaction.date: TODAY - timedelta(days=200)})
        _txn(db, b, TODAY - timedelta(days=200), "250")
    assert checks.transfer_pairs(db, TODAY) == []


def test_transfer_pair_matches_each_row_once_closest_first(db):
    a = _account(db, "Santander")
    b = _account(db, "Revolut")
    c = _account(db, "BBVA")
    o1 = _txn(db, a, TODAY - timedelta(days=10), "-100")
    o2 = _txn(db, c, TODAY - timedelta(days=12), "-100")
    i1 = _txn(db, b, TODAY - timedelta(days=10), "100")

    items = checks.transfer_pairs(db, TODAY)
    # One inflow pairs with exactly one outflow: the same-day one, even though
    # the earlier outflow (2 days off) is also in the window and comes first.
    assert [(it.data["out"]["id"], it.data["in"]["id"]) for it in items] == [(o1.id, i1.id)]
    assert o2.id not in {items[0].data["out"]["id"], items[0].data["in"]["id"]}


# ── prices ───────────────────────────────────────────────────────────────────

def test_stale_prices(db):
    a = _account(db, "Broker", type_=AccountType.investment, ccy="USD")

    def holding(ticker, manual: str | None = None, manual_on: date | None = None):
        h = Holding(
            account_id=a.id, ticker=ticker, quantity=Decimal("1"), price_currency="USD",
            manual_price=Decimal(manual) if manual else None,
            manual_price_updated_at=datetime(manual_on.year, manual_on.month, manual_on.day, tzinfo=UTC)
            if manual_on else None,
        )
        db.add(h)
        db.flush()
        return h

    live = holding("VT")
    db.add(PriceCacheEntry(ticker="VT", date=TODAY - timedelta(days=2), price=Decimal("100"), currency="USD"))
    old_live = holding("AGG")
    db.add(PriceCacheEntry(ticker="AGG", date=TODAY - timedelta(days=10), price=Decimal("90"), currency="USD"))
    fresh_manual = holding("PRIV", manual="5", manual_on=TODAY - timedelta(days=5))
    old_manual = holding("OLD", manual="5", manual_on=TODAY - timedelta(days=45))
    never = holding("NONE")

    items = {i.data["holding_id"]: i for i in checks.stale_prices(db, TODAY)}

    assert set(items) == {old_live.id, old_manual.id, never.id}
    assert live.id not in items and fresh_manual.id not in items
    assert items[old_live.id].data["last_priced_on"] == (TODAY - timedelta(days=10)).isoformat()
    assert items[never.id].key == f"stale_price:{never.id}:never"


# ── endpoint ─────────────────────────────────────────────────────────────────

def test_endpoint_lists_dismisses_and_restores(client, session_factory):
    with session_factory() as s:
        _account(s, "old", updated=date.today() - timedelta(days=90))
        s.commit()

    body = client.get("/attention").json()
    assert body["dismissed"] == 0
    [item] = [i for i in body["items"] if i["kind"] == "stale_balance"]
    assert item["account_name"] == "old"

    assert client.post("/attention/dismiss", json={"key": item["key"]}).status_code == 204
    assert client.post("/attention/dismiss", json={"key": item["key"]}).status_code == 204  # idempotent
    body = client.get("/attention").json()
    assert all(i["key"] != item["key"] for i in body["items"])
    assert body["dismissed"] == 1

    assert client.delete("/attention/dismissals").status_code == 204
    assert any(i["key"] == item["key"] for i in client.get("/attention").json()["items"])


def test_migration_up_and_down(tmp_path: Path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cwd = Path(__file__).resolve().parents[1]

    def run(*args: str) -> None:
        subprocess.run([sys.executable, "-m", "alembic", *args], cwd=cwd,
                       env={"DATABASE_URL": url, "PATH": ""}, check=True, capture_output=True)

    def tables() -> list[str]:
        eng = create_engine(url)
        try:
            return inspect(eng).get_table_names()
        finally:
            eng.dispose()

    run("upgrade", "a7b8c9d0e1f2")
    assert "attention_dismissals" in tables()
    run("downgrade", "e5f6a7b8c9d0")
    assert "attention_dismissals" not in tables()
