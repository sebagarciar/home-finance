"""DB-facing aggregation for GET /performance.

Per holding: replay the ledger, check it reconciles with the manual
`Holding.quantity`, price it via the same `price_holding` the Portfolio page
uses, then attribute + compute XIRR. Portfolio totals cover only holdings with
a reconciled basis and a price; `coverage_pct` says how much of the
portfolio's value that is.

A gain computed on the wrong quantity looks right and isn't — so when the
ledger doesn't reconcile, unrealized gain and XIRR are None with a reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ...models.holdings import Holding
from ...models.investment_trades import InvestmentTrade
from ..fx.conversion import to_base_current
from ..prices import price_holding
from .attribution import attribute
from .basis import LedgerError, PositionState, TradeInput, cash_flows, replay
from .returns import period_return, xirr

QTY_TOLERANCE = Decimal("0.000001")


def trade_input(t: InvestmentTrade) -> TradeInput:
    return TradeInput(
        date=t.date,
        kind=t.kind,
        quantity=Decimal(str(t.quantity)),
        price=Decimal(str(t.price)),
        amount=Decimal(str(t.amount)),
        fees=Decimal(str(t.fees)),
        fx_rate_to_base=Decimal(str(t.fx_rate_to_base)),
    )


@dataclass(frozen=True)
class ReturnFigure:
    rate: float | None
    annualized: bool


def _return(
    flows: list[tuple[date, Decimal]], start: date | None, today: date
) -> ReturnFigure:
    rate = xirr(flows)
    if rate is None or start is None:
        return ReturnFigure(None, False)
    if (today - start).days < 365:
        return ReturnFigure(period_return(rate, start, today), False)
    return ReturnFigure(rate, True)


@dataclass
class HoldingPerformance:
    holding_id: int
    ticker: str
    currency: str
    has_basis: bool
    reconciled: bool
    # Why gains/return are suppressed: no_trades | qty_mismatch |
    # currency_mismatch | missing_price | ledger_error. None when all good.
    issue: str | None
    ledger_qty: Decimal
    holding_qty: Decimal
    since: date | None
    state: PositionState
    value_base: Decimal | None = None  # at Holding.quantity, like the Portfolio page
    unrealized_base: Decimal | None = None
    price_effect: Decimal | None = None
    fx_effect: Decimal | None = None
    ret_base: ReturnFigure = field(default_factory=lambda: ReturnFigure(None, False))
    ret_native: ReturnFigure = field(default_factory=lambda: ReturnFigure(None, False))
    flows_base: list[tuple[date, Decimal]] = field(default_factory=list)

    @property
    def covered(self) -> bool:
        return self.issue is None


def holding_performance(db: Session, h: Holding, today: date | None = None) -> HoldingPerformance:
    today = today or date.today()
    holding_qty = Decimal(str(h.quantity))
    inputs = [trade_input(t) for t in h.trades]
    issue: str | None = None
    try:
        state = replay(inputs)
    except LedgerError:
        state, issue = PositionState(), "ledger_error"

    perf = HoldingPerformance(
        holding_id=h.id,
        ticker=h.ticker,
        currency=h.price_currency,
        has_basis=bool(inputs),
        reconciled=bool(inputs) and abs(state.qty - holding_qty) <= QTY_TOLERANCE,
        issue=issue,
        ledger_qty=state.qty,
        holding_qty=holding_qty,
        since=state.first_date,
        state=state,
    )

    priced = price_holding(db, h)
    if not priced.missing:
        perf.value_base = to_base_current(db, priced.value, priced.price_currency)

    if perf.issue is None:
        if not inputs:
            perf.issue = "no_trades"
        elif any(t.currency != h.price_currency for t in h.trades):
            perf.issue = "currency_mismatch"
        elif not perf.reconciled:
            perf.issue = "qty_mismatch"
        elif priced.missing:
            perf.issue = "missing_price"
    if perf.issue is not None:
        return perf

    attr = attribute(db, state, priced.price, h.price_currency)
    perf.unrealized_base = attr.unrealized_base
    perf.price_effect = attr.price_effect
    perf.fx_effect = attr.fx_effect

    perf.flows_base = [*cash_flows(state, in_base=True), (today, attr.value_base)]
    flows_native = [*cash_flows(state, in_base=False), (today, state.qty * priced.price)]
    perf.ret_base = _return(perf.flows_base, state.first_date, today)
    perf.ret_native = _return(flows_native, state.first_date, today)
    return perf


@dataclass
class PortfolioPerformance:
    holdings: list[HoldingPerformance]
    cost_base: Decimal
    value_base: Decimal
    unrealized_base: Decimal
    price_effect: Decimal
    fx_effect: Decimal
    realized_base: Decimal
    income_base: Decimal
    fees_base: Decimal
    ret: ReturnFigure
    coverage_pct: float | None  # share of priced portfolio value with a covered basis


def portfolio_performance(db: Session, today: date | None = None) -> PortfolioPerformance:
    today = today or date.today()
    rows = (
        db.execute(select(Holding).options(selectinload(Holding.trades)).order_by(Holding.id))
        .scalars()
        .all()
    )
    perfs = [holding_performance(db, h, today) for h in rows]
    covered = [p for p in perfs if p.covered]

    def total(get) -> Decimal:
        return sum((get(p) for p in covered), Decimal("0"))

    all_value = sum((p.value_base for p in perfs if p.value_base is not None), Decimal("0"))
    covered_value = total(lambda p: p.value_base)
    # Every holding's terminal value is dated today, so concatenating the
    # per-holding flows yields the portfolio's flow set.
    flows = [f for p in covered for f in p.flows_base]
    start = min((p.since for p in covered if p.since), default=None)

    return PortfolioPerformance(
        holdings=perfs,
        cost_base=total(lambda p: p.state.cost_base),
        value_base=covered_value,
        unrealized_base=total(lambda p: p.unrealized_base),
        price_effect=total(lambda p: p.price_effect),
        fx_effect=total(lambda p: p.fx_effect),
        realized_base=total(lambda p: p.state.realized_base),
        income_base=total(lambda p: p.state.income_base),
        fees_base=total(lambda p: p.state.fees_base),
        ret=_return(flows, start, today),
        coverage_pct=float(covered_value / all_value) if all_value > 0 else None,
    )
