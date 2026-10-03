"""Money-weighted return (XIRR) over dated cash flows. Pure.

Rates are floats (they're ratios, not money); amounts arrive as Decimal and are
converted only here.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

_LO, _HI = -0.9999, 10.0


def _npv(rate: float, flows: Sequence[tuple[float, float]]) -> float:
    return sum(cf / (1.0 + rate) ** t for t, cf in flows)


def _dnpv(rate: float, flows: Sequence[tuple[float, float]]) -> float:
    return sum(-t * cf / (1.0 + rate) ** (t + 1) for t, cf in flows)


def xirr(cash_flows: Sequence[tuple[date, Decimal]], *, tol: float = 1e-10) -> float | None:
    """Annualized rate r with sum(cf / (1+r)^(days/365)) = 0.

    Returns None when undefined: fewer than two flows, or no sign change (all
    in, or all out). Newton first; bisection over [-99.99%, 1000%] if Newton
    wanders or stalls.
    """
    if len(cash_flows) < 2:
        return None
    t0 = min(d for d, _ in cash_flows)
    flows = [((d - t0).days / 365.0, float(cf)) for d, cf in cash_flows]
    if not (any(cf > 0 for _, cf in flows) and any(cf < 0 for _, cf in flows)):
        return None

    rate = 0.1
    for _ in range(100):
        f = _npv(rate, flows)
        if abs(f) < tol:
            return rate
        d = _dnpv(rate, flows)
        if d == 0:
            break
        nxt = rate - f / d
        if not (_LO < nxt < _HI):
            break
        if abs(nxt - rate) < tol:
            return nxt
        rate = nxt

    lo, hi = _LO, _HI
    f_lo, f_hi = _npv(lo, flows), _npv(hi, flows)
    if f_lo * f_hi > 0:
        return None
    for _ in range(300):
        mid = (lo + hi) / 2
        f_mid = _npv(mid, flows)
        if abs(f_mid) < tol or (hi - lo) < tol:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def period_return(annual_rate: float, start: date, end: date) -> float:
    """De-annualize an XIRR to the holding period — used when the span is under
    a year, where an annualized figure is misleading (3 weeks at +2% → +40%/yr)."""
    return (1.0 + annual_rate) ** ((end - start).days / 365.0) - 1.0
