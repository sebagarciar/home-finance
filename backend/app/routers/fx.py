from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_session
from ..services.fx import get_rate

router = APIRouter(prefix="/fx", tags=["fx"])


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
