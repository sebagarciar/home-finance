from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime
from datetime import date as date_type
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Account, Category, Transaction
from ..models.transactions import TxnType
from ..services.categorization import apply_manual_correction
from ..services.categorization.cascade import classify
from ..services.categorization.normalize import normalize_description
from ..services.fx.conversion import to_base

router = APIRouter(prefix="/transactions", tags=["transactions"])


def _adjust_email_balance(db: Session, txn: Transaction, delta: Decimal) -> None:
    """Mirror an email-sourced row's contribution to account.current_balance.

    Email imports add each row's native amount to the balance (see
    commit_import); archiving / deleting / re-amounting such a row must apply
    the matching delta or the balance drifts. Statement rows never touch the
    balance — the user maintains it manually from the statement's closing
    figure — and neither do email rows in a non-native currency (the import
    skipped those too).
    """
    if txn.source != "email" or not delta:
        return
    account = db.get(Account, txn.account_id)
    if account is None or txn.currency != account.native_currency:
        return
    account.current_balance += delta
    account.balance_updated_at = datetime.now(UTC)


def _filtered_query(
    start: date_type | None,
    end: date_type | None,
    account_id: int | None,
    category: str | None,
    txn_type: TxnType | None,
    search: str | None,
    include_archived: bool,
):
    q = select(Transaction)
    if start is not None:
        q = q.where(Transaction.date >= start)
    if end is not None:
        q = q.where(Transaction.date <= end)
    if account_id is not None:
        q = q.where(Transaction.account_id == account_id)
    if category is not None:
        q = q.where(Transaction.category == category)
    if txn_type is not None:
        q = q.where(Transaction.txn_type == txn_type)
    if search:
        # Match against both raw and normalized description so the user can find
        # rows whether they remember the bank's exact wording or the cleaned form.
        pattern = f"%{search.lower()}%"
        q = q.where(
            or_(
                Transaction.raw_description.ilike(pattern),
                Transaction.normalized_description.ilike(pattern),
            )
        )
    if not include_archived:
        q = q.where(Transaction.archived.is_(False))
    return q


@router.get("")
def list_transactions(
    start: date_type | None = Query(None),
    end: date_type | None = Query(None),
    account_id: int | None = Query(None),
    category: str | None = Query(None),
    txn_type: TxnType | None = Query(None),
    search: str | None = Query(None, description="Case-insensitive substring match on raw or normalized description"),
    include_archived: bool = Query(False),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_session),
):
    q = _filtered_query(start, end, account_id, category, txn_type, search, include_archived)
    q = q.order_by(Transaction.date.desc(), Transaction.id.desc()).limit(limit).offset(offset)

    rows = db.execute(q).scalars().all()
    return [_serialize(t) for t in rows]


@router.get("/export.csv")
def export_transactions_csv(
    start: date_type | None = Query(None),
    end: date_type | None = Query(None),
    account_id: int | None = Query(None),
    category: str | None = Query(None),
    txn_type: TxnType | None = Query(None),
    search: str | None = Query(None),
    include_archived: bool = Query(False),
    db: Session = Depends(get_session),
):
    """Export the same filtered set the transactions list shows, as CSV.
    No limit/offset — exports honor filters but always return the full match.
    """
    q = _filtered_query(start, end, account_id, category, txn_type, search, include_archived)
    q = q.order_by(Transaction.date.desc(), Transaction.id.desc())
    rows = db.execute(q).scalars().all()

    accounts = {a.id: a for a in db.execute(select(Account)).scalars().all()}

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "date", "account", "amount", "currency", "amount_in_base_clp",
        "category", "txn_type", "description", "archived",
    ])
    for t in rows:
        account = accounts.get(t.account_id)
        writer.writerow([
            t.date.isoformat(),
            account.name if account else t.account_id,
            str(t.amount),
            t.currency,
            str(Decimal(str(t.amount)) * Decimal(str(t.fx_rate_to_base))),
            t.category or "",
            t.txn_type.value,
            t.normalized_description or t.raw_description,
            "yes" if t.archived else "no",
        ])

    filename = f"transactions_{datetime.now(UTC).strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _serialize(t: Transaction) -> dict:
    return {
        "id": t.id,
        "account_id": t.account_id,
        "date": t.date.isoformat(),
        "amount": str(t.amount),
        "currency": t.currency,
        "fx_rate_to_base": str(t.fx_rate_to_base),
        # amount_in_base = native * fx_rate; precomputed for the UI.
        "amount_in_base": str(Decimal(str(t.amount)) * Decimal(str(t.fx_rate_to_base))),
        "txn_type": t.txn_type.value,
        "category": t.category,
        "raw_description": t.raw_description,
        "normalized_description": t.normalized_description,
        "archived": t.archived,
    }


class TransactionCreate(BaseModel):
    account_id: int
    date: date_type
    amount: Decimal  # native, signed (negative=outflow, positive=inflow)
    currency: str = Field(min_length=3, max_length=3)
    raw_description: str = ""
    txn_type: TxnType = TxnType.other
    category: str | None = None  # if omitted, the cascade decides


