"""Household profile: derived figures (services/household) + forecast wiring."""
from __future__ import annotations

import itertools
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Account, AccountType, Assumptions, Transaction
from app.seeds.defaults import seed
from app.services.forecast.engine import run_forecast
from app.services.household import (
    current_allocation,
    derived_monthly_spend,
    effective_monthly_spend,
    liquid_cash_clp,
    month_offset,
    upcoming_expenses,
)

TODAY = date(2026, 10, 3)
_ids = itertools.count()


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()
    seed(s)  # categories (Salary is_income) + the household row
    yield s
    s.close()


def _acct(db) -> Account:
    a = Account(name="Bank", country="CL", type=AccountType.checking, native_currency="CLP",
                current_balance=Decimal("0"))
    db.add(a)
    db.flush()
    return a


def _txn(db, acct, d: date, amount: str, category="Supermarket", archived=False):
    db.add(Transaction(
        account_id=acct.id, date=d, amount=Decimal(amount), currency="CLP",
        fx_rate_to_base=Decimal("1"), category=category, raw_description="x",
        normalized_description="x", dedup_hash=f"t{next(_ids)}", archived=archived,
    ))
    db.flush()


def _household(db) -> Assumptions:
    return db.execute(select(Assumptions)).scalar_one()


# ── spending ────────────────────────────────────────────────────────────────

def test_derived_spend_averages_last_six_complete_months(db):
    a = _acct(db)
    # Eight complete months Feb–Sep at 100..800, plus a huge running month.
    for i, m in enumerate(range(2, 10)):
        _txn(db, a, date(2026, m, 15), f"-{(i + 1) * 100}")
    _txn(db, a, date(2026, 10, 1), "-99999")

    d = derived_monthly_spend(db, TODAY)
    assert d.months == ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
    assert d.monthly_clp == Decimal("550")  # mean of 300..800


def test_derived_spend_follows_dashboard_rules(db):
    a = _acct(db)
    _txn(db, a, date(2026, 9, 1), "-1000")
    _txn(db, a, date(2026, 9, 2), "250")  # refund nets against spend
    _txn(db, a, date(2026, 9, 3), "-500", archived=True)  # archived: ignored
    _txn(db, a, date(2026, 9, 28), "3000", category="Salary")  # income category
    assert derived_monthly_spend(db, TODAY).monthly_clp == Decimal("750")


def test_override_wins_and_none_without_data(db):
    h = _household(db)
    assert effective_monthly_spend(db, h, TODAY).source == "none"

    a = _acct(db)
    _txn(db, a, date(2026, 9, 1), "-1000")
    eff = effective_monthly_spend(db, h, TODAY)
    assert (eff.source, eff.monthly_clp) == ("derived", Decimal("1000"))

    h.spending_override_monthly = Decimal("4200")
    h.spending_override_currency = "CLP"
    eff = effective_monthly_spend(db, h, TODAY)
    assert (eff.source, eff.monthly_clp) == ("override", Decimal("4200"))
    assert eff.derived.monthly_clp == Decimal("1000")  # still reported alongside


# ── net worth shapes ────────────────────────────────────────────────────────

def _nw(**classes: str) -> dict:
    return {"by_asset_class": [{"asset_class": k, "total_in_base": v} for k, v in classes.items()]}


def test_current_allocation_maps_classes_and_ignores_debt():
    alloc = current_allocation(_nw(cash="200", equity="300", crypto="100", bond="400", debt="-500"))
    assert alloc == pytest.approx({"equity": 0.4, "bonds": 0.4, "cash": 0.2})


def test_current_allocation_unknown_class_is_equity_and_empty_is_cash():
    assert current_allocation(_nw(real_estate="100"))["equity"] == 1.0
    assert current_allocation(_nw()) == {"equity": 0.0, "bonds": 0.0, "cash": 1.0}


def test_liquid_cash():
    assert liquid_cash_clp(_nw(cash="1234", debt="-50")) == Decimal("1234")
    assert liquid_cash_clp(_nw(cash="-10")) == Decimal("0")
    assert liquid_cash_clp(_nw(equity="10")) == Decimal("0")


# ── planned expenses ────────────────────────────────────────────────────────

def test_month_offset():
    assert month_offset("2026-10", TODAY) == 0
    assert month_offset("2027-01", TODAY) == 3
    assert month_offset("2026-09", TODAY) == -1


def test_upcoming_expenses_skip_past_months(db):
    h = _household(db)
    h.planned_expenses = [
        {"label": "old", "amount": "1", "currency": "CLP", "month": "2026-09"},
        {"label": "now", "amount": "2", "currency": "CLP", "month": "2026-10"},
        {"label": "later", "amount": "3", "currency": "CLP", "month": "2027-01"},
    ]
    got = upcoming_expenses(db, h, TODAY)
    assert [(e["label"], e["months_away"], e["amount_clp"]) for e in got] == [
        ("now", 0, Decimal("2")), ("later", 3, Decimal("3")),
    ]


