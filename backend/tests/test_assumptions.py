"""Phase 7: assumptions GET/PUT endpoint tests."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_session
from app.main import app
from app.seeds.defaults import seed


@pytest.fixture
def client(monkeypatch):
    # Keep the forecast run in test_assumptions_feed_forecast offline/deterministic.
    from app.services.forecast import engine as engine_mod
    from app.services.forecast.blocks import ReturnsUnavailable

    def _no_network(*args, **kwargs):
        raise ReturnsUnavailable("network disabled in tests")

    monkeypatch.setattr(engine_mod, "fetch_monthly_returns", _no_network)

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_get_assumptions_returns_seeded_defaults(client):
    r = client.get("/assumptions")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["horizon_years"] == 30
    assert body["asset_allocation"]["equity"] == 0.7
    # Seeded defaults: no income/spending set yet.
    assert float(body["income_user1"]) == 0


def test_put_partial_update_persists(client):
    r = client.put(
        "/assumptions",
        json={
            "income_user1": "2500000",
            "income_user1_currency": "clp",
            "spending_baseline_monthly": "1800000",
            "horizon_years": 25,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert float(body["income_user1"]) == 2500000
    assert body["income_user1_currency"] == "CLP"  # upper-cased
    assert float(body["spending_baseline_monthly"]) == 1800000
    assert body["horizon_years"] == 25
    # Untouched field keeps its default.
    assert body["asset_allocation"]["equity"] == 0.7

    # Persisted across requests.
    assert float(client.get("/assumptions").json()["income_user1"]) == 2500000


def test_put_rejects_negative_allocation(client):
    r = client.put("/assumptions", json={"asset_allocation": {"equity": -0.1, "bonds": 1.1}})
    assert r.status_code == 422


def test_put_rejects_out_of_range_horizon(client):
    assert client.put("/assumptions", json={"horizon_years": 0}).status_code == 422
    assert client.put("/assumptions", json={"horizon_years": 200}).status_code == 422


def test_assumptions_feed_forecast(client):
    """A spending deficit should pull the median below the starting net worth."""
    # Heavy spending, no income, on a short horizon: net worth must fall.
    client.put(
        "/assumptions",
        json={
            "spending_baseline_monthly": "5000000",
            "income_user1": "0",
            "income_user2": "0",
            "horizon_years": 5,
        },
    )
    r = client.post("/forecast/run", json={"n_paths": 500, "seed": 1, "real": False})
    assert r.status_code == 200, r.text
    body = r.json()
    # With zero start net worth (no accounts) and pure spending, terminal median
    # is negative.
    assert body["terminal"]["p50"] < body["start_networth"]
