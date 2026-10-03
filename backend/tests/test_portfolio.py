"""Portfolio checks: risk answers -> target policy, and today's mix against it."""
from __future__ import annotations

import subprocess
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_session
from app.main import app
from app.models import Account, AccountType, Assumptions, Holding
from app.seeds.defaults import seed
from app.services.portfolio import RiskAnswers, derive_policy, mix_check
from app.services.portfolio import config as C


def answers(**kw) -> RiskAnswers:
    base = {"time_horizon": "7_15y", "risk_tolerance": "high", "risk_capacity": "high",
            "loss_reaction": "hold_uncomfortable"}
    base.update(kw)
    return RiskAnswers(**base)


# ── policy ──────────────────────────────────────────────────────────────────

def test_takes_lower_of_tolerance_and_capacity():
    p = derive_policy(answers(risk_tolerance="very_high", risk_capacity="moderate"))
    assert p.risk_profile == "moderate"
    assert [n.code for n in p.notes] == ["tolerance_capacity_conflict"]


def test_short_horizon_caps_to_conservative():
    p = derive_policy(answers(time_horizon="1_3y"))
    assert p.risk_profile == "conservative"
    assert any(n.code == "horizon_cap" for n in p.notes)


def test_short_horizon_very_high_capacity_allows_moderate_unless_expense_soon():
    a = answers(time_horizon="1_3y", risk_tolerance="very_high", risk_capacity="very_high")
    assert derive_policy(a).risk_profile == "moderate"
    soon = answers(time_horizon="1_3y", risk_tolerance="very_high", risk_capacity="very_high",
                   planned_expenses=[{"amount": 1000, "months_away": 6}])
    assert derive_policy(soon).risk_profile == "conservative"


def test_selling_after_a_drop_caps_to_moderate():
    p = derive_policy(answers(risk_tolerance="very_high", risk_capacity="very_high",
                              loss_reaction="sell_after_10"))
    assert p.risk_profile == "moderate"
    assert any(n.code == "loss_reaction_cap" for n in p.notes)


@pytest.mark.parametrize("profile", C.RISK_PROFILES)
def test_targets_are_range_midpoints(profile):
    scale = {v: k for k, v in C.RISK_SCALE_TO_PROFILE.items()}[profile]
    p = derive_policy(answers(time_horizon="gt_15y", risk_tolerance=scale, risk_capacity=scale,
                              loss_reaction="invest_more"))
    assert p.risk_profile == profile
    for bucket, (lo, hi) in C.ALLOCATION_RANGES[profile].items():
        assert p.target_allocation[bucket] == (lo + hi) / 2


# ── mix ─────────────────────────────────────────────────────────────────────

def networth(cash: str, holdings: list[tuple[str, str]], debt: str = "0") -> dict:
    return {
        "by_asset_class": [
            {"asset_class": "cash", "total_in_base": cash},
            {"asset_class": "debt", "total_in_base": debt},
        ],
        "holdings": [{"asset_class": cls, "value_in_base": v} for cls, v in holdings],
    }


def test_mix_against_growth_ranges():
    policy = derive_policy(answers())  # growth: cash 3–10, bonds 10–30, equities 60–85
    m = mix_check(networth("50", [("equity", "900"), ("bond", "50")], debt="-500"), policy)
    rows = {b.bucket: b for b in m.buckets}
    assert m.total_base == Decimal("1000")  # debt excluded
    assert (rows["global_equities"].current_pct, rows["global_equities"].status) == (90.0, "above")
    assert (rows["bonds"].current_pct, rows["bonds"].status) == (5.0, "below")
    assert rows["cash"].status == "in"
    assert rows["cash"].drift_pp == 5.0 - policy.target_allocation["cash"]
    assert m.out_of_range == 2
    # Empty buckets with a zero minimum (alternatives, crypto) aren't listed.
    assert "crypto" not in rows and "alternatives" not in rows


def test_mix_drift_inside_range_and_unclassified():
    policy = derive_policy(answers())
    # Equities 61% is in range (60–85) but 11.5pp under the 72.5 midpoint.
    m = mix_check(networth("70", [("equity", "610"), ("bond", "300"), ("mystery", "20")]), policy)
    rows = {b.bucket: b for b in m.buckets}
    assert rows["global_equities"].status == "in"
    assert rows["global_equities"].drifting and rows["global_equities"].drift_pp == -11.5
    assert m.drifting >= 1
    assert rows["unclassified"].target_pct is None and rows["unclassified"].current_pct == 2.0


