"""Free composite FX provider (mindicador.cl + frankfurter.app) and the
POST /fx/rerate backfill endpoint."""
from datetime import date
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_session
from app.main import app
from app.models import Account, AccountType, Transaction
from app.models.fx import FxRate
from app.models.transactions import TxnType
from app.services.fx.provider import (
    CurrencyApiProvider,
    FrankfurterProvider,
    FreeCompositeFxProvider,
    MindicadorClient,
)

# --------------------------------------------------------------------------- #
# Stubbed HTTP for the two free APIs
# --------------------------------------------------------------------------- #

# mindicador year series: banking days only (2025-03-07 is a Friday).
_MINDICADOR_SERIES = {
    "dolar": {"2025-03-07": "955.12", "2025-03-10": "957.80"},
    "euro": {"2025-03-07": "1042.50", "2025-03-10": "1045.00"},
}
_FRANKFURTER_RATES = {("GBP", "EUR"): "1.1700", ("EUR", "USD"): "1.0800"}


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.host == "mindicador.cl":
        # /api/{indicator}/{year}
        _, indicator, _year = request.url.path.rsplit("/", 2)
        serie = [
            {"fecha": f"{d}T03:00:00.000Z", "valor": float(v)}
            for d, v in _MINDICADOR_SERIES[indicator].items()
        ]
        return httpx.Response(200, json={"serie": serie})
    if request.url.host == "api.frankfurter.app":
        pair = (request.url.params["from"], request.url.params["to"])
        rate = _FRANKFURTER_RATES.get(pair)
        if rate is None:
            return httpx.Response(404, json={"message": "not found"})
        return httpx.Response(200, json={"rates": {pair[1]: float(rate)}})
    raise AssertionError(f"unexpected host: {request.url.host}")


class _CountingHandler:
    def __init__(self):
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request.url.host)
        return _handler(request)


@pytest.fixture
def composite():
    handler = _CountingHandler()
    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = FreeCompositeFxProvider(
        mindicador=MindicadorClient(api_base="https://mindicador.cl/api", client=client),
        frankfurter=FrankfurterProvider(api_base="https://api.frankfurter.app", client=client),
    )
    return provider, handler


# --------------------------------------------------------------------------- #
# CurrencyApiProvider (default "free" provider)
# --------------------------------------------------------------------------- #

def _currency_api_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_currency_api_fetches_pair():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "cdn.jsdelivr.net"
        assert "@2025-11-14" in request.url.path and request.url.path.endswith("/eur.json")
        return httpx.Response(200, json={"date": "2025-11-14", "eur": {"clp": 1081.79805179}})

    p = CurrencyApiProvider(client=_currency_api_client(handler))
    assert p.fetch(date(2025, 11, 14), "EUR", "CLP") == Decimal("1081.79805179")


def test_currency_api_falls_back_to_mirror():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        if request.url.host == "cdn.jsdelivr.net":
            return httpx.Response(503)
        return httpx.Response(200, json={"usd": {"clp": 940.5}})

    p = CurrencyApiProvider(client=_currency_api_client(handler))
    assert p.fetch(date(2025, 11, 14), "USD", "CLP") == Decimal("940.5")
    assert calls == ["cdn.jsdelivr.net", "2025-11-14.currency-api.pages.dev"]


def test_currency_api_same_day_falls_back_to_latest_tag():
    today = date.today()

    def handler(request: httpx.Request) -> httpx.Response:
        if "latest" in str(request.url):
            return httpx.Response(200, json={"eur": {"clp": 1040.0}})
        return httpx.Response(404)  # today's snapshot not published yet

    p = CurrencyApiProvider(client=_currency_api_client(handler))
    assert p.fetch(today, "EUR", "CLP") == Decimal("1040.0")


def test_currency_api_walks_back_over_dataset_gap_days():
    # The dataset has occasional missing days; the provider must use the
    # nearest earlier snapshot instead of failing.
    def handler(request: httpx.Request) -> httpx.Response:
        if "@2025-12-10" in request.url.path or "2025-12-10" in request.url.host:
            return httpx.Response(404)
        if "@2025-12-09" in request.url.path:
            return httpx.Response(200, json={"eur": {"clp": 1071.25}})
        return httpx.Response(404)

    p = CurrencyApiProvider(client=_currency_api_client(handler))
    assert p.fetch(date(2025, 12, 10), "EUR", "CLP") == Decimal("1071.25")


def test_currency_api_missing_quote_raises():
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return httpx.Response(200, json={"eur": {"usd": 1.08}})

    p = CurrencyApiProvider(client=_currency_api_client(handler))
    with pytest.raises(LookupError):
        p.fetch(date(2025, 11, 14), "EUR", "XXX")


# --------------------------------------------------------------------------- #
# Mindicador composite (alternative provider) unit tests
# --------------------------------------------------------------------------- #

def test_usd_to_clp_uses_mindicador(composite):
    provider, handler = composite
    rate = provider.fetch(date(2025, 3, 10), "USD", "CLP")
    assert rate == Decimal("957.80")
    assert handler.requests == ["mindicador.cl"]


def test_weekend_walks_back_to_last_banking_day(composite):
    provider, _ = composite
    # 2025-03-09 is a Sunday — no fixing published; Friday 03-07 must be used.
    assert provider.fetch(date(2025, 3, 9), "EUR", "CLP") == Decimal("1042.50")


