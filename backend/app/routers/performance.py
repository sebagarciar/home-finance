"""Cost basis + returns across holdings. See services/performance/service.py."""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_session
from ..services.performance.service import HoldingPerformance, portfolio_performance

router = APIRouter(prefix="/performance", tags=["performance"])


def _s(v: Decimal | None) -> str | None:
    return None if v is None else str(v)


def _holding(p: HoldingPerformance) -> dict:
    st = p.state
    avg = st.avg_cost_native
    return {
        "holding_id": p.holding_id,
        "ticker": p.ticker,
        "currency": p.currency,
        "has_basis": p.has_basis,
        "reconciled": p.reconciled,
        "issue": p.issue,
        "ledger_qty": str(p.ledger_qty),
        "holding_qty": str(p.holding_qty),
        "since": p.since.isoformat() if p.since else None,
        "avg_cost_native": _s(avg),
        "cost_native": str(st.cost_native),
        "cost_base": str(st.cost_base),
        "value_base": _s(p.value_base),
        "unrealized_base": _s(p.unrealized_base),
        "price_effect": _s(p.price_effect),
        "fx_effect": _s(p.fx_effect),
        "realized_base": str(st.realized_base),
        "income_base": str(st.income_base),
        "fees_base": str(st.fees_base),
        "return": p.ret_base.rate,
        "return_native": p.ret_native.rate,
        "annualized": p.ret_base.annualized,
    }


@router.get("")
def get_performance(db: Session = Depends(get_session)):
    perf = portfolio_performance(db)
    return {
        "totals": {
            "cost_base": str(perf.cost_base),
            "value_base": str(perf.value_base),
            "unrealized_base": str(perf.unrealized_base),
            "price_effect": str(perf.price_effect),
            "fx_effect": str(perf.fx_effect),
            "realized_base": str(perf.realized_base),
            "income_base": str(perf.income_base),
            "fees_base": str(perf.fees_base),
            "return": perf.ret.rate,
            "annualized": perf.ret.annualized,
            "coverage_pct": perf.coverage_pct,
        },
        "holdings": [_holding(p) for p in perf.holdings],
    }
