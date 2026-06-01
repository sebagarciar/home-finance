from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Account, AccountType

router = APIRouter(prefix="/accounts", tags=["accounts"])


class AccountIn(BaseModel):
    name: str
    institution: str | None = None
    country: str = Field(min_length=2, max_length=2)
    type: AccountType
    native_currency: str = Field(min_length=3, max_length=3)
    current_balance: Decimal = Decimal("0")


class AccountOut(BaseModel):
    id: int
    name: str
    institution: str | None
    country: str
    type: AccountType
    native_currency: str
    current_balance: Decimal
    balance_updated_at: datetime | None

    model_config = {"from_attributes": True}


class BalanceIn(BaseModel):
    current_balance: Decimal


@router.get("", response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_session)):
    return list(db.execute(select(Account).order_by(Account.id)).scalars().all())


@router.post("", response_model=AccountOut, status_code=201)
def create_account(payload: AccountIn, db: Session = Depends(get_session)):
    a = Account(
        name=payload.name,
        institution=payload.institution,
        country=payload.country.upper(),
        type=payload.type,
        native_currency=payload.native_currency.upper(),
        current_balance=payload.current_balance,
        balance_updated_at=(
            datetime.now(UTC) if payload.current_balance != 0 else None
        ),
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


@router.put("/{account_id}/balance", response_model=AccountOut)
def set_balance(account_id: int, payload: BalanceIn, db: Session = Depends(get_session)):
    """Update the manual cash balance. Net-worth reads this directly — there is
    no derivation from transactions."""
    a = db.get(Account, account_id)
    if a is None:
        raise HTTPException(404, "account not found")
    a.current_balance = payload.current_balance
    a.balance_updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(a)
    return a


@router.delete("/{account_id}", status_code=204)
def delete_account(account_id: int, db: Session = Depends(get_session)):
    a = db.get(Account, account_id)
    if a is None:
        raise HTTPException(404, "account not found")
    db.delete(a)
    db.commit()
