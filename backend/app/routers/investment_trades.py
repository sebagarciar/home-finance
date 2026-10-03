"""Cost-basis ledger CRUD.

Every write replays the holding's full ledger (with the change applied) before
committing, so an edit or delete that would make a later sell oversell is
rejected with 422 rather than leaving a broken ledger behind.

Buys/sells may be entered by quantity or by cash `amount` (Fintual statements
show CLP deposited, not units): buy qty = (amount − fees) / price, sell qty =
(amount + fees) / price, where `amount` is cash paid / net proceeds received.
"""
from __future__ import annotations

from datetime import date as date_type
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Holding, InvestmentTrade, TradeKind
from ..services.fx.conversion import to_base
from ..services.performance import LedgerError, validate_ledger
from ..services.performance.service import trade_input

router = APIRouter(tags=["investment-trades"])

_UNIT_KINDS = (TradeKind.opening, TradeKind.buy, TradeKind.sell)
_QTY_PLACES = Decimal("0.00000001")


class TradeIn(BaseModel):
    date: date_type
    kind: TradeKind
    quantity: Decimal | None = None
    price: Decimal | None = None
    amount: Decimal | None = None
    fees: Decimal = Decimal("0")
    note: str | None = Field(default=None, max_length=255)


class TradeUpdate(BaseModel):
    date: date_type | None = None
    kind: TradeKind | None = None
    quantity: Decimal | None = None
    price: Decimal | None = None
    amount: Decimal | None = None
    fees: Decimal | None = None
    note: str | None = Field(default=None, max_length=255)


def _resolve(payload: TradeIn) -> dict:
    """Validate a fully-specified trade and normalize it to column values."""
    if payload.date > date_type.today():
        raise HTTPException(422, "trade date cannot be in the future")
    if payload.fees < 0:
        raise HTTPException(422, "fees must be >= 0")

    if payload.kind in _UNIT_KINDS:
        if payload.price is None or payload.price <= 0:
            raise HTTPException(422, f"{payload.kind.value} needs a price > 0")
        if (payload.quantity is None) == (payload.amount is None):
            raise HTTPException(422, "give either quantity or amount, not both")
        if payload.quantity is not None:
            qty = payload.quantity
        else:
            assert payload.amount is not None
            gross = (
                payload.amount + payload.fees
                if payload.kind is TradeKind.sell
                else payload.amount - payload.fees
            )
            qty = (gross / payload.price).quantize(_QTY_PLACES)
        if qty <= 0:
            raise HTTPException(422, "quantity must be > 0")
        return {
            "date": payload.date, "kind": payload.kind, "quantity": qty,
            "price": payload.price, "amount": Decimal("0"), "fees": payload.fees,
            "note": payload.note,
        }

    if payload.amount is None or payload.amount <= 0:
        raise HTTPException(422, f"{payload.kind.value} needs an amount > 0")
    if payload.quantity or payload.price:
        raise HTTPException(422, f"{payload.kind.value} takes an amount, not quantity/price")
    return {
        "date": payload.date, "kind": payload.kind, "quantity": Decimal("0"),
        "price": Decimal("0"), "amount": payload.amount, "fees": payload.fees,
        "note": payload.note,
    }


def _check_ledger(holding: Holding, *, replace: InvestmentTrade | None = None,
                  candidate: InvestmentTrade | None = None) -> None:
    """Replay the ledger with `replace` swapped for `candidate` (either may be
    None: create → candidate only; delete → replace only)."""
    rows = [t for t in holding.trades if t is not replace]
    if candidate is not None:
        rows.append(candidate)
    rows.sort(key=lambda t: (t.date, t.id if t.id is not None else 1 << 62))
    try:
        validate_ledger(trade_input(t) for t in rows)
    except LedgerError as e:
        raise HTTPException(422, str(e)) from e


def _serialize(t: InvestmentTrade) -> dict:
    return {
        "id": t.id,
        "holding_id": t.holding_id,
        "date": t.date.isoformat(),
        "kind": t.kind.value,
        "quantity": str(t.quantity),
        "price": str(t.price),
        "amount": str(t.amount),
        "fees": str(t.fees),
        "currency": t.currency,
        "fx_rate_to_base": str(t.fx_rate_to_base),
        "note": t.note,
    }


def _holding(db: Session, holding_id: int) -> Holding:
    h = db.get(Holding, holding_id)
    if h is None:
        raise HTTPException(404, "holding not found")
    return h


@router.get("/holdings/{holding_id}/trades")
def list_trades(holding_id: int, db: Session = Depends(get_session)):
    return [_serialize(t) for t in _holding(db, holding_id).trades]


@router.post("/holdings/{holding_id}/trades", status_code=201)
def create_trade(holding_id: int, payload: TradeIn, db: Session = Depends(get_session)):
    h = _holding(db, holding_id)
    values = _resolve(payload)
    candidate = InvestmentTrade(
        holding_id=h.id,
        currency=h.price_currency,
        fx_rate_to_base=to_base(db, Decimal("1"), h.price_currency, payload.date),
        **values,
    )
    _check_ledger(h, candidate=candidate)
    h.trades.append(candidate)
    db.commit()
    db.refresh(candidate)
    return _serialize(candidate)


@router.patch("/trades/{trade_id}")
def update_trade(trade_id: int, payload: TradeUpdate, db: Session = Depends(get_session)):
    t = db.get(InvestmentTrade, trade_id)
    if t is None:
        raise HTTPException(404, "trade not found")
    sent = payload.model_fields_set
    kind = payload.kind if "kind" in sent and payload.kind is not None else t.kind
    unit_kind = kind in _UNIT_KINDS
    # Merge onto the stored row. Sending `amount` for a unit trade re-derives
    # quantity, so the stored quantity is dropped in that case.
    quantity: Decimal | None = None
    if "quantity" in sent:
        quantity = payload.quantity
    elif unit_kind and "amount" not in sent:
        quantity = t.quantity
    amount: Decimal | None = None
    if "amount" in sent:
        amount = payload.amount
    elif not unit_kind:
        amount = t.amount
    merged = TradeIn(
        date=payload.date if "date" in sent and payload.date else t.date,
        kind=kind,
        quantity=quantity,
        price=(payload.price if "price" in sent else t.price) if unit_kind else None,
        amount=amount,
        fees=payload.fees if "fees" in sent and payload.fees is not None else t.fees,
        note=payload.note if "note" in sent else t.note,
    )
    values = _resolve(merged)
    candidate = InvestmentTrade(
        id=t.id,
        holding_id=t.holding_id,
        currency=t.currency,
        fx_rate_to_base=(
            to_base(db, Decimal("1"), t.currency, values["date"])
            if values["date"] != t.date else t.fx_rate_to_base
        ),
        **values,
    )
    _check_ledger(t.holding, replace=t, candidate=candidate)
    for k, v in values.items():
        setattr(t, k, v)
    t.fx_rate_to_base = candidate.fx_rate_to_base
    db.commit()
    db.refresh(t)
    return _serialize(t)


@router.delete("/trades/{trade_id}", status_code=204)
def delete_trade(trade_id: int, db: Session = Depends(get_session)):
    t = db.get(InvestmentTrade, trade_id)
    if t is None:
        raise HTTPException(404, "trade not found")
    _check_ledger(t.holding, replace=t)
    t.holding.trades.remove(t)
    db.commit()
