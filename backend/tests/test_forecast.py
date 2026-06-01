"""Phase 6 forecast tests (all offline — no network).

The three spec-required checks plus an endpoint smoke test:
1. Block bootstrap preserves the empirical mean/vol of the source series.
2. The correlation-shock mask fires on ~the bottom decile of months.
3. Deterministic mode (σ=0, ρ=0, zero vol) reproduces a hand-computed
   compound-growth path.
"""
from __future__ import annotations

from decimal import Decimal

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_session
from app.main import app
from app.models import Account, Assumptions
from app.models.accounts import AccountType
from app.seeds.defaults import seed
from app.services.forecast.blocks import BlockBootstrap, shock_mask
from app.services.forecast.engine import run_forecast


@pytest.fixture
def session():
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
        yield s


# --- 1. Block bootstrap preserves moments ------------------------------------
def test_block_bootstrap_preserves_moments():
    rng = np.random.default_rng(42)
    # Synthetic monthly returns with a known mean/vol, one asset class.
    true_mean, true_vol = 0.008, 0.04
    history = rng.normal(true_mean, true_vol, size=(600, 1))

    boot = BlockBootstrap(history, block_len=6)
    sampled = boot.sample(n_paths=2000, n_months=120, rng=rng)

    assert sampled.shape == (2000, 120, 1)
    assert abs(sampled.mean() - history.mean()) < 0.002
    assert abs(sampled.std() - history.std()) < 0.004


def test_block_bootstrap_preserves_cross_asset_correlation():
    rng = np.random.default_rng(7)
    base = rng.normal(0.0, 0.04, size=600)
    # Second asset is strongly correlated with the first by construction.
    second = 0.8 * base + 0.2 * rng.normal(0.0, 0.04, size=600)
    history = np.column_stack([base, second])

    sampled = BlockBootstrap(history, block_len=6).sample(1000, 120, rng)
    flat = sampled.reshape(-1, 2)
    emp_corr = np.corrcoef(flat[:, 0], flat[:, 1])[0, 1]
    src_corr = np.corrcoef(history[:, 0], history[:, 1])[0, 1]
    assert abs(emp_corr - src_corr) < 0.05


# --- 2. Correlation shock fires in the bottom decile -------------------------
def test_shock_mask_fires_in_bottom_decile():
    rng = np.random.default_rng(123)
    port = rng.normal(0.005, 0.04, size=(5000, 60))
    mask = shock_mask(port, decile=0.10)
    fired = mask.mean()
    assert 0.09 < fired < 0.11
    # Everything that fires must be below everything that doesn't.
    assert port[mask].max() <= port[~mask].min()


# --- 3. Deterministic mode == compound growth --------------------------------
def test_deterministic_matches_compound_growth(session):
    a = session.execute(select(Assumptions).limit(1)).scalar_one()
    # Zero out all stochasticity and flows so NW is pure compounding.
    a.income_user1 = Decimal("0")
    a.income_user2 = Decimal("0")
    a.spending_baseline_monthly = Decimal("0")
    a.income_noise_sigma = Decimal("0")
    a.correlation_rho = Decimal("0")
    a.fx_drift_annual = Decimal("0")
    a.asset_allocation = {"equity": 1.0}
    a.return_assumptions = {"equity": 0.06}
    a.horizon_years = 10
    session.commit()

    result = run_forecast(
        session,
        overrides={"real": False},  # nominal — compare against nominal compounding
        n_paths=200,
        seed=1,
        returns_mode="deterministic",
    )

    start = result["start_networth"]
    monthly = (1.0 + 0.06) ** (1 / 12)
    bands = result["bands"]
    # All percentiles collapse to the same deterministic path.
    for b in bands:
        expected = start * monthly ** b["month"]
        assert b["p10"] == pytest.approx(b["p90"], rel=1e-9)
        assert b["p50"] == pytest.approx(expected, rel=1e-6)


# --- Endpoint smoke test ------------------------------------------------------
@pytest.fixture
def client(monkeypatch):
    # Force the offline/parametric returns path so the endpoint test never hits
    # the network (and stays deterministic regardless of yfinance availability).
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
        # Give the household a starting balance so NW != 0.
        s.add(Account(name="Cash", country="CL", type=AccountType.checking,
                      native_currency="CLP", current_balance=Decimal("10000000")))
        s.commit()

    def override():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_forecast_endpoint_returns_bands(client):
    r = client.post(
        "/forecast/run",
        json={"horizon_years": 5, "real": True, "target": 20000000,
              "n_paths": 500, "seed": 1},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["currency"] == "CLP"
    assert body["horizon_years"] == 5
    assert len(body["bands"]) == 5 * 12 + 1
    assert body["bands"][0]["month"] == 0
    assert 0.0 <= body["prob_hit_target"] <= 1.0
    # Bands should be ordered p10 <= p50 <= p90 at the terminal month.
    last = body["bands"][-1]
    assert last["p10"] <= last["p50"] <= last["p90"]