@router.post("", status_code=201)
def create_transaction(payload: TransactionCreate, db: Session = Depends(get_session)):
    """Manual transaction creation. Mirrors the import path: normalize the
    description, capture historical FX, and run the categorization cascade if
    the user didn't supply a category. Uses a synthetic dedup_hash so manual
    rows never collide with each other or with future CSV imports.
    """
    if db.get(Account, payload.account_id) is None:
        raise HTTPException(404, f"account {payload.account_id} not found")

    currency = payload.currency.upper()
    normalized = normalize_description(payload.raw_description)

    if payload.category is not None:
        valid = {c.name for c in db.execute(select(Category)).scalars().all()}
        if payload.category not in valid:
            raise HTTPException(400, f"unknown category {payload.category!r}; valid: {sorted(valid)}")
        category = payload.category
    else:
        category = classify(db, normalized).category

    fx_rate = to_base(db, Decimal("1"), currency, payload.date)
    txn = Transaction(
        account_id=payload.account_id,
        date=payload.date,
        amount=payload.amount,
        currency=currency,
        fx_rate_to_base=fx_rate,
        txn_type=payload.txn_type,
        category=category,
        raw_description=payload.raw_description,
        normalized_description=normalized,
        # Manual rows aren't being deduplicated against anything — synthesize a
        # unique hash so they can't collide with importer rows or each other.
        dedup_hash=f"manual:{uuid.uuid4().hex}",
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return _serialize(txn)


@router.delete("/{txn_id}", status_code=204)
def delete_transaction(txn_id: int, db: Session = Depends(get_session)):
    """Hard delete. Prefer POST /archive — this is irreversible."""
    t = db.get(Transaction, txn_id)
    if t is None:
        raise HTTPException(404, "transaction not found")
    if not t.archived:
        _adjust_email_balance(db, t, -t.amount)
    db.delete(t)
    db.commit()


@router.post("/{txn_id}/archive")
def archive_transaction(txn_id: int, db: Session = Depends(get_session)):
    """Soft-delete. Hides from totals + default lists but row is preserved so the
    user can restore via /unarchive if they archived something by mistake.
    """
    t = db.get(Transaction, txn_id)
    if t is None:
        raise HTTPException(404, "transaction not found")
    if not t.archived:
        t.archived = True
        _adjust_email_balance(db, t, -t.amount)
    db.commit()
    return {"id": t.id, "archived": True}


@router.post("/{txn_id}/unarchive")
def unarchive_transaction(txn_id: int, db: Session = Depends(get_session)):
    t = db.get(Transaction, txn_id)
    if t is None:
        raise HTTPException(404, "transaction not found")
    if t.archived:
        t.archived = False
        _adjust_email_balance(db, t, t.amount)
    db.commit()
    return {"id": t.id, "archived": False}


class DateUpdate(BaseModel):
    date: date_type


@router.patch("/{txn_id}/date")
def update_date(txn_id: int, payload: DateUpdate, db: Session = Depends(get_session)):
    """Move a transaction to a different date. Re-fetches fx_rate_to_base for the new
    date so CLP totals stay consistent — leaving the rate frozen would silently skew
    monthly spending whenever a user corrects an import date.
    """
    txn = db.get(Transaction, txn_id)
    if txn is None:
        raise HTTPException(404, "transaction not found")

    txn.date = payload.date
    txn.fx_rate_to_base = to_base(db, Decimal("1"), txn.currency, payload.date)
    db.commit()
    db.refresh(txn)
    return {
        "id": txn.id,
        "date": txn.date.isoformat(),
        "fx_rate_to_base": str(txn.fx_rate_to_base),
        "amount_in_base": str(Decimal(str(txn.amount)) * Decimal(str(txn.fx_rate_to_base))),
    }


class AmountUpdate(BaseModel):
    amount: Decimal  # native, signed (negative=outflow, positive=inflow)


@router.patch("/{txn_id}/amount")
def update_amount(txn_id: int, payload: AmountUpdate, db: Session = Depends(get_session)):
    """Edit the native amount on an existing transaction. Date / currency /
    fx_rate are left untouched — only the amount changes, so amount_in_base
    recomputes from the same captured rate.
    """
    txn = db.get(Transaction, txn_id)
    if txn is None:
        raise HTTPException(404, "transaction not found")
    if not txn.archived:
        _adjust_email_balance(db, txn, payload.amount - txn.amount)
    txn.amount = payload.amount
    db.commit()
    db.refresh(txn)
    return {
        "id": txn.id,
        "amount": str(txn.amount),
        "amount_in_base": str(Decimal(str(txn.amount)) * Decimal(str(txn.fx_rate_to_base))),
    }


class DescriptionUpdate(BaseModel):
    raw_description: str


@router.patch("/{txn_id}/description")
def update_description(txn_id: int, payload: DescriptionUpdate, db: Session = Depends(get_session)):
    """Edit the raw description of a transaction. Re-normalizes so the display
    name and categorization key both reflect the new wording. Category is left
    untouched — the user can update it separately if needed.
    """
    txn = db.get(Transaction, txn_id)
    if txn is None:
        raise HTTPException(404, "transaction not found")
    txn.raw_description = payload.raw_description
    txn.normalized_description = normalize_description(payload.raw_description)
    db.commit()
    db.refresh(txn)
    return {
        "id": txn.id,
        "raw_description": txn.raw_description,
        "normalized_description": txn.normalized_description,
    }


class CategoryUpdate(BaseModel):
    category: str
    propagate: bool = True  # also write a manual rule so future repeats inherit it


@router.patch("/{txn_id}/category")
def update_category(txn_id: int, payload: CategoryUpdate, db: Session = Depends(get_session)):
    txn = db.get(Transaction, txn_id)
    if txn is None:
        raise HTTPException(404, "transaction not found")

    valid = {c.name for c in db.execute(select(Category)).scalars().all()}
    if payload.category not in valid:
        raise HTTPException(400, f"unknown category {payload.category!r}; valid: {sorted(valid)}")

    txn.category = payload.category
    if payload.propagate:
        apply_manual_correction(db, txn.normalized_description, payload.category)
    db.commit()
    db.refresh(txn)
    return {
        "id": txn.id,
        "category": txn.category,
        "normalized_description": txn.normalized_description,
        "propagated": payload.propagate,
    }
