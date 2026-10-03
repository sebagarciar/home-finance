"""Average-cost replay of a trade ledger. Pure — no DB, no FX lookups.

Base (CLP) figures use each trade's own `fx_rate_to_base` (captured at the
trade date), so `cost_base` is what was actually paid in CLP terms. Sells
relieve cost at the running average in both native and base; they never move
the average itself.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ...models.investment_trades import TradeKind

_ZERO = Decimal("0")


class LedgerError(ValueError):
    """The ledger is internally inconsistent (oversell, misplaced opening, …)."""


@dataclass(frozen=True)
class TradeInput:
    date: date
    kind: TradeKind
    quantity: Decimal = _ZERO
    price: Decimal = _ZERO
    amount: Decimal = _ZERO
    fees: Decimal = _ZERO
    fx_rate_to_base: Decimal = Decimal("1")


@dataclass
class PositionState:
    qty: Decimal = _ZERO
    cost_native: Decimal = _ZERO
    cost_base: Decimal = _ZERO
    realized_native: Decimal = _ZERO
    realized_base: Decimal = _ZERO
    income_native: Decimal = _ZERO
    income_base: Decimal = _ZERO
    fees_native: Decimal = _ZERO  # standalone `fee` rows only; commissions sit in cost/proceeds
    fees_base: Decimal = _ZERO
    first_date: date | None = None
    trades: list[TradeInput] = field(default_factory=list)

    @property
    def avg_cost_native(self) -> Decimal | None:
        return self.cost_native / self.qty if self.qty > 0 else None


def ordered(trades: Iterable[TradeInput]) -> list[TradeInput]:
    """Chronological; an `opening` sorts first on its date. Stable otherwise, so
    callers pass same-day rows in id order."""
    return sorted(trades, key=lambda t: (t.date, t.kind is not TradeKind.opening))


def validate_ledger(trades: Iterable[TradeInput]) -> None:
    """Structural checks + a full replay (which raises on oversell)."""
    rows = ordered(trades)
    openings = [t for t in rows if t.kind is TradeKind.opening]
    if len(openings) > 1:
        raise LedgerError("only one opening position per holding")
    if openings and rows[0] is not openings[0]:
        raise LedgerError(
            f"opening position ({openings[0].date}) must be the earliest entry; "
            f"found an earlier {rows[0].kind.value} on {rows[0].date}"
        )
    replay(rows)


def replay(trades: Iterable[TradeInput]) -> PositionState:
    s = PositionState()
    for t in ordered(trades):
        s.trades.append(t)
        if s.first_date is None:
            s.first_date = t.date
        fx = t.fx_rate_to_base
        if t.kind in (TradeKind.opening, TradeKind.buy):
            gross = t.quantity * t.price + t.fees
            s.qty += t.quantity
            s.cost_native += gross
            s.cost_base += gross * fx
        elif t.kind is TradeKind.sell:
            if t.quantity > s.qty:
                raise LedgerError(
                    f"sell of {t.quantity} on {t.date} exceeds the {s.qty} units held"
                )
            if t.quantity == s.qty:
                # Close out exactly — avoids Decimal residue from avg × qty.
                relieved_native, relieved_base = s.cost_native, s.cost_base
            else:
                relieved_native = s.cost_native / s.qty * t.quantity
                relieved_base = s.cost_base / s.qty * t.quantity
            proceeds = t.quantity * t.price - t.fees
            s.realized_native += proceeds - relieved_native
            s.realized_base += proceeds * fx - relieved_base
            s.cost_native -= relieved_native
            s.cost_base -= relieved_base
            s.qty -= t.quantity
        elif t.kind is TradeKind.dividend:
            s.income_native += t.amount
            s.income_base += t.amount * fx
        elif t.kind is TradeKind.fee:
            s.fees_native += t.amount
            s.fees_base += t.amount * fx
    return s


def cash_flows(state: PositionState, *, in_base: bool) -> list[tuple[date, Decimal]]:
    """Investor-perspective flows (outflow negative) for XIRR, excluding the
    terminal value. Native flows are only meaningful within one currency."""
    out: list[tuple[date, Decimal]] = []
    for t in state.trades:
        fx = t.fx_rate_to_base if in_base else Decimal("1")
        if t.kind in (TradeKind.opening, TradeKind.buy):
            out.append((t.date, -(t.quantity * t.price + t.fees) * fx))
        elif t.kind is TradeKind.sell:
            out.append((t.date, (t.quantity * t.price - t.fees) * fx))
        elif t.kind is TradeKind.dividend:
            out.append((t.date, t.amount * fx))
        elif t.kind is TradeKind.fee:
            out.append((t.date, -t.amount * fx))
    return out