def test_forecast_draws_down_planned_expense_in_its_month(db):
    h = _household(db)
    h.income_noise_sigma = Decimal("0")
    h.correlation_rho = Decimal("0")
    h.spending_override_monthly = Decimal("0")
    h.return_assumptions = {"cash": 0.0}
    h.horizon_years = 1
    today = date.today()
    in_three = f"{(today.year * 12 + today.month - 1 + 3) // 12:04d}-{(today.month - 1 + 3) % 12 + 1:02d}"
    h.planned_expenses = [{"label": "car", "amount": "1000", "currency": "CLP", "month": in_three}]
    db.commit()

    r = run_forecast(db, overrides={"real": False}, n_paths=50, seed=1,
                     returns_mode="deterministic", allocation={"cash": 1.0})
    p50 = [b["p50"] for b in r["bands"]]
    # Flat at 0 until the step covering that month, then −1000 for good.
    assert p50[3] == 0 and p50[4] == -1000 and p50[-1] == -1000
    assert r["inputs"]["planned_expenses"] == 1
    assert r["inputs"]["spending_source"] == "override"


# ── migration ───────────────────────────────────────────────────────────────

def test_migration_up_and_down(tmp_path: Path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cwd = Path(__file__).resolve().parents[1]

    def run(*args: str) -> None:
        subprocess.run([sys.executable, "-m", "alembic", *args], cwd=cwd,
                       env={"DATABASE_URL": url, "PATH": ""}, check=True, capture_output=True)

    def cols(table: str) -> set[str]:
        eng = create_engine(url)
        try:
            return {c["name"] for c in inspect(eng).get_columns(table)}
        finally:
            eng.dispose()

    run("upgrade", "b8c9d0e1f2a3")
    assert {"spending_override_monthly", "planned_expenses"} <= cols("assumptions")
    assert "asset_allocation" not in cols("assumptions")
    assert "monthly_expenses" not in cols("investor_profiles")
    run("downgrade", "a7b8c9d0e1f2")
    assert {"spending_baseline_monthly", "asset_allocation"} <= cols("assumptions")
    assert "monthly_expenses" in cols("investor_profiles")


# ── goals ───────────────────────────────────────────────────────────────────

def _flat_household(db, start_cash: str) -> Assumptions:
    """Zero flows, zero vol, cash-only: net worth stays at the start value."""
    a = Account(name="Cash", country="CL", type=AccountType.checking, native_currency="CLP",
                current_balance=Decimal(start_cash))
    db.add(a)
    h = _household(db)
    h.income_noise_sigma = Decimal("0")
    h.correlation_rho = Decimal("0")
    h.spending_override_monthly = Decimal("0")
    h.return_assumptions = {"cash": 0.0}
    db.commit()
    return h


def _month(offset: int) -> str:
    t = date.today()
    total = t.year * 12 + t.month - 1 + offset
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def test_goal_probability_and_horizon_stretch(db):
    h = _flat_household(db, "1000")
    h.goals = [
        {"label": "reach", "amount": "1000", "currency": "CLP", "month": _month(3)},
        {"label": "miss", "amount": "1001", "currency": "CLP", "month": _month(3)},
        {"label": "far", "amount": "500", "currency": "CLP", "month": _month(14 * 12 + 2)},
        {"label": "past", "amount": "1", "currency": "CLP", "month": _month(-1)},
    ]
    db.commit()

    r = run_forecast(db, overrides={"real": False, "horizon_years": 10}, n_paths=50, seed=1,
                     returns_mode="deterministic", allocation={"cash": 1.0})
    goals = {g["label"]: g for g in r["goals"]}
    assert goals["reach"]["probability"] == 1.0
    assert goals["miss"]["probability"] == 0.0
    assert goals["reach"]["p50"] == 1000
    # 14y2m away: the 10y horizon stretches to 15y so the goal is covered.
    assert r["horizon_years"] == 15 and goals["far"]["probability"] == 1.0
    assert goals["past"]["probability"] is None and goals["past"]["months_away"] == -1


def test_goal_counts_planned_expense_before_it(db):
    """A planned expense before the goal date lowers net worth at the goal."""
    h = _flat_household(db, "1000")
    h.planned_expenses = [{"label": "car", "amount": "400", "currency": "CLP", "month": _month(1)}]
    h.goals = [{"label": "keep 800", "amount": "800", "currency": "CLP", "month": _month(6)}]
    db.commit()
    r = run_forecast(db, overrides={"real": False}, n_paths=50, seed=1,
                     returns_mode="deterministic", allocation={"cash": 1.0})
    assert r["goals"][0]["probability"] == 0.0 and r["goals"][0]["p50"] == 600
