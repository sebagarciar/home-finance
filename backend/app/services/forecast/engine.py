"""Monte Carlo household net-worth forecast.

Vectorized across `n_paths` simulated futures, monthly steps over the horizon.
Everything is in base currency (CLP); the EUR display toggle is applied later at
render time, never here.

Model, per the build spec:
- **Start** from the latest net-worth snapshot (else the live computation).
- **Income**: both salaries -> base, monthly, with deterministic growth and a
  per-month lognormal noise (σ = `income_noise_sigma`).
- **Spending**: baseline -> base, with deterministic growth/inflation.
- **Returns**: historical block bootstrap of `equity`/`bonds` proxies (cash is
  deterministic). Falls back to a parametric Normal model when history can't be
  fetched, and a zero-vol `deterministic` mode exists for tests/offline.
- **Correlated shocks (ρ)**: in bottom-decile market months, income is scaled
  down and spending up by `ρ × shock magnitude`.
- **Real terms by default** (deflate by inflation); nominal via the toggle.
- **FX scenario**: flat by default; an annual CLP drift can be applied to the
  foreign-currency income streams (never bundled into returns).
- **Life events**: optional dated lump sums.

Outputs P10/P25/P50/P75/P90 net-worth bands across the horizon plus the
probability of finishing at or above an editable target.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Assumptions, NetworthSnapshot
from ..fx.conversion import to_base_current
from ..networth import current_networth
from .blocks import (
    ASSET_PROXIES,
    BlockBootstrap,
    ReturnsUnavailable,
    fetch_monthly_returns,
    shock_mask,
)

log = logging.getLogger(__name__)

# Annualized volatility used by the parametric returns fallback, by asset class.
# Cash is treated as risk-free. Only consulted when the block bootstrap is
# unavailable (offline) or explicitly requested.
_PARAMETRIC_VOL = {"equity": 0.15, "bonds": 0.05, "cash": 0.0}

_PERCENTILES = (10, 25, 50, 75, 90)


def _add_months(d: date, months: int) -> date:
    """Calendar month arithmetic, clamping the day to 28 to stay valid."""
    total = (d.year * 12 + (d.month - 1)) + months
    year, month = divmod(total, 12)
    return date(year, month + 1, min(d.day, 28))


def _start_networth(db: Session) -> Decimal:
    latest = db.execute(
        select(NetworthSnapshot).order_by(NetworthSnapshot.date.desc()).limit(1)
    ).scalar_one_or_none()
    if latest is not None:
        return Decimal(str(latest.total_networth_in_base))
    return Decimal(current_networth(db)["total_in_base"])


def _portfolio_returns(
    a: Assumptions,
    n_paths: int,
    n_months: int,
    rng: np.random.Generator,
    returns_mode: str,
) -> np.ndarray:
    """Return `[n_paths, n_months]` portfolio monthly returns, allocation-weighted
    across asset classes. `returns_mode` ∈ auto|bootstrap|parametric|deterministic."""
    allocation: dict[str, float] = {k: float(v) for k, v in a.asset_allocation.items()}
    total_alloc = sum(allocation.values()) or 1.0
    weights = {k: v / total_alloc for k, v in allocation.items()}
    expected: dict[str, float] = {k: float(v) for k, v in a.return_assumptions.items()}

    # Asset classes that have a historical proxy and can be bootstrapped.
    boot_classes = [c for c in weights if c in ASSET_PROXIES]
    det_classes = [c for c in weights if c not in ASSET_PROXIES]  # e.g. cash

    use_bootstrap = returns_mode in ("auto", "bootstrap") and boot_classes
    sampled: np.ndarray | None = None
    if use_bootstrap:
        try:
            matrix, classes = fetch_monthly_returns(boot_classes)
            sampled = BlockBootstrap(matrix).sample(n_paths, n_months, rng)
            boot_classes = classes
        except ReturnsUnavailable as e:
            if returns_mode == "bootstrap":
                raise
            log.warning("Forecast returns unavailable (%s); using parametric model.", e)
            sampled = None

    port = np.zeros((n_paths, n_months), dtype=float)

    if sampled is not None:
        for i, c in enumerate(boot_classes):
            port += weights[c] * sampled[:, :, i]
    else:
        # Parametric / deterministic for the would-be-bootstrapped classes.
        for c in boot_classes:
            mu_m = (1.0 + expected.get(c, 0.0)) ** (1 / 12) - 1.0
            if returns_mode == "deterministic":
                draws = np.full((n_paths, n_months), mu_m)
            else:
                vol_m = _PARAMETRIC_VOL.get(c, 0.0) / np.sqrt(12)
                draws = rng.normal(mu_m, vol_m, size=(n_paths, n_months))
            port += weights[c] * draws

    # Deterministic classes (cash) — always from the expected return, no vol.
    for c in det_classes:
        mu_m = (1.0 + expected.get(c, 0.0)) ** (1 / 12) - 1.0
        port += weights[c] * mu_m

    return port


def run_forecast(
    db: Session,
    *,
    overrides: dict | None = None,
    n_paths: int = 10000,
    seed: int | None = None,
    returns_mode: str = "auto",
) -> dict:
    """Run the Monte Carlo forecast and return a JSON-ready band/summary dict."""
    overrides = overrides or {}
    a = db.execute(select(Assumptions).limit(1)).scalar_one_or_none()
    if a is None:
        raise ValueError("No assumptions row found — seed the database first.")

    horizon_years = int(overrides.get("horizon_years") or a.horizon_years)
    real = bool(overrides.get("real", True))
    target = overrides.get("target")
    target_dec = Decimal(str(target)) if target is not None else None
    n_months = horizon_years * 12

    rng = np.random.default_rng(seed)

    start_nw = float(_start_networth(db))

    # --- Income (base, monthly) -------------------------------------------------
    income_base = float(
        to_base_current(db, a.income_user1, a.income_user1_currency)
        + to_base_current(db, a.income_user2, a.income_user2_currency)
    )
    spending_base = float(to_base_current(db, a.spending_baseline_monthly, a.spending_baseline_currency))

    g_income = (1.0 + float(a.income_growth_rate)) ** (1 / 12)
    g_spending = (1.0 + float(a.spending_growth_rate)) ** (1 / 12)
    sigma = float(a.income_noise_sigma)
    rho = float(a.correlation_rho)
    fx_drift = float(a.fx_drift_annual)
    monthly_inflation = (1.0 + float(a.inflation_rate)) ** (1 / 12)

    months = np.arange(1, n_months + 1)
    income_trend = income_base * g_income ** (months - 1)  # [n_months]
    spending_trend = spending_base * g_spending ** (months - 1)

    # FX scenario: apply an annual CLP drift to the foreign-currency income share.
    # Flat (drift 0) leaves this a no-op. Approximated at the household level.
    if fx_drift and income_base:
        foreign_share = 1.0 - (
            float(to_base_current(db, a.income_user1, a.income_user1_currency)) if a.income_user1_currency == "CLP" else 0.0
        ) / income_base
        years_elapsed = (months - 1) / 12.0
        income_trend = income_trend * (
            (1.0 - foreign_share) + foreign_share * (1.0 + fx_drift) ** years_elapsed
        )

    # Per-path-month income with lognormal noise (σ=0 -> exact trend).
    noise = (
        np.exp(rng.normal(0.0, sigma, size=(n_paths, n_months)))
        if sigma > 0
        else np.ones((n_paths, n_months))
    )
    income = income_trend[None, :] * noise
    spending = np.broadcast_to(spending_trend[None, :], (n_paths, n_months)).copy()

    # --- Returns + correlated shocks -------------------------------------------
    port = _portfolio_returns(a, n_paths, n_months, rng, returns_mode)
    if rho > 0:
        q10 = np.quantile(port, 0.10)
        if q10 < 0:
            fires = shock_mask(port, 0.10)
            mag = np.clip((q10 - port) / abs(q10), 0.0, 1.0)
            scale = rho * mag * fires
            income = income * (1.0 - scale)
            spending = spending * (1.0 + scale)

    # --- Life events (dated lump sums) -----------------------------------------
    life_flows = np.zeros(n_months, dtype=float)
    for ev in overrides.get("life_events", []) or []:
        m = int(ev["month"])
        if 1 <= m <= n_months:
            life_flows[m - 1] += float(
                to_base_current(db, ev["amount"], ev.get("currency", "CLP"))
            )

    # --- Iterate (vectorized across paths) -------------------------------------
    nw = np.empty((n_paths, n_months + 1), dtype=float)
    nw[:, 0] = start_nw
    for t in range(n_months):
        nw[:, t + 1] = (
            nw[:, t] * (1.0 + port[:, t]) + income[:, t] - spending[:, t] + life_flows[t]
        )

    if real:
        deflator = monthly_inflation ** np.arange(n_months + 1)  # [n_months+1]
        nw = nw / deflator[None, :]

    # --- Percentile bands -------------------------------------------------------
    pct = np.percentile(nw, _PERCENTILES, axis=0)  # [5, n_months+1]
    today = date.today()
    bands = [
        {
            "month": t,
            "date": _add_months(today, t).isoformat(),
            "p10": round(float(pct[0, t]), 2),
            "p25": round(float(pct[1, t]), 2),
            "p50": round(float(pct[2, t]), 2),
            "p75": round(float(pct[3, t]), 2),
            "p90": round(float(pct[4, t]), 2),
        }
        for t in range(n_months + 1)
    ]

    terminal = nw[:, -1]
    prob_hit_target = (
        float(np.mean(terminal >= float(target_dec))) if target_dec is not None else None
    )

    return {
        "currency": "CLP",
        "real": real,
        "n_paths": n_paths,
        "horizon_years": horizon_years,
        "start_networth": round(start_nw, 2),
        "bands": bands,
        "terminal": {
            "p10": round(float(np.percentile(terminal, 10)), 2),
            "p50": round(float(np.percentile(terminal, 50)), 2),
            "p90": round(float(np.percentile(terminal, 90)), 2),
        },
        "target": float(target_dec) if target_dec is not None else None,
        "prob_hit_target": prob_hit_target,
    }
