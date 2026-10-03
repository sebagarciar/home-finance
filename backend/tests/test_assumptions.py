"""Household profile (/assumptions) GET/PUT + derived endpoint tests."""
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
    assert "asset_allocation" not in body  # the forecast uses the current mix
    # Seeded defaults: no income set, spending derived (no override).
    assert float(body["income_user1"]) == 0
    assert body["spending_override_monthly"] is None
    assert body["planned_expenses"] == []


def test_put_partial_update_persists(client):
    r = client.put(
        "/assumptions",
        json={
            "income_user1": "2500000",
            "income_user1_currency": "clp",
            "spending_override_monthly": "1800000",
            "horizon_years": 25,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert float(body["income_user1"]) == 2500000
    assert body["income_user1_currency"] == "CLP"  # upper-cased
    assert float(body["spending_override_monthly"]) == 1800000
    assert body["horizon_years"] == 25
    # Untouched field keeps its default.
    assert body["inflation_rate"] == 0.03

    # Persisted across requests.
    assert float(client.get("/assumptions").json()["income_user1"]) == 2500000


def test_override_clears_with_explicit_null(client):
    client.put("/assumptions", json={"spending_override_monthly": "900"})
    body = client.put("/assumptions", json={"spending_override_monthly": None}).json()
    assert body["spending_override_monthly"] is None
    # A null for any other (non-nullable) field is ignored, not a 500.
    assert client.put("/assumptions", json={"horizon_years": None}).status_code == 200


def test_planned_expenses_validated_and_sorted(client):
    r = client.put("/assumptions", json={"planned_expenses": [
        {"label": "Car", "amount": "8000", "currency": "eur", "month": "2027-06"},
        {"label": "Flights", "amount": "1200", "currency": "EUR", "month": "2026-12"},
    ]})
    assert r.status_code == 200, r.text
    assert [e["month"] for e in r.json()["planned_expenses"]] == ["2026-12", "2027-06"]
    assert r.json()["planned_expenses"][1]["currency"] == "EUR"
    bad = {"label": "x", "amount": "10", "currency": "EUR", "month": "2027-13"}
    assert client.put("/assumptions", json={"planned_expenses": [bad]}).status_code == 422
    zero = {"label": "x", "amount": "0", "currency": "EUR", "month": "2027-01"}
    assert client.put("/assumptions", json={"planned_expenses": [zero]}).status_code == 422


def test_goals_validated_and_sorted(client):
    r = client.put("/assumptions", json={"goals": [
        {"label": "Deposit", "amount": "15000", "currency": "eur", "month": "2028-06"},
        {"label": "Buffer", "amount": "3000000", "currency": "CLP", "month": "2027-01"},
    ]})
    assert r.status_code == 200, r.text
    assert [g["label"] for g in r.json()["goals"]] == ["Buffer", "Deposit"]
    assert r.json()["goals"][1]["currency"] == "EUR"
    bad = {"label": "x", "amount": "-5", "currency": "EUR", "month": "2028-01"}
    assert client.put("/assumptions", json={"goals": [bad]}).status_code == 422


def test_derived_endpoint_without_data(client):
    body = client.get("/assumptions/derived").json()
    assert body["spending"] == {
        "derived_monthly": None, "months": [], "effective_monthly": "0", "source": "none",
    }
    assert body["allocation"] == {"equity": 0.0, "bonds": 0.0, "cash": 1.0}


def test_put_rejects_out_of_range_horizon(client):
    assert client.put("/assumptions", json={"horizon_years": 0}).status_code == 422
    assert client.put("/assumptions", json={"horizon_years": 200}).status_code == 422


def test_assumptions_feed_forecast(client):
    """A spending deficit should pull the median below the starting net worth."""
    # Heavy spending, no income, on a short horizon: net worth must fall.
    client.put(
        "/assumptions",
        json={
            "spending_override_monthly": "5000000",
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
    assert body["inputs"]["spending_source"] == "override"
    assert body["inputs"]["monthly_spending"] == 5000000
