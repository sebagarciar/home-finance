"""Phase 4 endpoint tests: accounts CRUD, transactions list/filter, spending summary,
manual category update with rule propagation."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_session
from app.main import app
from app.models import CategoryRule, Transaction
from app.models.categories import RuleSource
from app.models.transactions import TxnType
from app.seeds.defaults import seed


@pytest.fixture
def client(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # share one connection so :memory: tables persist
        future=True,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    with TestingSession() as s:
        seed(s)

    def override():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override

    # Phase 4 endpoints don't invoke the FX provider — categorization in commit_import
    # is patched per test if needed.
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed_transactions(client):
    # Create an account.
    r = client.post(
        "/accounts",
        json={"name": "Santander ES", "country": "ES", "type": "checking", "native_currency": "EUR"},
    )
    assert r.status_code == 201, r.text
    acc_id = r.json()["id"]

    # Insert transactions directly via the session for speed (bypass the import pipeline).
    from app.main import app as _app
    db_override = _app.dependency_overrides[get_session]
    gen = db_override()
    db = next(gen)
    try:
        db.add_all([
            Transaction(
                account_id=acc_id, date=date(2026, 1, 15),
                amount=Decimal("-50.00"), currency="EUR",
                fx_rate_to_base=Decimal("1000"),  # 1 EUR = 1000 CLP
                txn_type=TxnType.card_payment, category="Supermarket",
                raw_description="Mercadona Madrid", normalized_description="mercadona",
                dedup_hash="h1",
            ),
            Transaction(
                account_id=acc_id, date=date(2026, 1, 20),
                amount=Decimal("-20.00"), currency="EUR",
                fx_rate_to_base=Decimal("1000"),
                txn_type=TxnType.card_payment, category="Restaurant",
                raw_description="Wetaca", normalized_description="wetaca",
                dedup_hash="h2",
            ),
            Transaction(
                account_id=acc_id, date=date(2026, 2, 10),
                amount=Decimal("-100.00"), currency="EUR",
                fx_rate_to_base=Decimal("1050"),
                txn_type=TxnType.card_payment, category="Supermarket",
                raw_description="Mercadona", normalized_description="mercadona",
                dedup_hash="h3",
            ),
            Transaction(
                account_id=acc_id, date=date(2026, 2, 12),
                amount=Decimal("500.00"), currency="EUR",  # inflow — must NOT count as spending
                fx_rate_to_base=Decimal("1050"),
                txn_type=TxnType.deposit, category="Transfers",
                raw_description="Salary", normalized_description="salary",
                dedup_hash="h4",
            ),
        ])
        db.commit()
    finally:
        gen.close()
    return acc_id


def test_accounts_list_and_create(client):
    # Defaults seed creates a "Manual" account for hand-entered transactions.
    seeded = client.get("/accounts").json()
    assert [a["name"] for a in seeded] == ["Manual"]

    r = client.post(
        "/accounts",
        json={"name": "Test", "country": "CL", "type": "checking", "native_currency": "CLP"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Test"
    assert body["country"] == "CL"
    names = {a["name"] for a in client.get("/accounts").json()}
    assert names == {"Manual", "Test"}


def test_categories_list_returns_seeded_taxonomy(client):
    names = {c["name"] for c in client.get("/categories").json()}
    # The new 13-category taxonomy
    assert {"Supermarket", "Restaurant", "Transport", "Subscriptions", "Other"} <= names


def test_transactions_filter_by_date_and_category(client):
    _seed_transactions(client)
    all_rows = client.get("/transactions").json()
    assert len(all_rows) == 4

    feb = client.get("/transactions", params={"start": "2026-02-01"}).json()
    assert len(feb) == 2

    super_rows = client.get("/transactions", params={"category": "Supermarket"}).json()
    assert len(super_rows) == 2
    assert all(t["category"] == "Supermarket" for t in super_rows)

    deposits = client.get("/transactions", params={"txn_type": "deposit"}).json()
    assert len(deposits) == 1
    assert deposits[0]["category"] == "Transfers"


def test_transactions_amount_in_base_is_computed(client):
    _seed_transactions(client)
    rows = client.get("/transactions", params={"category": "Restaurant"}).json()
    assert len(rows) == 1
    # -20 EUR * 1000 = -20000 CLP
    assert Decimal(rows[0]["amount_in_base"]) == Decimal("-20000")


def test_spending_summary_includes_all_non_salary_categories(client):
    _seed_transactions(client)
    s = client.get("/spending/summary").json()
    # Mercadona: -50*1000 + -100*1050 = 155,000. Wetaca: -20*1000 = 20,000.
    # Deposit categorized "Transfers" (500*1050 inflow) = -525,000 spend.
    # All categories shown, including the negative Transfers — user-visible
    # signal, not silently dropped.
    by_cat = {c["category"]: Decimal(c["total"]) for c in s["by_category"]}
    assert by_cat["Supermarket"] == Decimal("155000")
    assert by_cat["Restaurant"] == Decimal("20000")
    assert by_cat["Transfers"] == Decimal("-525000")
    assert Decimal(s["total_spent"]) == Decimal("-350000")

    months = {m["month"]: Decimal(m["total"]) for m in s["by_month"]}
    # 2026-01: 50k + 20k = 70k. 2026-02: 105k - 525k = -420k.
    assert months == {"2026-01": Decimal("70000"), "2026-02": Decimal("-420000")}


def test_spending_summary_excludes_salary_and_feeds_income_series(client):
    """Salary is the one category kept out of the spending series; its
    positive inflows feed by_month_income instead."""
    acc_id = _seed_transactions(client)
    from app.main import app as _app
    db_override = _app.dependency_overrides[get_session]
    gen = db_override()
    db = next(gen)
    try:
        db.add(
            Transaction(
                account_id=acc_id, date=date(2026, 4, 1),
                amount=Decimal("2000.00"), currency="EUR",
                fx_rate_to_base=Decimal("1000"),
                txn_type=TxnType.deposit, category="Salary",
                raw_description="Payroll", normalized_description="payroll",
                dedup_hash="h_salary",
            )
        )
        db.commit()
    finally:
        gen.close()

    s = client.get("/spending/summary", params={"start": "2026-04-01"}).json()
    by_cat = {c["category"]: Decimal(c["total"]) for c in s["by_category"]}
    assert "Salary" not in by_cat
    income = {m["month"]: Decimal(m["total"]) for m in s["by_month_income"]}
    # native amount * fx_rate = 2000 * 1000 = 2,000,000
    assert income["2026-04"] == Decimal("2000000")


def test_spending_summary_nets_same_category_inflows(client):
    """A reimbursement (deposit/transfer) tagged the same as an outflow
    offsets that category's spend — Bizum-from-friend semantics."""
    acc_id = _seed_transactions(client)
    from app.main import app as _app
    db_override = _app.dependency_overrides[get_session]
    gen = db_override()
    db = next(gen)
    try:
        db.add_all([
            # -300 EUR Airbnb in March (Travel outflow)
            Transaction(
                account_id=acc_id, date=date(2026, 3, 10),
                amount=Decimal("-300.00"), currency="EUR",
                fx_rate_to_base=Decimal("1000"),
                txn_type=TxnType.card_payment, category="Travel",
                raw_description="Airbnb", normalized_description="airbnb",
                dedup_hash="h5",
            ),
            # +100 EUR Bizum from a friend repaying their share (Travel inflow)
            Transaction(
                account_id=acc_id, date=date(2026, 3, 12),
                amount=Decimal("100.00"), currency="EUR",
                fx_rate_to_base=Decimal("1000"),
                txn_type=TxnType.deposit, category="Travel",
                raw_description="Bizum from friend",
                normalized_description="bizum",
                dedup_hash="h6",
            ),
        ])
        db.commit()
    finally:
        gen.close()

    s = client.get("/spending/summary", params={"start": "2026-03-01"}).json()
    by_cat = {c["category"]: Decimal(c["total"]) for c in s["by_category"]}
    # 300*1000 outflow - 100*1000 inflow = 200,000 net
    assert by_cat["Travel"] == Decimal("200000")
    assert Decimal(s["total_spent"]) == Decimal("200000")
    mar = {m["month"]: Decimal(m["total"]) for m in s["by_month"]}
    assert mar["2026-03"] == Decimal("200000")


def test_category_update_propagates_rule(client):
    _seed_transactions(client)
    # Find the Wetaca row
    rows = client.get("/transactions", params={"category": "Restaurant"}).json()
    txn_id = rows[0]["id"]

    r = client.patch(
        f"/transactions/{txn_id}/category",
        json={"category": "Subscriptions", "propagate": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["category"] == "Subscriptions"
    assert body["propagated"] is True

    # And the rule for "wetaca" must now be source=manual, category=Subscriptions.
    gen = app.dependency_overrides[get_session]()
    db = next(gen)
    try:
        rule = db.query(CategoryRule).filter_by(normalized_description="wetaca").one()
        assert rule.source == RuleSource.manual
        assert rule.category == "Subscriptions"
    finally:
        gen.close()


def test_category_update_rejects_unknown_category(client):
    _seed_transactions(client)
    rows = client.get("/transactions").json()
    r = client.patch(
        f"/transactions/{rows[0]['id']}/category",
        json={"category": "Cryptography", "propagate": False},
    )
    assert r.status_code == 400
