from datetime import date as date_type
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_session
from ..models import Transaction
from ..models.fx import FxRate
from ..services.fx import get_rate
from ..services.fx.provider import get_provider

router = APIRouter(prefix="/fx", tags=["fx"])

# fx_rates / transactions store Numeric(20,10); quantize provider output to the
# same precision so a re-run compares equal and reports "unchanged".
_RATE_PRECISION = Decimal("0.0000000001")


@router.get("")
def fx_rate(
    base: str = Query(..., min_length=3, max_length=3),
    quote: str = Query(..., min_length=3, max_length=3),
    on_date: date_type | None = Query(None, alias="date"),
    db: Session = Depends(get_session),
):
    try:
        rate = get_rate(db, on_date, base.upper(), quote.upper())
    except LookupError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {
        "base": base.upper(),
        "quote": quote.upper(),
        "date": (on_date or date_type.today()).isoformat(),
        "rate": str(rate),
    }


@router.post("/rerate")
def rerate_transactions(db: Session = Depends(get_session)):
    """Backfill historical FX onto existing transactions.

    Refetches the rate for every distinct (date, currency) among
    foreign-currency transactions (archived included) and rewrites
    `fx_rate_to_base`. Deliberately bypasses the fx_rates cache and upserts it,
    because rows cached before the fallback-no-persist fix may hold approximate
    fallback rates. Idempotent: a second run reports everything unchanged.
    """
    base = get_settings().base_currency
    provider = get_provider()  # one instance, so per-year series caching pays off

    txns = list(
        db.execute(select(Transaction).where(Transaction.currency != base)).scalars().all()
    )
    fetched: dict[tuple[date_type, str], Decimal] = {}
    failures: list[str] = []
    for on, ccy in sorted({(t.date, t.currency) for t in txns}):
        try:
            rate = provider.fetch(on, ccy, base).quantize(_RATE_PRECISION)
        except Exception as e:  # noqa: BLE001 — collect per-pair failures, don't abort the batch
            failures.append(f"{ccy}->{base} on {on.isoformat()}: {e}")
            continue
        fetched[(on, ccy)] = rate
        row = db.execute(
            select(FxRate).where(
                FxRate.date == on,
                FxRate.base_currency == ccy,
                FxRate.quote_currency == base,
            )
        ).scalar_one_or_none()
        if row is None:
            db.add(FxRate(date=on, base_currency=ccy, quote_currency=base, rate=rate))
        else:
            row.rate = rate

    updated = unchanged = skipped = 0
    for t in txns:
        new_rate = fetched.get((t.date, t.currency))
        if new_rate is None:
            skipped += 1
            continue
        if Decimal(str(t.fx_rate_to_base)).quantize(_RATE_PRECISION) == new_rate:
            unchanged += 1
        else:
            t.fx_rate_to_base = new_rate
            updated += 1
    db.commit()

    return {
        "transactions_scanned": len(txns),
        "updated": updated,
        "unchanged": unchanged,
        "skipped": skipped,
        "failures": failures,
    }
