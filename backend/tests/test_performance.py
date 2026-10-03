"""Cost basis + performance.

Covers:
- Average-cost replay: running average, realized gain, fees in basis/proceeds.
- Ledger validation: oversell, opening must be first and unique.
- XIRR against hand-computed and Excel reference values; period vs annualized.
- Price/FX attribution on a USD holding; zero FX effect on a CLP holding.
- Reconciliation: qty mismatch / no trades suppress gains.
- Endpoints: buy-by-amount, oversell 422 on create/edit/delete, date edit
  re-captures FX, GET /performance totals + coverage, holding delete cascades.
- Migration upgrade/downgrade.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_session
from app.main import app
from app.models import Account, AccountType, FxRate, Holding, InvestmentTrade, TradeKind
from app.services.performance import LedgerError, TradeInput, replay, validate_ledger, xirr
from app.services.performance.service import holding_performance
from app.services.prices import valuation as valuation_mod
from app.services.prices.provider import PriceProvider, PriceQuote

D = Decimal
TODAY = date.today()
TWO_YEARS_AGO = TODAY - timedelta(days=730)
ONE_YEAR_AGO = TODAY - timedelta(days=365)


class StubPrices(PriceProvider):
    def __init__(self, quotes: dict[str, tuple[str, str]]):
        self.quotes = quotes

    def fetch(self, ticker: str) -> PriceQuote:
        price, ccy = self.quotes[ticker.upper()]
        return PriceQuote(ticker=ticker.upper(), price=D(price), currency=ccy, as_of=TODAY)


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


def _fx(db, on: date, ccy: str, rate: str) -> None:
    db.add(FxRate(date=on, base_currency=ccy, quote_currency="CLP", rate=D(rate)))
    db.commit()


def _holding(db, ticker: str, qty: str, ccy: str) -> Holding:
    acct = db.execute(select(Account)).scalars().first()
    if acct is None:
        acct = Account(name="Broker", country="CL", type=AccountType.investment, native_currency="CLP")
        db.add(acct)
        db.flush()
    h = Holding(account_id=acct.id, ticker=ticker, quantity=D(qty), price_currency=ccy)
    db.add(h)
    db.commit()
    return h


def _trade(db, h: Holding, on: date, kind: TradeKind, *, qty="0", price="0",
           amount="0", fees="0", fx="1") -> None:
    h.trades.append(InvestmentTrade(
        date=on, kind=kind, quantity=D(qty), price=D(price), amount=D(amount),
        fees=D(fees), currency=h.price_currency, fx_rate_to_base=D(fx),
    ))
    db.commit()


def _prices(monkeypatch, quotes: dict[str, tuple[str, str]]) -> None:
    monkeypatch.setattr(valuation_mod, "get_provider", lambda: StubPrices(quotes))


# ---------------------------------------------------------------- pure engine


def _t(kind: TradeKind, on: date = date(2025, 1, 1), **kw) -> TradeInput:
    return TradeInput(date=on, kind=kind, **{k: D(v) for k, v in kw.items()})


def test_average_cost_and_realized_gain():
    s = replay([
        _t(TradeKind.buy, date(2025, 1, 1), quantity="10", price="100"),
        _t(TradeKind.buy, date(2025, 2, 1), quantity="10", price="200"),
        _t(TradeKind.sell, date(2025, 3, 1), quantity="5", price="300"),
    ])
    assert s.qty == D("15")
    assert s.avg_cost_native == D("150")
    assert s.realized_native == D("750")  # 5 × (300 − 150)
    assert s.cost_native == D("2250")


def test_fees_in_basis_and_proceeds():
    s = replay([
        _t(TradeKind.buy, quantity="10", price="100", fees="10"),
        _t(TradeKind.sell, date(2025, 2, 1), quantity="10", price="120", fees="5"),
    ])
    assert s.realized_native == D("1195") - D("1010")
    assert s.qty == 0 and s.cost_native == 0


def test_base_cost_uses_trade_date_fx():
    s = replay([
        _t(TradeKind.buy, quantity="1", price="100", fx_rate_to_base="900"),
        _t(TradeKind.buy, date(2025, 2, 1), quantity="1", price="100", fx_rate_to_base="1000"),
        _t(TradeKind.sell, date(2025, 3, 1), quantity="1", price="100", fx_rate_to_base="1100"),
    ])
    # Avg base cost 95,000/unit; sold for 110,000 → pure FX gain.
    assert s.realized_native == 0
    assert s.realized_base == D("15000")
    assert s.cost_base == D("95000")


def test_oversell_rejected():
    with pytest.raises(LedgerError, match="exceeds"):
        replay([
            _t(TradeKind.buy, quantity="5", price="1"),
            _t(TradeKind.sell, date(2025, 2, 1), quantity="6", price="1"),
        ])


def test_opening_must_be_first_and_unique():
    with pytest.raises(LedgerError, match="earliest"):
        validate_ledger([
            _t(TradeKind.buy, date(2025, 1, 1), quantity="1", price="1"),
            _t(TradeKind.opening, date(2025, 2, 1), quantity="1", price="1"),
        ])
    with pytest.raises(LedgerError, match="only one"):
        validate_ledger([
            _t(TradeKind.opening, quantity="1", price="1"),
            _t(TradeKind.opening, date(2025, 2, 1), quantity="1", price="1"),
        ])
    # Same-day buy entered before the opening still sorts after it.
    validate_ledger([
        _t(TradeKind.buy, quantity="1", price="1"),
        _t(TradeKind.opening, quantity="1", price="1"),
    ])


def test_xirr_simple_year():
    r = xirr([(date(2025, 1, 1), D("-100")), (date(2026, 1, 1), D("110"))])
    assert r == pytest.approx(0.10, abs=1e-9)


def test_xirr_excel_reference():
    # Microsoft's XIRR documentation example → 0.373362535.
    flows = [
        (date(2008, 1, 1), D("-10000")),
        (date(2008, 3, 1), D("2750")),
        (date(2008, 10, 30), D("4250")),
        (date(2009, 2, 15), D("3250")),
        (date(2009, 4, 1), D("2750")),
    ]
    assert xirr(flows) == pytest.approx(0.373362535, abs=1e-6)


def test_xirr_undefined_without_sign_change():
    assert xirr([(date(2025, 1, 1), D("-100")), (date(2025, 6, 1), D("-50"))]) is None
    assert xirr([(date(2025, 1, 1), D("-100"))]) is None


# ------------------------------------------------------- attribution + returns


def test_usd_holding_price_vs_fx_split(db, monkeypatch):
    _fx(db, TWO_YEARS_AGO, "USD", "900")
    _fx(db, TODAY, "USD", "1000")
    h = _holding(db, "VT", "10", "USD")
    _trade(db, h, TWO_YEARS_AGO, TradeKind.buy, qty="10", price="100", fx="900")
    _prices(monkeypatch, {"VT": ("100", "USD")})  # price unchanged

    p = holding_performance(db, h)
    assert p.issue is None
    assert p.state.cost_base == D("900000")
    assert p.value_base == D("1000000")
    assert p.unrealized_base == D("100000")
    assert p.price_effect == 0
    assert p.fx_effect == D("100000")
    assert p.ret_native.rate == pytest.approx(0.0, abs=1e-9)
    assert p.ret_base.annualized is True
    assert p.ret_base.rate == pytest.approx((1000 / 900) ** (365 / 730) - 1, abs=1e-6)


def test_clp_holding_has_no_fx_effect(db, monkeypatch):
    h = _holding(db, "FINTUAL:186", "100", "CLP")
    _trade(db, h, TWO_YEARS_AGO, TradeKind.opening, qty="100", price="1000")
    _prices(monkeypatch, {"FINTUAL:186": ("1200", "CLP")})

    p = holding_performance(db, h)
    assert p.unrealized_base == D("20000")
    assert p.price_effect == D("20000")
    assert p.fx_effect == 0


def test_under_a_year_is_period_return(db, monkeypatch):
    h = _holding(db, "AAA", "1", "CLP")
    _trade(db, h, TODAY - timedelta(days=30), TradeKind.buy, qty="1", price="100")
    _prices(monkeypatch, {"AAA": ("102", "CLP")})

    p = holding_performance(db, h)
    assert p.ret_base.annualized is False
    assert p.ret_base.rate == pytest.approx(0.02, abs=1e-6)


def test_mismatch_and_no_trades_suppress_gains(db, monkeypatch):
    _prices(monkeypatch, {"AAA": ("10", "CLP"), "BBB": ("10", "CLP")})
    a = _holding(db, "AAA", "120", "CLP")
    _trade(db, a, ONE_YEAR_AGO, TradeKind.buy, qty="118", price="9")
    b = _holding(db, "BBB", "5", "CLP")

    pa = holding_performance(db, a)
    assert pa.issue == "qty_mismatch" and pa.reconciled is False
    assert pa.unrealized_base is None and pa.ret_base.rate is None
    assert pa.state.cost_base == D("1062")  # basis still reported

    pb = holding_performance(db, b)
    assert pb.issue == "no_trades" and pb.has_basis is False
    assert pb.value_base == D("50")


# ------------------------------------------------------------------ endpoints


def test_trade_endpoints_and_performance(client, session_factory, monkeypatch):
    db = session_factory()
    _fx(db, ONE_YEAR_AGO, "USD", "900")
    _fx(db, TWO_YEARS_AGO, "USD", "800")
    _fx(db, TODAY, "USD", "1000")
    vt = _holding(db, "VT", "8", "USD")
    other = _holding(db, "BBB", "1", "CLP")  # no basis → excluded from coverage
    vt_id, other_id = vt.id, other.id
    db.close()
    _prices(monkeypatch, {"VT": ("120", "USD"), "BBB": ("4000", "CLP")})

    base = f"/holdings/{vt_id}/trades"
    # Buy by amount: (1005 − 5) / 100 = 10 units.
    r = client.post(base, json={"date": ONE_YEAR_AGO.isoformat(), "kind": "buy",
                                "amount": "1005", "price": "100", "fees": "5"})
    assert r.status_code == 201, r.text
    buy = r.json()
    assert D(buy["quantity"]) == 10 and D(buy["fx_rate_to_base"]) == 900

    assert client.post(base, json={"date": TODAY.isoformat(), "kind": "sell",
                                   "quantity": "11", "price": "120"}).status_code == 422
    assert client.post(base, json={"date": TODAY.isoformat(), "kind": "buy",
                                   "quantity": "1", "amount": "1", "price": "1"}).status_code == 422

    r = client.post(base, json={"date": TODAY.isoformat(), "kind": "sell",
                                "quantity": "2", "price": "120"})
    assert r.status_code == 201
    sell_id = r.json()["id"]

    # Deleting the buy would leave the sell overselling.
    assert client.delete(f"/trades/{buy['id']}").status_code == 422
    # Shrinking the buy below the later sell is rejected too.
    assert client.patch(f"/trades/{buy['id']}", json={"quantity": "1"}).status_code == 422

    # Moving the buy re-captures FX for the new date.
    r = client.patch(f"/trades/{buy['id']}", json={"date": TWO_YEARS_AGO.isoformat()})
    assert r.status_code == 200 and D(r.json()["fx_rate_to_base"]) == 800

    perf = client.get("/performance").json()
    row = next(h for h in perf["holdings"] if h["holding_id"] == vt_id)
    assert row["issue"] is None and row["reconciled"] is True
    assert D(row["cost_base"]) == D("1005") * 800 * 8 / 10
    assert D(row["value_base"]) == D("8") * 120 * 1000
    assert D(row["realized_base"]) == D("2") * 120 * 1000 - D("1005") * 800 * 2 / 10
    assert row["annualized"] is True and row["return"] > 0
    assert next(h for h in perf["holdings"] if h["holding_id"] == other_id)["issue"] == "no_trades"
    t = perf["totals"]
    assert D(t["value_base"]) == D(row["value_base"])
    assert t["coverage_pct"] == pytest.approx(960000 / (960000 + 4000))

    assert client.delete(f"/trades/{sell_id}").status_code == 204
    assert client.delete(f"/holdings/{vt_id}").status_code == 204
    s = session_factory()
    assert s.execute(select(InvestmentTrade)).first() is None
    s.close()


# ------------------------------------------------------------------ migration


def test_migration_up_and_down(tmp_path: Path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    env = {"DATABASE_URL": url, "PATH": ""}
    cwd = Path(__file__).resolve().parents[1]
    alembic = [sys.executable, "-m", "alembic"]

    def run(*args: str) -> None:
        subprocess.run([*alembic, *args], cwd=cwd, env=env, check=True, capture_output=True)

    run("upgrade", "head")
    eng = create_engine(url)
    assert "investment_trades" in inspect(eng).get_table_names()
    eng.dispose()
    run("downgrade", "-1")
    eng = create_engine(url)
    assert "investment_trades" not in inspect(eng).get_table_names()
    eng.dispose()
