"""Holdings CRUD + valuation endpoints.

Valuation goes through `price_holding` which falls back to `manual_price` when
the provider is unreachable. The response includes a staleness flag so the UI
can render "manual, as of <date>".
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Account, Holding
from ..services.fx.conversion import to_base_current
from ..services.prices import price_holding

router = APIRouter(prefix="/holdings", tags=["holdings"])


class HoldingIn(BaseModel):
    account_id: int
    ticker: str = Field(min_length=1, max_length=32)
    quantity: Decimal
    price_currency: str = Field(min_length=3, max_length=3)
    asset_class: str = "equity"
    manual_price: Decimal | None = None


class HoldingUpdate(BaseModel):
    account_id: int | None = None
    ticker: str | None = Field(default=None, min_length=1, max_length=32)
    quantity: Decimal | None = None
    price_currency: str | None = Field(default=None, min_length=3, max_length=3)
    asset_class: str | None = None
    manual_price: Decimal | None = None  # explicit null clears the override


class ManualPriceIn(BaseModel):
    manual_price: Decimal | None  # None clears the manual override


def _serialize(db: Session, h: Holding) -> dict:
    """List representation: priced + converted to base, includes staleness."""
    priced = price_holding(db, h)
    if priced.missing:
        value_base = Decimal("0")
    else:
        value_base = to_base_current(db, priced.value, priced.price_currency)
    return {
        "id": h.id,
        "account_id": h.account_id,
        "ticker": h.ticker,
        "quantity": str(h.quantity),
        "price_currency": h.price_currency,
        "asset_class": h.asset_class,
        "manual_price": str(h.manual_price) if h.manual_price is not None else None,
        "manual_price_updated_at": (
            h.manual_price_updated_at.isoformat() if h.manual_price_updated_at else None
        ),
        "price": str(priced.price),
        "as_of": priced.as_of.isoformat(),
        "source": priced.source,
        "is_manual": priced.is_manual,
        "missing_price": priced.missing,
        "value_native": str(priced.value),
        "value_in_base": str(value_base),
    }


@router.get("")
def list_holdings(db: Session = Depends(get_session)):
    rows = db.execute(select(Holding).order_by(Holding.id)).scalars().all()
    return [_serialize(db, h) for h in rows]


@router.post("", status_code=201)
def create_holding(payload: HoldingIn, db: Session = Depends(get_session)):
    if db.get(Account, payload.account_id) is None:
        raise HTTPException(404, f"account {payload.account_id} not found")
    h = Holding(
        account_id=payload.account_id,
        ticker=payload.ticker.upper(),
        quantity=payload.quantity,
        price_currency=payload.price_currency.upper(),
        asset_class=payload.asset_class,
        manual_price=payload.manual_price,
        manual_price_updated_at=(
            datetime.now(UTC) if payload.manual_price is not None else None
        ),
    )
    db.add(h)
    db.commit()
    db.refresh(h)
    return _serialize(db, h)


@router.patch("/{holding_id}")
def update_holding(holding_id: int, payload: HoldingUpdate, db: Session = Depends(get_session)):
    h = db.get(Holding, holding_id)
    if h is None:
        raise HTTPException(404, "holding not found")
    if payload.account_id is not None:
        if db.get(Account, payload.account_id) is None:
            raise HTTPException(404, f"account {payload.account_id} not found")
        h.account_id = payload.account_id
    if payload.ticker is not None:
        h.ticker = payload.ticker.upper()
    if payload.quantity is not None:
        h.quantity = payload.quantity
    if payload.price_currency is not None:
        h.price_currency = payload.price_currency.upper()
    if payload.asset_class is not None:
        h.asset_class = payload.asset_class
    if "manual_price" in payload.model_fields_set and payload.manual_price != h.manual_price:
        h.manual_price = payload.manual_price
        h.manual_price_updated_at = (
            datetime.now(UTC) if payload.manual_price is not None else None
        )
    db.commit()
    db.refresh(h)
    return _serialize(db, h)


@router.put("/{holding_id}/manual_price")
def set_manual_price(holding_id: int, payload: ManualPriceIn, db: Session = Depends(get_session)):
    """Set or clear the manual-price override. Pass null to clear."""
    h = db.get(Holding, holding_id)
    if h is None:
        raise HTTPException(404, "holding not found")
    h.manual_price = payload.manual_price
    h.manual_price_updated_at = (
        datetime.now(UTC) if payload.manual_price is not None else None
    )
    db.commit()
    db.refresh(h)
    return _serialize(db, h)


@router.delete("/{holding_id}", status_code=204)
def delete_holding(holding_id: int, db: Session = Depends(get_session)):
    h = db.get(Holding, holding_id)
    if h is None:
        raise HTTPException(404, "holding not found")
    db.delete(h)
    db.commit()
