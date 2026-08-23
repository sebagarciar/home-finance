"""Portfolio Health Review — Stage 1 + 2 tests.

Covers the deterministic core (policy mapping, allocation/concentration findings,
scoring + explainability, determinism) plus the profile-incomplete guardrail and
the full review endpoint. The engine functions are pure, so most tests exercise
them directly without a DB.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.db import Base, get_session
from app.main import app
from app.models import Account, Holding
from app.models.accounts import AccountType
from app.services.portfolio_health import scoring
from app.services.portfolio_health.engine import run_review
from app.services.portfolio_health.policy import ProfileData, derive_policy
from app.services.portfolio_health.stress import run_stress


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #
def make_profile(**overrides) -> ProfileData:
    base = {
        "primary_goal": "long_term_growth",
        "time_horizon": "7_15y",
        "risk_tolerance": "high",
        "risk_capacity": "high",
        "loss_reaction": "hold_uncomfortable",
        "income_stability": "stable",
        "investment_knowledge": "intermediate",
        "monthly_income": 3000.0,
        "monthly_expenses": 2000.0,
        "emergency_fund_amount": 10000.0,
        "expected_large_expenses": [],
        "constraints": {},
        "base_currency": "CLP",
        "tax_residence": "CL",
    }
    base.update(overrides)
    return ProfileData(**base)


def make_snapshot(holdings: list[dict], cash: str = "0") -> dict:
    """Minimal current_networth() shape the engine reads."""
    by_asset_class = [{"asset_class": "cash", "total_in_base": cash}]
    return {
        "currency": "CLP",
        "by_asset_class": by_asset_class,
        "by_currency": [],
        "holdings": holdings,
    }


def holding(hid, ticker, asset_class, value, *, currency="CLP", missing=False) -> dict:
    return {
        "holding_id": hid,
        "ticker": ticker,
        "asset_class": asset_class,
        "price_currency": currency,
        "value_in_base": value,
        "missing_price": missing,
    }


# --------------------------------------------------------------------------- #
# Policy mapping
# --------------------------------------------------------------------------- #
def test_policy_takes_lower_of_tolerance_and_capacity():
    p = make_profile(risk_tolerance="very_high", risk_capacity="low")
    policy = derive_policy(p)
    assert policy.risk_profile == "conservative"
    codes = {n.code for n in policy.notes}
    assert "tolerance_capacity_conflict" in codes


def test_short_horizon_caps_to_conservative():
    p = make_profile(time_horizon="1_3y", risk_tolerance="high", risk_capacity="high")
    policy = derive_policy(p)
    assert policy.risk_profile == "conservative"
    assert any(n.code == "horizon_cap" for n in policy.notes)


def test_short_horizon_very_high_capacity_allows_moderate():
    p = make_profile(
        time_horizon="1_3y", risk_tolerance="very_high", risk_capacity="very_high",
        expected_large_expenses=[],
    )
    policy = derive_policy(p)
    assert policy.risk_profile == "moderate"


def test_panic_sell_caps_to_moderate():
    p = make_profile(risk_tolerance="high", risk_capacity="very_high", loss_reaction="sell_after_10")
    policy = derive_policy(p)
    assert policy.risk_profile == "moderate"
    assert any(n.code == "loss_reaction_cap" for n in policy.notes)


def test_allocation_ranges_match_profile():
    policy = derive_policy(make_profile(risk_tolerance="moderate", risk_capacity="moderate"))
    assert policy.risk_profile == "moderate"
    assert policy.allocation_ranges["global_equities"] == [40, 65]
    # target midpoint
    assert policy.target_allocation["global_equities"] == 52.5


def test_variable_income_raises_emergency_fund_target():
    stable = derive_policy(make_profile(income_stability="stable"))
    variable = derive_policy(make_profile(income_stability="variable"))
    assert variable.emergency_fund_target_months > stable.emergency_fund_target_months
    assert variable.emergency_fund_target_months == 6.0


def test_near_term_large_expense_raises_liquidity_target():
    p = make_profile(expected_large_expenses=[{"label": "car", "amount": 20000, "currency": "EUR", "months_away": 12}])
    policy = derive_policy(p)
    assert any(n.code == "liquidity_target_raised" for n in policy.notes)
    assert policy.emergency_fund_target_months == 6.0  # base 3 + large-expense 3


def test_constraint_tightens_crypto_cap():
    p = make_profile(risk_tolerance="very_high", risk_capacity="very_high", constraints={"max_crypto_pct": 1})
    policy = derive_policy(p)
    assert policy.risk_profile == "aggressive"
    assert policy.max_crypto_pct == 1  # tighter than the aggressive default of 10


# --------------------------------------------------------------------------- #
# Allocation findings
# --------------------------------------------------------------------------- #
def test_equity_above_range_high_severity():
    policy = derive_policy(make_profile(risk_tolerance="moderate", risk_capacity="moderate"))
    # 85% equities, 15% cash; moderate equity range 40-65 -> 20pp over -> high
    snap = make_snapshot([holding(1, "VT", "etf", "850000")], cash="150000")
    result = run_review(make_profile(risk_tolerance="moderate", risk_capacity="moderate"), policy, snap)
    alloc = [f for f in result.findings if f.fid == "asset_allocation.above_range"]
    assert alloc, "expected an above-range allocation finding"
    f = alloc[0]
    assert f.severity == "high"
    assert f.evidence["currentAllocationPercent"] == 85.0
    assert f.evidence["targetRangePercent"] == [40, 65]


def test_in_range_allocation_no_finding():
    policy = derive_policy(make_profile(risk_tolerance="moderate", risk_capacity="moderate"))
    # 50% equities / 50% cash — equities in 40-65; cash above 5-15 though
    snap = make_snapshot([holding(1, "VT", "etf", "500000")], cash="500000")
    result = run_review(make_profile(risk_tolerance="moderate", risk_capacity="moderate"), policy, snap)
    assert not [f for f in result.findings if f.fid == "asset_allocation.above_range" and f.evidence["bucket"] == "global_equities"]


# --------------------------------------------------------------------------- #
# Concentration findings
# --------------------------------------------------------------------------- #
def test_single_stock_concentration_flagged():
    policy = derive_policy(make_profile())
    # One stock = 50% of portfolio (limit 10, >2x -> high)
    snap = make_snapshot(
        [holding(1, "AAPL", "equity", "500000"), holding(2, "VT", "etf", "500000")],
    )
    result = run_review(make_profile(), policy, snap)
    fids = {f.fid for f in result.findings}
    assert "concentration.single_holding" in fids
    assert "concentration.single_stock" in fids
    stock = next(f for f in result.findings if f.fid == "concentration.single_stock")
    assert stock.evidence["ticker"] == "AAPL"
    assert stock.severity == "high"


def test_crypto_over_limit_high_severity():
    policy = derive_policy(make_profile(risk_tolerance="moderate", risk_capacity="moderate"))
    # 12% crypto, moderate cap 5
    snap = make_snapshot(
        [holding(1, "BTC", "crypto", "120000"), holding(2, "VT", "etf", "880000")],
    )
    result = run_review(make_profile(risk_tolerance="moderate", risk_capacity="moderate"), policy, snap)
    crypto = [f for f in result.findings if f.fid == "concentration.crypto"]
    assert crypto and crypto[0].severity == "high"
    assert crypto[0].evidence["limitPercent"] == 5


def test_employer_stock_concentration():
    policy = derive_policy(make_profile(constraints={"employer_stock_ticker": "ACME"}))
    snap = make_snapshot(
        [holding(1, "ACME", "equity", "200000"), holding(2, "VT", "etf", "800000")],
    )
    result = run_review(make_profile(constraints={"employer_stock_ticker": "ACME"}), policy, snap)
    emp = [f for f in result.findings if f.fid == "concentration.employer_stock"]
    assert emp and emp[0].evidence["ticker"] == "ACME"


# --------------------------------------------------------------------------- #
# Data quality
# --------------------------------------------------------------------------- #
def test_unknown_asset_class_creates_data_quality_finding():
    policy = derive_policy(make_profile())
    snap = make_snapshot([holding(1, "???", "mystery", "100000"), holding(2, "VT", "etf", "900000")])
    result = run_review(make_profile(), policy, snap)
    assert any(f.fid == "data_quality.unknown_asset_class" for f in result.findings)


def test_high_unknown_fraction_caps_data_quality_score():
    policy = derive_policy(make_profile())
    # 60% of value is unclassified -> flag + score cap
    snap = make_snapshot([holding(1, "???", "mystery", "600000"), holding(2, "VT", "etf", "400000")])
    result = run_review(make_profile(), policy, snap)
    assert result.flags["data_quality_capped"] is True
    sc = scoring.score(result.findings, result.flags)
    assert sc["sub_scores"]["dataQualityScore"] <= 50.0


def test_missing_price_finding():
    policy = derive_policy(make_profile())
    snap = make_snapshot([holding(1, "VT", "etf", "0", missing=True)])
    result = run_review(make_profile(), policy, snap)
    assert any(f.fid == "data_quality.missing_price" for f in result.findings)


# --------------------------------------------------------------------------- #
# Scoring + explainability + determinism
# --------------------------------------------------------------------------- #
def test_score_is_explainable():
    policy = derive_policy(make_profile(risk_tolerance="moderate", risk_capacity="moderate"))
    snap = make_snapshot([holding(1, "AAPL", "equity", "900000")], cash="100000")
    result = run_review(make_profile(risk_tolerance="moderate", risk_capacity="moderate"), policy, snap)
    sc = scoring.score(result.findings, result.flags)
    # Every penalty references a finding id present in the findings list.
    finding_ids = {f.fid for f in result.findings}
    for _sub, entries in sc["score_explanation"].items():
        for e in entries:
            assert e["finding_id"] in finding_ids or "cap" in e
    assert 0 <= sc["overall"] <= 100


def test_determinism_same_input_same_findings():
    profile = make_profile(risk_tolerance="moderate", risk_capacity="moderate")
    policy = derive_policy(profile)
    snap = make_snapshot(
        [holding(1, "AAPL", "equity", "500000"), holding(2, "BTC", "crypto", "200000"),
         holding(3, "VT", "etf", "300000")],
        cash="100000",
    )
    r1 = run_review(profile, policy, snap)
    r2 = run_review(profile, policy, snap)
    assert r1.findings_as_dicts() == r2.findings_as_dicts()
    assert r1.diagnostics == r2.diagnostics


def test_overall_status_labels():
    assert scoring.overall_status(95, []) == "Looks aligned"
    assert scoring.overall_status(75, []) == "Monitor"


# --------------------------------------------------------------------------- #
# Endpoints
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

    def override_session():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = lambda: "test"
    yield TestClient(app), TestingSession
    app.dependency_overrides.clear()


_PROFILE_PAYLOAD = {
    "primary_goal": "retirement",
    "time_horizon": "7_15y",
    "risk_tolerance": "moderate",
    "risk_capacity": "moderate",
    "loss_reaction": "hold_uncomfortable",
    "monthly_income": "3000",
    "monthly_income_currency": "CLP",
    "monthly_expenses": "2000",
    "monthly_expenses_currency": "CLP",
    "emergency_fund_amount": "10000",
    "income_stability": "stable",
    "investment_knowledge": "intermediate",
    "tax_residence": "CL",
    "base_currency": "CLP",
    "constraints": {},
}


def _seed_clp_portfolio(session_factory):
    """A CLP-only portfolio so net-worth needs no FX provider (CLP->CLP = 1)."""
    s = session_factory()
    acc = Account(name="Cash", country="CL", type=AccountType.checking, native_currency="CLP",
                  current_balance=Decimal("500000"))
    s.add(acc)
    s.commit()
    s.refresh(acc)
    # AAPL = 50% of a 1,000,000 portfolio -> concentration + allocation findings
    s.add(Holding(account_id=acc.id, ticker="AAPL", quantity=Decimal("50"),
                  price_currency="CLP", asset_class="equity", manual_price=Decimal("10000")))
    s.commit()
    s.close()


def test_review_guardrail_without_profile(client):
    cl, _ = client
    r = cl.post("/portfolio-health/review")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["profile_incomplete"] is True
    assert "factual_summary" in body
    assert "overall_score" not in body


def test_put_profile_then_review(client, monkeypatch):
    cl, session_factory = client
    # Force the manual-price fallback so valuation is offline + deterministic.
    from app.services.prices import valuation as valuation_mod
    from app.services.prices.provider import PriceLookupError

    class _DeadProvider:
        def fetch(self, ticker):
            raise PriceLookupError(f"offline: {ticker}")

    monkeypatch.setattr(valuation_mod, "get_provider", lambda: _DeadProvider())
    _seed_clp_portfolio(session_factory)

    r = cl.put("/portfolio-health/profile", json=_PROFILE_PAYLOAD)
    assert r.status_code == 200, r.text
    assert r.json()["policy"]["risk_profile"] == "moderate"

    g = cl.get("/portfolio-health/profile")
    assert g.json()["profile"]["primary_goal"] == "retirement"

    rv = cl.post("/portfolio-health/review")
    assert rv.status_code == 200, rv.text
    review = rv.json()
    assert review["profile_incomplete"] is False
    assert 0 <= review["overall_score"] <= 100
    assert set(review["sub_scores"]) >= {
        "goalAlignmentScore", "riskAlignmentScore", "diversificationScore",
        "liquidityScore", "costEfficiencyScore", "dataQualityScore",
    }
    assert review["rules_engine_version"]
    # AAPL at 50% should produce a single-stock concentration finding.
    assert any(f["category"] == "concentration" for f in review["findings"])

    latest = cl.get("/portfolio-health/review/latest").json()["review"]
    assert latest["id"] == review["id"]
    hist = cl.get("/portfolio-health/reviews").json()
    assert len(hist) == 1


def test_review_reports_fx_failure_in_missing_data(client, monkeypatch):
    """An unconvertible profile amount degrades to 0 but must surface in
    missing_data instead of silently changing the liquidity diagnostics."""
    cl, session_factory = client
    from app.services.prices import valuation as valuation_mod
    from app.services.prices.provider import PriceLookupError

    class _DeadProvider:
        def fetch(self, ticker):
            raise PriceLookupError(f"offline: {ticker}")

    monkeypatch.setattr(valuation_mod, "get_provider", lambda: _DeadProvider())
    _seed_clp_portfolio(session_factory)

    payload = {**_PROFILE_PAYLOAD, "monthly_expenses_currency": "EUR"}
    assert cl.put("/portfolio-health/profile", json=payload).status_code == 200

    import app.routers.portfolio_health as ph_router

    def _fx_down(db, amount, currency, provider=None):
        if currency == "CLP":
            return Decimal(str(amount))
        raise LookupError(f"no rate for {currency}")

    monkeypatch.setattr(ph_router, "to_base_current", _fx_down)

    review = cl.post("/portfolio-health/review").json()
    assert any("monthly_expenses" in note for note in review["missing_data"])
    # The engine saw 0 expenses -> liquidity diagnostics marked unavailable.
    assert review["diagnostics"]["liquidity"]["data_available"] is False


def test_review_repersists_policy_when_derivation_drifts(client, monkeypatch):
    """If the stored policy row no longer matches derive_policy's output (the
    derivation logic changed), the review writes a new version so the policy it
    displays is the one the engine ran on."""
    cl, session_factory = client
    from app.services.prices import valuation as valuation_mod
    from app.services.prices.provider import PriceLookupError

    class _DeadProvider:
        def fetch(self, ticker):
            raise PriceLookupError(f"offline: {ticker}")

    monkeypatch.setattr(valuation_mod, "get_provider", lambda: _DeadProvider())
    _seed_clp_portfolio(session_factory)

    r = cl.put("/portfolio-health/profile", json=_PROFILE_PAYLOAD)
    assert r.json()["policy"]["version"] == 1

    # Simulate a derive_policy change since the row was written.
    from app.models import InvestmentPolicyProfile

    s = session_factory()
    row = s.query(InvestmentPolicyProfile).one()
    row.risk_profile = "aggressive"
    s.commit()
    s.close()

    review = cl.post("/portfolio-health/review").json()
    policy = review["diagnostics"]["policy"]
    assert policy["risk_profile"] == "moderate"  # re-derived, not the stale row
    assert policy["version"] == 2

    # An unchanged derivation does NOT spawn another version.
    review2 = cl.post("/portfolio-health/review").json()
    assert review2["diagnostics"]["policy"]["version"] == 2


# --------------------------------------------------------------------------- #
# Stage 2: Liquidity
# --------------------------------------------------------------------------- #
def test_emergency_fund_critical_when_cash_under_one_month():
    """Cash < 1 month of expenses → high-severity liquidity finding."""
    policy = derive_policy(make_profile(income_stability="stable"))
    snap = make_snapshot([holding(1, "VT", "etf", "900000")], cash="500")
    # monthly expenses = 2000, cash = 500 → 0.25 months
    result = run_review(make_profile(), policy, snap, avg_monthly_expenses_clp=2000.0)
    critical = [f for f in result.findings if f.fid == "liquidity.emergency_fund_critical"]
    assert critical, "expected a critical liquidity finding"
    assert critical[0].severity == "high"
    assert critical[0].evidence["efMonthsCurrent"] < 1.0


def test_emergency_fund_below_target():
    """Cash = 1.5 months, target = 3 → medium finding."""
    policy = derive_policy(make_profile(income_stability="stable"))
    snap = make_snapshot([holding(1, "VT", "etf", "900000")], cash="3000")
    # monthly expenses = 2000, cash = 3000 → 1.5 months, target = 3
    result = run_review(make_profile(), policy, snap, avg_monthly_expenses_clp=2000.0)
    below = [f for f in result.findings if f.fid == "liquidity.emergency_fund_below_target"]
    assert below
    assert below[0].severity == "medium"
    assert below[0].evidence["efMonthsTarget"] == 3.0


def test_no_liquidity_finding_when_ef_sufficient():
    """Cash = 5 months, target = 3 → no liquidity finding."""
    policy = derive_policy(make_profile(income_stability="stable"))
    snap = make_snapshot([holding(1, "VT", "etf", "900000")], cash="10000")
    result = run_review(make_profile(), policy, snap, avg_monthly_expenses_clp=2000.0)
    liq = [f for f in result.findings if f.category == "liquidity"]
    assert not liq


def test_no_liquidity_finding_when_no_expense_data():
    """No expenses provided → no liquidity finding (can't evaluate)."""
    policy = derive_policy(make_profile())
    snap = make_snapshot([holding(1, "VT", "etf", "900000")], cash="100")
    result = run_review(make_profile(), policy, snap, avg_monthly_expenses_clp=0.0)
    liq = [f for f in result.findings if f.category == "liquidity"]
    assert not liq


def test_large_expense_gap_finding():
    """Cash < sum of near-term large expenses → liquidity gap finding."""
    policy = derive_policy(make_profile())
    snap = make_snapshot([holding(1, "VT", "etf", "900000")], cash="5000")
    large = [{"label": "car", "amount_clp": 20000.0, "months_away": 12}]
    result = run_review(
        make_profile(), policy, snap,
        avg_monthly_expenses_clp=2000.0,
        large_expenses_clp=large,
    )
    gap = [f for f in result.findings if f.fid == "liquidity.large_expense_gap"]
    assert gap


def test_variable_income_raises_ef_target_and_finding():
    """Variable income raises the EF target → more likely to trip the below-target finding."""
    stable_policy = derive_policy(make_profile(income_stability="stable"))
    variable_policy = derive_policy(make_profile(income_stability="variable"))
    assert variable_policy.emergency_fund_target_months > stable_policy.emergency_fund_target_months

    snap = make_snapshot([holding(1, "VT", "etf", "900000")], cash="8000")
    # cash = 8000, expenses = 2000 → 4 months
    # stable target = 3 (OK), variable target = 6 (below target → finding)
    stable_result = run_review(
        make_profile(income_stability="stable"), stable_policy, snap,
        avg_monthly_expenses_clp=2000.0
    )
    variable_result = run_review(
        make_profile(income_stability="variable"), variable_policy, snap,
        avg_monthly_expenses_clp=2000.0
    )
    stable_liq = [f for f in stable_result.findings if f.category == "liquidity"]
    variable_liq = [f for f in variable_result.findings if f.category == "liquidity"]
    assert not stable_liq
    assert variable_liq


# --------------------------------------------------------------------------- #
# Stage 2: Rebalancing
# --------------------------------------------------------------------------- #
def test_rebalancing_finding_for_in_range_drift():
    """A bucket within range but drifted from midpoint triggers a rebalancing finding."""
    # growth profile: bonds range [10, 30], midpoint 20; drift threshold 5
    policy = derive_policy(make_profile(risk_tolerance="high", risk_capacity="high"))
    assert policy.risk_profile == "growth"
    # bonds = 5%, within range [10-30]? No, actually 5 < 10 so it's out of range.
    # Let's put bonds at 25%, in range [10-30], midpoint 20 → drift = 5 (exactly at threshold)
    # Use equities at 65%, in range [60-85], midpoint 72.5 → drift ~ 7.5pp → rebalancing
    snap = make_snapshot(
        [
            holding(1, "AGG", "bonds", "250000"),   # 25% bonds, in [10-30]
            holding(2, "VT", "etf", "650000"),       # 65% equities, in [60-85]
        ],
        cash="100000",  # 10% cash, in [3-10] but just at top
    )
    result = run_review(
        make_profile(risk_tolerance="high", risk_capacity="high"), policy, snap
    )
    rebal = [f for f in result.findings if f.fid == "rebalancing.drift_above_threshold"]
    # equities 65% vs midpoint 72.5 → drift 7.5 > threshold 5 → finding
    assert any(f.evidence["bucket"] == "global_equities" for f in rebal)


def test_no_rebalancing_finding_for_out_of_range_bucket():
    """Out-of-range buckets don't also get a rebalancing finding (allocation finding covers it)."""
    policy = derive_policy(make_profile(risk_tolerance="moderate", risk_capacity="moderate"))
    # 85% equities, way above 40-65 range → allocation finding only, not also rebalancing
    snap = make_snapshot([holding(1, "VT", "etf", "850000")], cash="150000")
    result = run_review(make_profile(risk_tolerance="moderate", risk_capacity="moderate"), policy, snap)
    alloc_f = [f for f in result.findings if f.fid == "asset_allocation.above_range"
               and f.evidence["bucket"] == "global_equities"]
    rebal_f = [f for f in result.findings if f.fid == "rebalancing.drift_above_threshold"
               and f.evidence["bucket"] == "global_equities"]
    assert alloc_f      # allocation finding present
    assert not rebal_f  # no duplicate rebalancing finding for same bucket


# --------------------------------------------------------------------------- #
# Stage 2: Stress scenarios
# --------------------------------------------------------------------------- #
def test_stress_scenarios_in_review_result():
    """Stress scenarios are included in the review diagnostics."""
    policy = derive_policy(make_profile())
    snap = make_snapshot([holding(1, "VT", "etf", "900000")], cash="100000")
    result = run_review(make_profile(), policy, snap)
    assert "stress" in result.diagnostics
    scenarios = result.diagnostics["stress"]
    assert isinstance(scenarios, list)
    assert len(scenarios) >= 2  # equity + bonds always present
    labels = {s["scenario"] for s in scenarios}
    assert "equity_crash" in labels
    assert "bond_stress" in labels


def test_stress_equity_impact_arithmetic():
    """Equity crash: 90% portfolio in equities, -30% shock → ≈ -27% portfolio impact."""
    scenarios, _ = run_stress(
        allocation_current_pct={"global_equities": 90.0, "bonds": 0.0, "crypto": 0.0},
        portfolio_value_in_base=Decimal("1000000"),
        concentration_top1_pct=90.0,
        by_currency=[],
        risk_profile="growth",
    )
    eq = next(s for s in scenarios if s["scenario"] == "equity_crash")
    assert abs(eq["approx_impact_pct"] - (-27.0)) < 0.5  # ≈ -27%
    assert int(eq["approx_impact_base"]) == -270000


def test_stress_crypto_scenario_included_only_when_exposed():
    """Crypto scenario is emitted only when crypto_pct > 0.1."""
    _, _ = run_stress(  # no crypto
        allocation_current_pct={"global_equities": 80.0, "crypto": 0.0},
        portfolio_value_in_base=Decimal("1000000"),
        concentration_top1_pct=80.0,
        by_currency=[],
    )
    scenarios_no_crypto, _ = run_stress(
        allocation_current_pct={"global_equities": 80.0, "crypto": 0.0},
        portfolio_value_in_base=Decimal("1000000"),
        concentration_top1_pct=80.0,
        by_currency=[],
    )
    scenarios_with_crypto, _ = run_stress(
        allocation_current_pct={"global_equities": 70.0, "crypto": 10.0},
        portfolio_value_in_base=Decimal("1000000"),
        concentration_top1_pct=70.0,
        by_currency=[],
    )
    assert not any(s["scenario"] == "crypto_crash" for s in scenarios_no_crypto)
    assert any(s["scenario"] == "crypto_crash" for s in scenarios_with_crypto)


def test_drawdown_finding_when_worst_case_breaches_threshold():
    """Conservative profile (threshold -10%): 80% equities → equity crash ≈ -24% → finding."""
    # Simulate a conservative investor with lots of equities (very out of profile)
    # equity crash: 80% * -30% = -24% portfolio impact; conservative threshold = -10%
    scenarios, findings = run_stress(
        allocation_current_pct={"global_equities": 80.0, "bonds": 10.0},
        portfolio_value_in_base=Decimal("1000000"),
        concentration_top1_pct=80.0,
        by_currency=[],
        risk_profile="conservative",
    )
    assert any(f.fid == "drawdown.worst_case_exceeds_threshold" for f in findings)


def test_no_drawdown_finding_when_within_threshold():
    """Aggressive profile (threshold -40%): mild portfolio → no drawdown finding."""
    # All bonds, low equity: bond impact -0.1 * 20% = -2% → well within -40% threshold
    scenarios, findings = run_stress(
        allocation_current_pct={"global_equities": 0.0, "bonds": 20.0},
        portfolio_value_in_base=Decimal("1000000"),
        concentration_top1_pct=20.0,
        by_currency=[],
        risk_profile="aggressive",
    )
    assert not any(f.fid == "drawdown.worst_case_exceeds_threshold" for f in findings)


def test_stress_scenarios_deterministic():
    """Same input → same stress output (pure function, no randomness)."""
    kwargs = {
        "allocation_current_pct": {"global_equities": 60.0, "bonds": 20.0, "crypto": 5.0},
        "portfolio_value_in_base": Decimal("2000000"),
        "concentration_top1_pct": 30.0,
        "by_currency": [{"currency": "USD", "total_in_base": "500000"},
                        {"currency": "CLP", "total_in_base": "1500000"}],
        "risk_profile": "growth",
    }
    s1, f1 = run_stress(**kwargs)
    s2, f2 = run_stress(**kwargs)
    assert s1 == s2
    assert [f.fid for f in f1] == [f.fid for f in f2]


# --------------------------------------------------------------------------- #
# Stage 3 — Explanation provider + guardrail tests
# --------------------------------------------------------------------------- #
from app.services.portfolio_health.explanation import (
    OllamaExplanationProvider,
    ExplanationProvider,
    _passes_content_guardrail,
    _valid_finding_id,
    _template_explanation,
    _parse_sections,
    explain_review,
)


# Minimal valid review data for explanation tests
_REVIEW_DATA = {
    "primary_goal": "long_term_growth",
    "time_horizon": "7_15y",
    "risk_profile": "moderate",
    "overall_score": 72.0,
    "sub_scores": {"goalAlignmentScore": 80, "riskAlignmentScore": 70},
    "status": "Monitor",
    "findings": [
        {
            "id": "allocation.equity_above_range",
            "category": "asset_allocation",
            "severity": "medium",
            "finding": "Equity allocation is above the policy upper bound.",
            "whyItMatters": "Excess equity raises volatility beyond the policy.",
        }
    ],
    "missing_data": ["Some prices missing."],
}


def test_template_explanation_contains_required_sections():
    exp = _template_explanation(_REVIEW_DATA)
    for key in ["overall_summary", "aligned", "needs_attention", "why_it_matters",
                "what_to_review_next", "data_limitations", "professional_advice_note"]:
        assert key in exp, f"missing section: {key}"
    assert exp["generated_by"] == "template"


def test_template_explanation_is_deterministic():
    a = _template_explanation(_REVIEW_DATA)
    b = _template_explanation(_REVIEW_DATA)
    assert a == b


def test_guardrail_rejects_buy_sell_phrases():
    assert not _passes_content_guardrail("You should buy more equities.")
    assert not _passes_content_guardrail("SELL the crypto position immediately.")
    assert not _passes_content_guardrail("I predict it will go up next year.")
    assert not _passes_content_guardrail("This is tax advice for your situation.")


def test_guardrail_passes_educational_text():
    assert _passes_content_guardrail(
        "The portfolio may be over-weighted in equities relative to the policy range. "
        "Consider reviewing the allocation at the next rebalancing window."
    )


def test_guardrail_rejects_invented_finding_ids():
    known = {"allocation.equity_above_range"}
    # Invented id not in the review
    assert not _valid_finding_id("See finding suitability.invented_id for details.", known)


def test_guardrail_passes_known_finding_ids():
    known = {"allocation.equity_above_range"}
    assert _valid_finding_id(
        "The finding allocation.equity_above_range indicates an imbalance.", known
    )


def test_guardrail_passes_text_without_finding_ids():
    # No dot-separated tokens at all — must pass (no invented IDs)
    assert _valid_finding_id("The portfolio score is 72 out of 100.", set())


def test_parse_sections_returns_all_keys():
    raw = """OVERALL SUMMARY:
Good score overall.

WHAT'S WORKING:
• Goal alignment is strong.

NEEDS ATTENTION:
• Equity slightly above range.

WHY THESE MATTER:
Relevant to long-term growth.

WHAT TO REVIEW NEXT:
• Check the allocation at rebalancing.

DATA LIMITATIONS:
Some prices missing.

PROFESSIONAL ADVICE NOTE:
This is educational only.
"""
    sections = _parse_sections(raw)
    assert sections.get("overall_summary") == "Good score overall."
    assert "Goal alignment" in sections.get("aligned", "")
    assert "Equity slightly" in sections.get("needs_attention", "")


class _FakeProvider(ExplanationProvider):
    def __init__(self, response: str | None):
        self._response = response

    def generate(self, prompt: str) -> str | None:
        return self._response


def test_explain_review_uses_template_when_provider_returns_none():
    exp, ver = explain_review(_REVIEW_DATA, _FakeProvider(None))
    assert exp["generated_by"] == "template"
    assert ver is None


def test_explain_review_uses_template_when_provider_returns_forbidden_phrase():
    bad_response = """OVERALL SUMMARY:
You should buy more equities immediately.

WHAT'S WORKING:
Nothing.

NEEDS ATTENTION:
Sell your bonds.

WHY THESE MATTER:
Returns will go up.

WHAT TO REVIEW NEXT:
Buy index funds.

DATA LIMITATIONS:
None.

PROFESSIONAL ADVICE NOTE:
Not advice.
"""
    exp, ver = explain_review(_REVIEW_DATA, _FakeProvider(bad_response))
    assert exp["generated_by"] == "template"
    assert ver is None


def test_explain_review_uses_template_when_provider_invents_finding():
    invented_id_response = """OVERALL SUMMARY:
Looks okay.

WHAT'S WORKING:
• allocation.invented_finding_xyz is great.

NEEDS ATTENTION:
• Check suitability.another_fake_id for details.

WHY THESE MATTER:
Because.

WHAT TO REVIEW NEXT:
• Review regularly.

DATA LIMITATIONS:
None.

PROFESSIONAL ADVICE NOTE:
Educational only.
"""
    exp, ver = explain_review(_REVIEW_DATA, _FakeProvider(invented_id_response))
    assert exp["generated_by"] == "template"


def test_explain_review_accepts_valid_ollama_response():
    valid_response = """OVERALL SUMMARY:
The portfolio scores 72/100 and is generally on track.

WHAT'S WORKING:
• Goal alignment score is strong at 80/100.

NEEDS ATTENTION:
• allocation.equity_above_range: equity is above the policy upper bound.

WHY THESE MATTER:
With a 7-15 year horizon and a long-term growth goal, maintaining target allocation matters.

WHAT TO REVIEW NEXT:
• Review the equity allocation at the next rebalancing window.

DATA LIMITATIONS:
Some prices missing.

PROFESSIONAL ADVICE NOTE:
This is educational and not investment or legal advice.
"""
    exp, ver = explain_review(_REVIEW_DATA, _FakeProvider(valid_response))
    assert exp["generated_by"] == "ollama"
    assert ver is not None
    assert "72/100" in exp["overall_summary"]


def test_ollama_provider_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(
        "app.services.portfolio_health.explanation.get_settings",
        lambda: type("S", (), {"ollama_enabled": False, "ollama_model": "x", "ollama_url": "x"})(),
    )
    p = OllamaExplanationProvider()
    assert p.generate("test") is None


# --------------------------------------------------------------------------- #
# Stage 4 — enrichment, classification, sector/geo/currency/fees
# --------------------------------------------------------------------------- #
from app.services.portfolio_health.enrich import (
    enrich_ticker,
    enrich_all,
    get_metadata_map,
    metadata_to_dict,
)
from app.services.portfolio_health.classify import classify_holding, classify_all
from app.services.portfolio_health.engine import (
    _sector_concentration,
    _geography_concentration,
    _currency_concentration,
    _fees_analysis,
)


def make_meta(**kwargs) -> dict:
    """Build a partial metadata dict for testing classify_holding."""
    defaults = {
        "asset_class": None, "sector": None, "region": None, "country": None,
        "currency": None, "product_type": None, "expense_ratio": None,
        "diversified_fund": None, "liquidity_level": None, "source": "auto",
        "updated_at": None,
    }
    defaults.update(kwargs)
    return defaults


# --- enrichment graceful degradation ---

def test_enrich_ticker_returns_none_when_yfinance_unavailable(monkeypatch, tmp_path):
    """enrich_ticker never raises; returns None when yfinance is unreachable."""
    from app.db import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    # Patch _yfinance_info to simulate network failure.
    import app.services.portfolio_health.enrich as enrich_mod
    monkeypatch.setattr(enrich_mod, "_yfinance_info", lambda ticker: {})

    result = enrich_ticker("MSFT", db)
    assert result is None  # graceful degrade, no exception


def test_enrich_ticker_caches_result(monkeypatch):
    """enrich_ticker writes a SecurityMetadata row when yfinance returns data."""
    from app.db import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    import app.services.portfolio_health.enrich as enrich_mod

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    fake_info = {
        "quoteType": "etf",
        "sector": None,
        "country": None,
        "currency": "USD",
        "expenseRatio": 0.0003,
    }
    monkeypatch.setattr(enrich_mod, "_yfinance_info", lambda ticker: fake_info)

    row = enrich_ticker("VT", db)
    assert row is not None
    assert row.ticker == "VT"
    assert row.product_type == "ETF"
    assert row.expense_ratio is not None
    assert row.diversified_fund is True
    assert row.currency == "USD"


def test_enrich_ticker_skips_fintual(monkeypatch):
    """Fintual tickers (namespaced FINTUAL:*) are skipped without a yfinance call."""
    from app.db import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    import app.services.portfolio_health.enrich as enrich_mod

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    calls = []
    monkeypatch.setattr(enrich_mod, "_yfinance_info", lambda t: calls.append(t) or {})

    result = enrich_ticker("FINTUAL:12345", db)
    assert result is None
    assert not calls  # no yfinance call made


# --- manual override precedence ---

def test_manual_override_never_overwritten_by_enrich(monkeypatch):
    """A row with source='manual' is returned as-is; enrich_ticker never overwrites it."""
    from app.db import Base
    from app.models.portfolio_health import SecurityMetadata
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    import app.services.portfolio_health.enrich as enrich_mod
    from datetime import datetime, timezone, timedelta

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    # Insert a manual override with a stale updated_at so the TTL would normally trigger a refresh.
    stale_time = datetime.now(tz=timezone.utc) - timedelta(days=30)
    manual = SecurityMetadata(
        ticker="AAPL",
        sector="Healthcare",  # deliberately wrong — manual override wins
        expense_ratio=99.0,
        source="manual",
        updated_at=stale_time,
    )
    db.add(manual)
    db.flush()

    # Even though yfinance would return different data, manual row must be preserved.
    monkeypatch.setattr(
        enrich_mod, "_yfinance_info",
        lambda t: {"quoteType": "equity", "sector": "Technology", "currency": "USD"}
    )

    row = enrich_ticker("AAPL", db)
    assert row is not None
    assert row.source == "manual"
    assert row.sector == "Healthcare"   # not overwritten
    assert row.expense_ratio == 99.0    # not overwritten


# --- classification with metadata ---

def test_classify_holding_upgrades_unknown_bucket_from_metadata():
    """When asset_class in the snapshot is empty but metadata has it, bucket is upgraded."""
    h = holding(1, "MSFT", "", "100000")  # no asset_class
    meta = make_meta(asset_class="equity", diversified_fund=False)
    hc = classify_holding(h, meta)
    assert hc.policy_bucket == "global_equities"
    assert hc.asset_class_known is True
    assert hc.is_single_stock is True


def test_classify_holding_metadata_diversified_flag_overrides_default():
    """metadata.diversified_fund=True marks an equity-bucket holding as not a single stock."""
    h = holding(1, "SPY", "equity", "200000")
    meta = make_meta(asset_class="equity", diversified_fund=True)
    hc = classify_holding(h, meta)
    assert hc.is_diversified_fund is True
    assert hc.is_single_stock is False


def test_classify_holding_sector_and_country_populated_from_metadata():
    h = holding(1, "NVDA", "equity", "100000")
    meta = make_meta(sector="Technology", country="US", region="North America", expense_ratio=0.0)
    hc = classify_holding(h, meta)
    assert hc.sector == "Technology"
    assert hc.country == "US"
    assert hc.expense_ratio == 0.0


# --- sector concentration ---

def _make_classes_with_sector(entries):
    """Build a list of HoldingClass-like objects for concentration tests."""
    from app.services.portfolio_health.classify import HoldingClass
    classes = []
    for h_dict in entries:
        h = holding(h_dict["id"], h_dict["ticker"], h_dict.get("asset_class", "equity"),
                    h_dict["value"])
        meta = make_meta(
            sector=h_dict.get("sector"),
            country=h_dict.get("country"),
            expense_ratio=h_dict.get("expense_ratio"),
            diversified_fund=h_dict.get("diversified_fund", False),
        )
        classes.append(classify_holding(h, meta))
    return classes


def test_sector_concentration_finding_when_over_limit():
    """Single-stock tech exposure > 30% → sector.over_limit finding."""
    classes = _make_classes_with_sector([
        {"id": 1, "ticker": "AAPL", "value": "400000", "sector": "Technology"},
        {"id": 2, "ticker": "MSFT", "value": "300000", "sector": "Technology"},
        {"id": 3, "ticker": "JPM", "value": "300000", "sector": "Financials"},
    ])
    invested = Decimal("1000000")
    diag, findings = _sector_concentration(classes, invested, max_sector_pct=30.0)
    sector_f = [f for f in findings if f.fid == "sector.over_limit"]
    assert sector_f, "expected sector.over_limit finding"
    tech_f = [f for f in sector_f if f.evidence["sector"] == "Technology"]
    assert tech_f
    assert tech_f[0].evidence["currentPercent"] == pytest.approx(70.0)


def test_sector_concentration_no_finding_when_within_limit():
    # 20% Technology + 20% Financials + 60% in a diversified ETF (no sector) → no finding
    classes = _make_classes_with_sector([
        {"id": 1, "ticker": "AAPL", "value": "200000", "sector": "Technology"},
        {"id": 2, "ticker": "JPM", "value": "200000", "sector": "Financials"},
        {"id": 3, "ticker": "VT", "value": "600000", "asset_class": "etf",
         "sector": None, "diversified_fund": True},
    ])
    invested = Decimal("1000000")
    _, findings = _sector_concentration(classes, invested, max_sector_pct=30.0)
    assert not findings


def test_sector_concentration_skips_diversified_funds():
    """Diversified ETFs don't contribute to sector concentration (no sector set)."""
    classes = _make_classes_with_sector([
        {"id": 1, "ticker": "VT", "value": "800000", "asset_class": "etf",
         "sector": None, "diversified_fund": True},
        {"id": 2, "ticker": "AAPL", "value": "200000", "sector": "Technology"},
    ])
    invested = Decimal("1000000")
    _, findings = _sector_concentration(classes, invested, max_sector_pct=30.0)
    # AAPL is 20% of Technology, VT has no sector — no sector finding
    assert not findings


# --- geography concentration ---

def test_geography_concentration_finding_when_over_limit():
    """US holdings > 70% → geography.over_limit finding."""
    classes = _make_classes_with_sector([
        {"id": 1, "ticker": "AAPL", "value": "500000", "country": "US"},
        {"id": 2, "ticker": "MSFT", "value": "300000", "country": "US"},
        {"id": 3, "ticker": "NESN", "value": "200000", "country": "CH"},
    ])
    invested = Decimal("1000000")
    _, findings = _geography_concentration(classes, invested, max_country_pct=70.0)
    us_f = [f for f in findings if f.evidence["country"] == "US"]
    assert us_f
    assert us_f[0].evidence["currentPercent"] == pytest.approx(80.0)


def test_geography_concentration_no_finding_without_metadata():
    """Holdings without country metadata produce no geography findings."""
    classes = _make_classes_with_sector([
        {"id": 1, "ticker": "AAPL", "value": "900000"},  # no country
        {"id": 2, "ticker": "AGG", "value": "100000"},
    ])
    invested = Decimal("1000000")
    _, findings = _geography_concentration(classes, invested, max_country_pct=70.0)
    assert not findings


# --- currency concentration ---

def test_currency_concentration_finding_when_over_limit():
    """USD exposure > 80% of total → currency.over_limit finding."""
    by_currency = [
        {"currency": "USD", "total_in_base": "900000"},
        {"currency": "CLP", "total_in_base": "100000"},
    ]
    total = Decimal("1000000")
    _, findings = _currency_concentration(by_currency, total, max_currency_pct=80.0)
    usd_f = [f for f in findings if f.evidence["currency"] == "USD"]
    assert usd_f
    assert usd_f[0].evidence["currentPercent"] == pytest.approx(90.0)


def test_currency_concentration_no_finding_within_limit():
    by_currency = [
        {"currency": "USD", "total_in_base": "700000"},
        {"currency": "EUR", "total_in_base": "300000"},
    ]
    total = Decimal("1000000")
    _, findings = _currency_concentration(by_currency, total, max_currency_pct=80.0)
    assert not findings


# --- fees ---

def test_fees_weighted_er_medium_finding_when_above_warn_threshold():
    """ER = 0.9% on 100% of portfolio → medium fees finding."""
    classes = _make_classes_with_sector([
        {"id": 1, "ticker": "SOME_FUND", "value": "1000000", "expense_ratio": 0.9,
         "asset_class": "etf", "diversified_fund": True},
    ])
    invested = Decimal("1000000")
    diag, findings = _fees_analysis(classes, invested)
    assert diag["weighted_expense_ratio"] == pytest.approx(0.9, abs=0.001)
    high_f = [f for f in findings if f.fid == "fees.high_weighted_expense_ratio"]
    assert high_f
    assert high_f[0].severity == "medium"


def test_fees_weighted_er_high_finding_when_above_high_threshold():
    """ER = 2.0% → high severity finding."""
    classes = _make_classes_with_sector([
        {"id": 1, "ticker": "EXP_FUND", "value": "1000000", "expense_ratio": 2.0,
         "asset_class": "etf", "diversified_fund": True},
    ])
    invested = Decimal("1000000")
    _, findings = _fees_analysis(classes, invested)
    high_f = [f for f in findings if f.fid == "fees.very_high_weighted_expense_ratio"]
    assert high_f
    assert high_f[0].severity == "high"


def test_fees_no_finding_when_low_er():
    """ER = 0.03% (typical index ETF) → no fee finding."""
    classes = _make_classes_with_sector([
        {"id": 1, "ticker": "VT", "value": "1000000", "expense_ratio": 0.03,
         "asset_class": "etf", "diversified_fund": True},
    ])
    invested = Decimal("1000000")
    _, findings = _fees_analysis(classes, invested)
    fee_f = [f for f in findings if f.category == "fees" and "expense" in f.fid]
    assert not fee_f


def test_fees_data_missing_finding_when_no_er():
    """Holdings without expense_ratio produce a fees.data_missing finding, not invented fees."""
    classes = _make_classes_with_sector([
        {"id": 1, "ticker": "SOME_ETF", "value": "1000000", "expense_ratio": None,
         "asset_class": "etf", "diversified_fund": True},
    ])
    invested = Decimal("1000000")
    diag, findings = _fees_analysis(classes, invested)
    missing_f = [f for f in findings if f.fid == "fees.data_missing"]
    assert missing_f
    assert missing_f[0].evidence["count"] == 1
    # No weighted ER invented when data is missing
    assert diag["weighted_expense_ratio"] is None


def test_fees_weighted_er_arithmetic():
    """Weighted average ER = correct linear combination by portfolio weight."""
    classes = _make_classes_with_sector([
        {"id": 1, "ticker": "A", "value": "600000", "expense_ratio": 1.0,
         "asset_class": "etf", "diversified_fund": True},
        {"id": 2, "ticker": "B", "value": "400000", "expense_ratio": 0.0,
         "asset_class": "etf", "diversified_fund": True},
    ])
    invested = Decimal("1000000")
    diag, _ = _fees_analysis(classes, invested)
    # 60% × 1.0 + 40% × 0.0 = 0.6
    assert diag["weighted_expense_ratio"] == pytest.approx(0.6, abs=0.001)


def test_fees_crypto_excluded_from_missing_count():
    """Crypto holdings don't count toward the missing-fee-data finding."""
    from app.services.portfolio_health.classify import HoldingClass
    classes = [
        classify_holding(
            {"holding_id": 1, "ticker": "BTC", "asset_class": "crypto",
             "price_currency": "USD", "value_in_base": "200000", "missing_price": False}
        ),
        classify_holding(
            {"holding_id": 2, "ticker": "VT", "asset_class": "etf",
             "price_currency": "USD", "value_in_base": "800000", "missing_price": False},
            make_meta(expense_ratio=0.07, diversified_fund=True),
        ),
    ]
    invested = Decimal("1000000")
    diag, findings = _fees_analysis(classes, invested)
    missing_f = [f for f in findings if f.fid == "fees.data_missing"]
    assert not missing_f  # VT has data, BTC is excluded


# --- metadata endpoint tests (via TestClient) ---

def test_metadata_put_and_get(client, monkeypatch):
    """PUT /metadata/{ticker} creates a manual override; GET returns it."""
    cl, _ = client
    r = cl.put("/portfolio-health/metadata/AAPL", json={
        "sector": "Technology",
        "country": "US",
        "expense_ratio": 0.0,
        "diversified_fund": False,
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ticker"] == "AAPL"
    assert data["sector"] == "Technology"
    assert data["source"] == "manual"

    g = cl.get("/portfolio-health/metadata/AAPL")
    assert g.status_code == 200
    assert g.json()["country"] == "US"


def test_metadata_list(client):
    cl, _ = client
    cl.put("/portfolio-health/metadata/TSLA", json={"sector": "Automotive"})
    cl.put("/portfolio-health/metadata/NVDA", json={"sector": "Technology"})
    rows = cl.get("/portfolio-health/metadata").json()
    tickers = [r["ticker"] for r in rows]
    assert "TSLA" in tickers and "NVDA" in tickers


def test_metadata_delete(client):
    cl, _ = client
    cl.put("/portfolio-health/metadata/GOOG", json={"sector": "Technology"})
    del_r = cl.delete("/portfolio-health/metadata/GOOG")
    assert del_r.status_code == 200
    assert cl.get("/portfolio-health/metadata/GOOG").status_code == 404


def test_review_uses_metadata_for_sector_findings(client, monkeypatch):
    """When holdings have manual metadata with sector, sector findings appear in the review."""
    cl, session_factory = client
    from app.services.prices import valuation as valuation_mod
    from app.services.prices.provider import PriceLookupError

    class _DeadProvider:
        def fetch(self, ticker):
            raise PriceLookupError(f"offline: {ticker}")

    monkeypatch.setattr(valuation_mod, "get_provider", lambda: _DeadProvider())

    # Make enrichment a no-op (metadata comes from manual PUT below).
    import app.routers.portfolio_health as ph_router
    monkeypatch.setattr(ph_router, "enrich_all", lambda tickers, db: {})

    # Seed: a portfolio of 2 single stocks in the same sector.
    s = session_factory()
    from app.models import Account, Holding
    from app.models.accounts import AccountType
    acc = Account(name="Brokerage", country="US", type=AccountType.investment,
                  native_currency="CLP", current_balance=Decimal("0"))
    s.add(acc)
    s.commit()
    s.refresh(acc)
    s.add(Holding(account_id=acc.id, ticker="AAPL", quantity=Decimal("40"),
                  price_currency="CLP", asset_class="equity", manual_price=Decimal("10000")))
    s.add(Holding(account_id=acc.id, ticker="MSFT", quantity=Decimal("35"),
                  price_currency="CLP", asset_class="equity", manual_price=Decimal("10000")))
    s.commit()
    s.close()

    # Add manual metadata for both (same sector → triggers sector finding).
    cl.put("/portfolio-health/metadata/AAPL", json={"sector": "Technology", "country": "US",
                                                     "diversified_fund": False})
    cl.put("/portfolio-health/metadata/MSFT", json={"sector": "Technology", "country": "US",
                                                     "diversified_fund": False})

    cl.put("/portfolio-health/profile", json=_PROFILE_PAYLOAD)

    # Override enrich_all to return the manually-seeded metadata.
    import app.routers.portfolio_health as ph_router2
    from app.models.portfolio_health import SecurityMetadata
    from app.services.portfolio_health.enrich import metadata_to_dict as m2d

    def _fake_enrich(tickers, db):
        result = {}
        for t in tickers:
            row = db.get(SecurityMetadata, t.upper())
            if row:
                result[t] = row
        return result

    monkeypatch.setattr(ph_router2, "enrich_all", _fake_enrich)

    review = cl.post("/portfolio-health/review").json()
    assert review["profile_incomplete"] is False
    sector_findings = [f for f in review["findings"] if f["category"] == "sector"]
    assert sector_findings, "expected sector concentration finding from manual metadata"
