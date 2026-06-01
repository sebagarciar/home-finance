"""Net-worth endpoints.

- GET /networth/current — live computation (cash + holdings, both valued at
  current FX / current prices). Use for the dashboard tile.
- GET /networth/history — historical snapshots for the line chart.
- POST /networth/snapshot — take + persist a snapshot for today (or `date=`).
  Idempotent per date.
"""
from __future__ import annotations

from datetime import date as date_type

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import NetworthSnapshot
from ..services.networth import current_networth, take_snapshot
from ._validation import validate_date_range

router = APIRouter(prefix="/networth", tags=["networth"])


@router.get("/current")
def get_current(db: Session = Depends(get_session)):
    return current_networth(db)


@router.get("/history")
def get_history(
    start: date_type | None = Query(None),
    end: date_type | None = Query(None),
    db: Session = Depends(get_session),
):
    validate_date_range(start, end)
    q = select(NetworthSnapshot).order_by(NetworthSnapshot.date)
    if start is not None:
        q = q.where(NetworthSnapshot.date >= start)
    if end is not None:
        q = q.where(NetworthSnapshot.date <= end)
    rows = db.execute(q).scalars().all()
    return [
        {
            "date": r.date.isoformat(),
            "total_in_base": str(r.total_networth_in_base),
        }
        for r in rows
    ]


@router.post("/snapshot", status_code=201)
def post_snapshot(
    on_date: date_type | None = Query(None, alias="date"),
    db: Session = Depends(get_session),
):
    snap = take_snapshot(db, on_date)
    return {
        "date": snap.date.isoformat(),
        "total_in_base": str(snap.total_networth_in_base),
    }
