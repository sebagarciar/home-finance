"""Stress-test scenarios for the portfolio (Stage 2).

Pure function: consumes the allocation/concentration/currency data already
computed by engine.py and applies STRESS_SHOCKS from config. Returns a list
of scenario dicts framed as estimates with transparent assumptions (not
predictions), plus any drawdown findings.

Called from run_review() so results are part of the deterministic review and
drawdown findings feed into scoring.
"""
from __future__ import annotations

from decimal import Decimal

from . import config as C
from . import findings as F

_ZERO = Decimal("0")


def run_stress(
    *,
    allocation_current_pct: dict[str, float],
    portfolio_value_in_base: Decimal,
    concentration_top1_pct: float,
    by_currency: list[dict],
    risk_profile: str = "moderate",
    base_currency: str = "CLP",
) -> tuple[list[dict], list[F.Finding]]:
    """Return (scenarios, drawdown_findings).

    Each scenario dict:
      {scenario, label, assumption, approx_impact_pct, approx_impact_base}

    All impacts are approximate — the assumption text makes the methodology
    transparent so the user understands what they're looking at.
    """
    value = portfolio_value_in_base if portfolio_value_in_base > _ZERO else _ZERO
    scenarios: list[dict] = []

    eq_pct = allocation_current_pct.get("global_equities", 0.0)
    bond_pct = allocation_current_pct.get("bonds", 0.0)
    crypto_pct = allocation_current_pct.get("crypto", 0.0)
    top1_pct = concentration_top1_pct

    def _impact(exposure_pct: float, shock: float) -> tuple[float, str]:
        """impact_pct (portfolio level), impact_base (CLP string)."""
        portfolio_impact_pct = round(exposure_pct / 100 * shock * 100, 2)
        portfolio_impact_base = str(
            (value * Decimal(str(exposure_pct / 100 * shock))).quantize(Decimal("1"))
        )
        return portfolio_impact_pct, portfolio_impact_base

    # ── Equity drawdown ────────────────────────────────────────────────────────
    eq_imp_pct, eq_imp_base = _impact(eq_pct, C.STRESS_SHOCKS["equity"])
    scenarios.append({
        "scenario": "equity_crash",
        "label": "Equity market crash",
        "assumption": (
            f"Equities ({eq_pct:.0f}% of portfolio) fall "
            f"{abs(C.STRESS_SHOCKS['equity'] * 100):.0f}%. "
            "Estimate based on historical -30% corrections (e.g. 2008, 2020)."
        ),
        "approx_impact_pct": eq_imp_pct,
        "approx_impact_base": eq_imp_base,
    })

    # ── Bond stress ────────────────────────────────────────────────────────────
    bond_imp_pct, bond_imp_base = _impact(bond_pct, C.STRESS_SHOCKS["bonds"])
    scenarios.append({
        "scenario": "bond_stress",
        "label": "Bond market stress",
        "assumption": (
            f"Bonds ({bond_pct:.0f}% of portfolio) fall "
            f"{abs(C.STRESS_SHOCKS['bonds'] * 100):.0f}%. "
            "Estimate based on interest-rate-rise stress scenarios."
        ),
        "approx_impact_pct": bond_imp_pct,
        "approx_impact_base": bond_imp_base,
    })

    # ── Crypto shock (only if meaningful exposure) ─────────────────────────────
    if crypto_pct > 0.1:
        crypto_imp_pct, crypto_imp_base = _impact(crypto_pct, C.STRESS_SHOCKS["crypto"])
        scenarios.append({
            "scenario": "crypto_crash",
            "label": "Crypto collapse",
            "assumption": (
                f"Crypto ({crypto_pct:.0f}% of portfolio) falls "
                f"{abs(C.STRESS_SHOCKS['crypto'] * 100):.0f}%. "
                "High-volatility tail risk estimate."
            ),
            "approx_impact_pct": crypto_imp_pct,
            "approx_impact_base": crypto_imp_base,
        })

    # ── Largest single holding shock ───────────────────────────────────────────
    if top1_pct > 0.1:
        lh_imp_pct, lh_imp_base = _impact(top1_pct, C.STRESS_SHOCKS["largest_holding"])
        scenarios.append({
            "scenario": "largest_holding_collapse",
            "label": "Largest holding collapse",
            "assumption": (
                f"Top holding ({top1_pct:.0f}% of portfolio) falls "
                f"{abs(C.STRESS_SHOCKS['largest_holding'] * 100):.0f}%. "
                "Idiosyncratic or company-specific risk estimate."
            ),
            "approx_impact_pct": lh_imp_pct,
            "approx_impact_base": lh_imp_base,
        })

    # ── Home-currency appreciation (CLP strengthens → foreign holdings cheaper in CLP) ──
    foreign_frac = _foreign_currency_fraction(by_currency, base_currency)
    if foreign_frac > 0.01:
        fx_pct = round(foreign_frac * 100, 1)
        fx_imp_pct, fx_imp_base = _impact(
            foreign_frac * 100, C.STRESS_SHOCKS["home_currency_strength"]
        )
        scenarios.append({
            "scenario": "home_currency_strength",
            "label": "Home currency appreciation",
            "assumption": (
                f"Foreign-currency holdings ({fx_pct:.0f}% of portfolio) lose "
                f"{abs(C.STRESS_SHOCKS['home_currency_strength'] * 100):.0f}% "
                "of CLP value as CLP appreciates by that margin."
            ),
            "approx_impact_pct": fx_imp_pct,
            "approx_impact_base": fx_imp_base,
        })

    # ── Drawdown finding if worst scenario breaches the profile threshold ───────
    findings: list[F.Finding] = []
    if scenarios and value > _ZERO:
        worst = min(scenarios, key=lambda s: s["approx_impact_pct"])
        threshold = C.DRAWDOWN_CONCERN_THRESHOLD.get(risk_profile, -30.0)
        if worst["approx_impact_pct"] < threshold:
            findings.append(
                F.build(
                    "drawdown.worst_case_exceeds_threshold",
                    severity="medium",
                    evidence={
                        "worstScenario": worst["scenario"],
                        "worstImpactPct": worst["approx_impact_pct"],
                        "thresholdPct": threshold,
                        "riskProfile": risk_profile,
                    },
                    impact_pct=abs(worst["approx_impact_pct"]),
                    threshold_pct=abs(threshold),
                )
            )

    return scenarios, findings


def _foreign_currency_fraction(by_currency: list[dict], base_currency: str) -> float:
    """Fraction of portfolio value held in non-base currencies."""
    total = sum(float(row.get("total_in_base") or 0) for row in by_currency)
    if total <= 0:
        return 0.0
    base_value = sum(
        float(row.get("total_in_base") or 0)
        for row in by_currency
        if (row.get("currency") or "").upper() == base_currency.upper()
    )
    return max(0.0, (total - base_value) / total)