def test_clp_to_eur_is_inverted(composite):
    provider, _ = composite
    rate = provider.fetch(date(2025, 3, 10), "CLP", "EUR")
    assert rate == Decimal("1") / Decimal("1045.00")


def test_gbp_to_clp_crosses_via_ecb_eur(composite):
    provider, handler = composite
    rate = provider.fetch(date(2025, 3, 10), "GBP", "CLP")
    # GBP->EUR (ECB) 1.17 × EUR->CLP (BCCh) 1045 = 1222.65
    assert rate == Decimal("1.1700") * Decimal("1045.00")
    assert set(handler.requests) == {"mindicador.cl", "api.frankfurter.app"}


def test_non_clp_pair_goes_to_frankfurter_only(composite):
    provider, handler = composite
    assert provider.fetch(date(2025, 3, 10), "EUR", "USD") == Decimal("1.0800")
    assert handler.requests == ["api.frankfurter.app"]


def test_year_series_is_fetched_once_per_year(composite):
    provider, handler = composite
    provider.fetch(date(2025, 3, 7), "USD", "CLP")
    provider.fetch(date(2025, 3, 10), "USD", "CLP")
    provider.fetch(date(2025, 3, 9), "USD", "CLP")  # weekend walk-back, same series
    assert handler.requests == ["mindicador.cl"]


def test_missing_value_raises_lookup_error(composite):
    provider, _ = composite
    # 2025-06-01 is >10 days past the last stubbed fixing — must not guess.
    with pytest.raises(LookupError):
        provider.fetch(date(2025, 6, 1), "USD", "CLP")


# --------------------------------------------------------------------------- #
# POST /fx/rerate
# --------------------------------------------------------------------------- #

@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    def override():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override
    yield TestClient(app)
    app.dependency_overrides.pop(get_session, None)


def _db(client):  # noqa: ARG001 — uses the active override
    gen = app.dependency_overrides[get_session]()
    return next(gen)


def test_rerate_corrects_fallback_rates_and_poisoned_cache(client, monkeypatch, composite):
    provider, _ = composite
    monkeypatch.setattr("app.routers.fx.get_provider", lambda: provider)

    db = _db(client)
    acc = Account(name="S", country="ES", type=AccountType.checking, native_currency="EUR")
    db.add(acc)
    db.flush()
    db.add_all([
        # Imported on the approximate fallback rate (1050) while offline.
        Transaction(
            account_id=acc.id, date=date(2025, 3, 10), amount=Decimal("-100"),
            currency="EUR", fx_rate_to_base=Decimal("1050"),
            txn_type=TxnType.card_payment, dedup_hash="r1",
        ),
        # CLP row — must not be touched.
        Transaction(
            account_id=acc.id, date=date(2025, 3, 10), amount=Decimal("-5000"),
            currency="CLP", fx_rate_to_base=Decimal("1"),
            txn_type=TxnType.card_payment, dedup_hash="r2",
        ),
    ])
    # Poisoned cache row from before the fallback-no-persist fix.
    db.add(FxRate(date=date(2025, 3, 10), base_currency="EUR", quote_currency="CLP", rate=Decimal("1050")))
    db.commit()

    r = client.post("/fx/rerate")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {
        "transactions_scanned": 1,
        "updated": 1,
        "unchanged": 0,
        "skipped": 0,
        "failures": [],
    }

    db = _db(client)
    txn = db.execute(select(Transaction).where(Transaction.dedup_hash == "r1")).scalar_one()
    assert Decimal(str(txn.fx_rate_to_base)) == Decimal("1045.00")
    cached = db.execute(select(FxRate).where(FxRate.base_currency == "EUR")).scalar_one()
    assert Decimal(str(cached.rate)) == Decimal("1045.00")

    # Idempotent: second run changes nothing.
    r2 = client.post("/fx/rerate")
    assert r2.json()["updated"] == 0
    assert r2.json()["unchanged"] == 1


def test_rerate_reports_failures_without_aborting(client, monkeypatch, composite):
    provider, _ = composite
    monkeypatch.setattr("app.routers.fx.get_provider", lambda: provider)

    db = _db(client)
    acc = Account(name="S", country="ES", type=AccountType.checking, native_currency="EUR")
    db.add(acc)
    db.flush()
    db.add_all([
        Transaction(
            account_id=acc.id, date=date(2025, 3, 10), amount=Decimal("-100"),
            currency="EUR", fx_rate_to_base=Decimal("1050"),
            txn_type=TxnType.card_payment, dedup_hash="f1",
        ),
        # No fixing within 10 days of this date in the stub — must fail cleanly.
        Transaction(
            account_id=acc.id, date=date(2025, 6, 1), amount=Decimal("-50"),
            currency="EUR", fx_rate_to_base=Decimal("1050"),
            txn_type=TxnType.card_payment, dedup_hash="f2",
        ),
    ])
    db.commit()

    body = client.post("/fx/rerate").json()
    assert body["updated"] == 1
    assert body["skipped"] == 1
    assert len(body["failures"]) == 1 and "2025-06-01" in body["failures"][0]

    db = _db(client)
    untouched = db.execute(select(Transaction).where(Transaction.dedup_hash == "f2")).scalar_one()
    assert Decimal(str(untouched.fx_rate_to_base)) == Decimal("1050")