def test_cash_holdings_are_not_double_counted():
    policy = derive_policy(answers())
    # by_asset_class["cash"] already includes cash-class holdings.
    m = mix_check(networth("100", [("cash", "100"), ("equity", "900")]), policy)
    assert m.total_base == Decimal("1000")


def test_empty_portfolio():
    m = mix_check(networth("0", []), derive_policy(answers()))
    assert m.total_base == 0 and all(b.current_pct == 0 for b in m.buckets)


# ── endpoints ───────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    from app.services.prices import valuation as valuation_mod
    from app.services.prices.provider import PriceLookupError

    class _Offline:
        def fetch(self, ticker):
            raise PriceLookupError(f"offline: {ticker}")

    monkeypatch.setattr(valuation_mod, "get_provider", lambda: _Offline())
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with Session() as s:
        seed(s)
        acc = Account(name="Bank", country="CL", type=AccountType.checking, native_currency="CLP",
                      current_balance=Decimal("100000"))
        s.add(acc)
        s.flush()
        s.add(Holding(account_id=acc.id, ticker="EQ", quantity=Decimal("1"), price_currency="CLP",
                      asset_class="equity", manual_price=Decimal("700000")))
        s.add(Holding(account_id=acc.id, ticker="BD", quantity=Decimal("1"), price_currency="CLP",
                      asset_class="bond", manual_price=Decimal("200000")))
        s.commit()

    def override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override
    yield TestClient(app), Session
    app.dependency_overrides.pop(get_session, None)


def test_checks_without_answers(client):
    cl, _ = client
    assert cl.get("/portfolio/checks").json() == {"profile": None, "policy": None, "mix": None}
    assert cl.get("/portfolio/risk-profile").json() == {"profile": None}


def test_save_answers_then_check(client):
    cl, _ = client
    body = {"time_horizon": "gt_15y", "risk_tolerance": "high", "risk_capacity": "high",
            "loss_reaction": "invest_more"}
    r = cl.put("/portfolio/risk-profile", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["policy"]["risk_profile"] == "growth"
    assert cl.put("/portfolio/risk-profile", json={**body, "time_horizon": "soon"}).status_code == 422

    checks = cl.get("/portfolio/checks").json()
    rows = {b["bucket"]: b for b in checks["mix"]["buckets"]}
    assert Decimal(checks["mix"]["total"]) == Decimal("1000000")
    assert (rows["global_equities"]["current_pct"], rows["global_equities"]["status"]) == (70.0, "in")
    assert (rows["bonds"]["current_pct"], rows["cash"]["current_pct"]) == (20.0, 10.0)


def test_near_term_planned_expense_feeds_the_horizon_cap(client):
    cl, Session = client
    with Session() as s:
        soon = (date.today().replace(day=1) + timedelta(days=40)).strftime("%Y-%m")
        s.query(Assumptions).one().planned_expenses = [
            {"label": "car", "amount": "1000000", "currency": "CLP", "month": soon},
        ]
        s.commit()
    body = {"time_horizon": "1_3y", "risk_tolerance": "very_high", "risk_capacity": "very_high",
            "loss_reaction": "invest_more"}
    assert cl.put("/portfolio/risk-profile", json=body).json()["policy"]["risk_profile"] == "conservative"


# ── migration ───────────────────────────────────────────────────────────────

def test_migration_up_and_down(tmp_path: Path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cwd = Path(__file__).resolve().parents[1]

    def run(*args: str) -> None:
        subprocess.run([sys.executable, "-m", "alembic", *args], cwd=cwd,
                       env={"DATABASE_URL": url, "PATH": ""}, check=True, capture_output=True)

    def tables() -> set[str]:
        eng = create_engine(url)
        try:
            return set(inspect(eng).get_table_names())
        finally:
            eng.dispose()

    run("upgrade", "c9d0e1f2a3b4")
    assert "risk_profiles" in tables()
    assert not tables() & {"investor_profiles", "portfolio_health_reviews", "security_metadata"}
    run("downgrade", "b8c9d0e1f2a3")
    assert {"investor_profiles", "portfolio_health_reviews", "portfolio_findings",
            "investment_policy_profiles", "security_metadata"} <= tables()
