"""Phase 5 — holdings + portfolio + net-worth.

Covers:
- USD-priced holding valuation: qty × price × USD/CLP matches the two-hop conversion.
- Manual price fallback: provider failure routes to manual_price, is_manual=True.
- Snapshot round-trip: take_snapshot then history endpoint surfaces the row.
- Net-worth tile: cash uses current FX (not historical), holdings sum in.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_session
from app.main import app
from app.models import Account, AccountType, FxRate, Holding, Transaction
from app.models.transactions import TxnType
from app.services.prices import valuation as valuation_mod
from app.services.prices.provider import PriceLookupError, PriceProvider, PriceQuote


class StubPriceProvider(PriceProvider):
    def __init__(self, quotes: dict[str, PriceQuote], fail: set[str] | None = None):
        self.quotes = quotes
        self.fail = fail or set()
        self.calls: list[str] = []

    def fetch(self, ticker: str) -> PriceQuote:
        ticker = ticker.upper()
        self.calls.append(ticker)
        if ticker in self.fail:
            raise PriceLookupError(f"stub failure for {ticker}")
        if ticker not in self.quotes:
            raise PriceLookupError(f"no stub for {ticker}")
        return self.quotes[ticker]


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
def client(session_factory):
    def override():
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed_fx_today(db, pairs: dict[tuple[str, str], Decimal]):
    today = date.today()
    for (base, quote), rate in pairs.items():
        db.add(FxRate(date=today, base_currency=base, quote_currency=quote, rate=rate))
    db.commit()


def _patch_provider(monkeypatch, stub: PriceProvider):
    monkeypatch.setattr(valuation_mod, "get_provider", lambda: stub)


def test_usd_holding_valuation_two_hop(session_factory, monkeypatch):
    """qty × USD price → CLP via current USD/CLP rate."""
    db = session_factory()
    db.add(Account(name="IBKR", country="US", type=AccountType.investment, native_currency="USD"))
    db.commit()
    acc = db.query(Account).first()
    h = Holding(
        account_id=acc.id, ticker="SPY", quantity=Decimal("10"),
        price_currency="USD", asset_class="equity",
    )
    db.add(h)
    db.commit()
    db.refresh(h)

    _seed_fx_today(db, {("USD", "CLP"): Decimal("950")})
    stub = StubPriceProvider({"SPY": PriceQuote("SPY", Decimal("500"), "USD", date.today())})
    _patch_provider(monkeypatch, stub)

    priced = valuation_mod.price_holding(db, h)
    assert priced.price == Decimal("500")
    assert priced.is_manual is False
    # value_native = 10 * 500 = 5000 USD; in CLP = 5000 * 950 = 4_750_000
    from app.services.fx.conversion import to_base_current
    value_base = to_base_current(db, priced.value, priced.price_currency)
    assert value_base == Decimal("4750000")
    db.close()


def test_manual_price_fallback_when_provider_fails(session_factory, monkeypatch):
    db = session_factory()
    db.add(Account(name="IBKR", country="US", type=AccountType.investment, native_currency="USD"))
    db.commit()
    acc = db.query(Account).first()
    h = Holding(
        account_id=acc.id, ticker="UNKNOWN", quantity=Decimal("3"),
        price_currency="USD", asset_class="equity",
        manual_price=Decimal("100"),
        manual_price_updated_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    db.add(h)
    db.commit()
    db.refresh(h)

    stub = StubPriceProvider({}, fail={"UNKNOWN"})
    _patch_provider(monkeypatch, stub)

    priced = valuation_mod.price_holding(db, h)
    assert priced.is_manual is True
    assert priced.source == "manual"
    assert priced.price == Decimal("100")
    assert priced.as_of == date(2026, 5, 1)
    db.close()


def test_missing_price_when_no_manual_and_provider_fails(session_factory, monkeypatch):
    db = session_factory()
    db.add(Account(name="IBKR", country="US", type=AccountType.investment, native_currency="USD"))
    db.commit()
    acc = db.query(Account).first()
    h = Holding(
        account_id=acc.id, ticker="NOPE", quantity=Decimal("1"),
        price_currency="USD", asset_class="equity",
    )
    db.add(h)
    db.commit()
    db.refresh(h)

    stub = StubPriceProvider({}, fail={"NOPE"})
    _patch_provider(monkeypatch, stub)

    priced = valuation_mod.price_holding(db, h)
    assert priced.missing is True
    assert priced.is_manual is True
    assert priced.price == Decimal("0")
    db.close()


def test_price_cache_hit_short_circuits_provider(session_factory, monkeypatch):
    """Second call within TTL must not re-hit the provider."""
    db = session_factory()
    stub = StubPriceProvider({"AAA": PriceQuote("AAA", Decimal("42"), "USD", date.today())})
    _patch_provider(monkeypatch, stub)

    q1 = valuation_mod.current_price(db, "AAA")
    q2 = valuation_mod.current_price(db, "AAA")
    assert q1.price == q2.price == Decimal("42")
    assert stub.calls == ["AAA"]  # only the first call hit the provider
    db.close()


def test_networth_current_endpoint_includes_cash_and_holdings(client, session_factory, monkeypatch):
    db = session_factory()
    # Cash from manual current_balance (NOT derived from transactions).
    # A historical 100 EUR deposit is also present and must be ignored by net-worth.
    eur_acc = Account(
        name="Sant ES", country="ES", type=AccountType.checking, native_currency="EUR",
        current_balance=Decimal("100"),
    )
    usd_acc = Account(name="IBKR", country="US", type=AccountType.investment, native_currency="USD")
    db.add_all([eur_acc, usd_acc])
    db.commit()
    db.add(Transaction(
        account_id=eur_acc.id, date=date(2026, 1, 1),
        amount=Decimal("999"), currency="EUR",  # must not affect net worth
        fx_rate_to_base=Decimal("900"),
        txn_type=TxnType.deposit, category="Salary",
        raw_description="seed", normalized_description="seed", dedup_hash="seed1",
    ))
    db.add(Holding(
        account_id=usd_acc.id, ticker="SPY", quantity=Decimal("2"),
        price_currency="USD", asset_class="equity",
    ))
    _seed_fx_today(db, {
        ("EUR", "CLP"): Decimal("1050"),
        ("USD", "CLP"): Decimal("950"),
    })
    db.commit()
    db.close()

    stub = StubPriceProvider({"SPY": PriceQuote("SPY", Decimal("500"), "USD", date.today())})
    _patch_provider(monkeypatch, stub)

    r = client.get("/networth/current")
    assert r.status_code == 200
    body = r.json()
    # cash: 100 EUR * 1050 (CURRENT) = 105_000 CLP. NOT 100 * 900.
    assert Decimal(body["cash_total_in_base"]) == Decimal("105000")
    # holdings: 2 * 500 USD * 950 = 950_000 CLP
    assert Decimal(body["holdings_total_in_base"]) == Decimal("950000")
    assert Decimal(body["total_in_base"]) == Decimal("1055000")


def test_snapshot_persists_and_history_returns_it(client, session_factory, monkeypatch):
    db = session_factory()
    acc = Account(
        name="Cash", country="CL", type=AccountType.checking, native_currency="CLP",
        current_balance=Decimal("500000"),
    )
    db.add(acc)
    db.commit()
    db.close()

    stub = StubPriceProvider({})
    _patch_provider(monkeypatch, stub)

    r = client.post("/networth/snapshot")
    assert r.status_code == 201
    assert Decimal(r.json()["total_in_base"]) == Decimal("500000")

    # Re-running same date overwrites (no duplicate).
    r2 = client.post("/networth/snapshot")
    assert r2.status_code == 201

    history = client.get("/networth/history").json()
    assert len(history) == 1
    assert Decimal(history[0]["total_in_base"]) == Decimal("500000")


def test_account_row_includes_holdings_value(client, session_factory, monkeypatch):
    """An investment account row reports cash + holdings + total."""
    db = session_factory()
    acc = Account(
        name="IBKR", country="US", type=AccountType.investment,
        native_currency="USD", current_balance=Decimal("500"),  # cash sweep
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    db.add(Holding(
        account_id=acc.id, ticker="SPY", quantity=Decimal("10"),
        price_currency="USD", asset_class="equity",
    ))
    db.commit()
    db.close()

    sess = session_factory()
    _seed_fx_today(sess, {("USD", "CLP"): Decimal("950")})
    sess.close()
    _patch_provider(monkeypatch, StubPriceProvider({
        "SPY": PriceQuote("SPY", Decimal("400"), "USD", date.today())
    }))

    body = client.get("/networth/current").json()
    row = next(r for r in body["by_account"] if r["name"] == "IBKR")
    # cash: 500 * 950 = 475_000
    assert Decimal(row["cash_in_base"]) == Decimal("475000")
    # holdings: 10 * 400 * 950 = 3_800_000
    assert Decimal(row["holdings_in_base"]) == Decimal("3800000")
    assert Decimal(row["total_in_base"]) == Decimal("4275000")


def test_debt_account_subtracts_from_networth(client, session_factory, monkeypatch):
    db = session_factory()
    db.add_all([
        Account(
            name="Checking", country="CL", type=AccountType.checking,
            native_currency="CLP", current_balance=Decimal("1000000"),
        ),
        Account(
            name="Mortgage", country="CL", type=AccountType.debt,
            native_currency="CLP", current_balance=Decimal("400000"),
        ),
    ])
    db.commit()
    db.close()
    _patch_provider(monkeypatch, StubPriceProvider({}))

    body = client.get("/networth/current").json()
    assert Decimal(body["total_in_base"]) == Decimal("600000")
    # Debt bucket present and negative.
    by_class = {r["asset_class"]: Decimal(r["total_in_base"]) for r in body["by_asset_class"]}
    assert by_class["cash"] == Decimal("1000000")
    assert by_class["debt"] == Decimal("-400000")


def test_balance_endpoint_updates_networth(client, session_factory, monkeypatch):
    _patch_provider(monkeypatch, StubPriceProvider({}))
    r = client.post("/accounts", json={
        "name": "Bank", "country": "CL", "type": "checking",
        "native_currency": "CLP", "current_balance": "0",
    })
    acc_id = r.json()["id"]
    assert Decimal(client.get("/networth/current").json()["total_in_base"]) == 0

    r = client.put(f"/accounts/{acc_id}/balance", json={"current_balance": "250000"})
    assert r.status_code == 200
    assert r.json()["balance_updated_at"] is not None
    assert Decimal(client.get("/networth/current").json()["total_in_base"]) == Decimal("250000")


def test_holdings_crud(client, session_factory, monkeypatch):
    db = session_factory()
    db.add(Account(name="IBKR", country="US", type=AccountType.investment, native_currency="USD"))
    db.commit()
    acc_id = db.query(Account).first().id
    db.close()

    stub = StubPriceProvider({"SPY": PriceQuote("SPY", Decimal("500"), "USD", date.today())})
    _patch_provider(monkeypatch, stub)
    # Seed FX so value_in_base resolves.
    sess = session_factory()
    _seed_fx_today(sess, {("USD", "CLP"): Decimal("950")})
    sess.close()

    r = client.post("/holdings", json={
        "account_id": acc_id, "ticker": "spy", "quantity": "4",
        "price_currency": "usd", "asset_class": "equity",
    })
    assert r.status_code == 201
    h = r.json()
    assert h["ticker"] == "SPY"
    assert Decimal(h["value_in_base"]) == Decimal("1900000")  # 4*500*950
    holding_id = h["id"]

    # Manual price override.
    r = client.put(f"/holdings/{holding_id}/manual_price", json={"manual_price": "123.45"})
    assert r.status_code == 200
    # Provider still works; manual_price is stored but live price preferred.
    assert Decimal(r.json()["manual_price"]) == Decimal("123.45")

    # When provider fails AND no cache, fallback uses manual price.
    stub.fail.add("SPY")
    from app.models.prices import PriceCacheEntry
    sess = session_factory()
    sess.query(PriceCacheEntry).delete()
    sess.commit()
    sess.close()
    rows = client.get("/holdings").json()
    assert rows[0]["is_manual"] is True
    assert Decimal(rows[0]["price"]) == Decimal("123.45")

    r = client.delete(f"/holdings/{holding_id}")
    assert r.status_code == 204
    assert client.get("/holdings").json() == []


def test_by_currency_breakdown(session_factory, monkeypatch):
    """Net worth groups by denomination currency: CLP cash, EUR cash, USD holding."""
    db = session_factory()
    db.add(Account(name="Scotia CL", country="CL", type=AccountType.checking, native_currency="CLP"))
    db.add(Account(name="Santander ES", country="ES", type=AccountType.checking, native_currency="EUR"))
    db.add(Account(name="IBKR", country="US", type=AccountType.investment, native_currency="USD"))
    db.commit()
    clp_acc, eur_acc, usd_acc = db.query(Account).order_by(Account.id).all()
    clp_acc.current_balance = Decimal("1000000")  # 1,000,000 CLP
    eur_acc.current_balance = Decimal("1000")      # 1,000 EUR
    h = Holding(
        account_id=usd_acc.id, ticker="SPY", quantity=Decimal("10"),
        price_currency="USD", asset_class="equity",
    )
    db.add(h)
    db.commit()

    _seed_fx_today(db, {("EUR", "CLP"): Decimal("1000"), ("USD", "CLP"): Decimal("950")})
    stub = StubPriceProvider({"SPY": PriceQuote("SPY", Decimal("500"), "USD", date.today())})
    _patch_provider(monkeypatch, stub)

    from app.services.networth.snapshot import current_networth
    nw = current_networth(db)
    by_cur = {row["currency"]: Decimal(row["total_in_base"]) for row in nw["by_currency"]}

    # CLP: 1,000,000 ; EUR: 1,000 * 1000 = 1,000,000 ; USD: 10 * 500 * 950 = 4,750,000
    assert by_cur["CLP"] == Decimal("1000000")
    assert by_cur["EUR"] == Decimal("1000000")
    assert by_cur["USD"] == Decimal("4750000")
    # Sum of currency buckets equals total net worth.
    assert sum(by_cur.values()) == Decimal(nw["total_in_base"])
    db.close()
