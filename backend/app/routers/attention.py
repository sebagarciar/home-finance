"""Needs-attention list for the Overview. See services/attention/checks.py."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import AttentionDismissal
from ..services.attention import collect

router = APIRouter(prefix="/attention", tags=["attention"])


class DismissIn(BaseModel):
    key: str = Field(min_length=1, max_length=128)


@router.get("")
def get_attention(db: Session = Depends(get_session)):
    dismissed = set(db.execute(select(AttentionDismissal.key)).scalars())
    items = collect(db)
    live = [i for i in items if i.key not in dismissed]
    return {
        "items": [{"kind": i.kind, "key": i.key, **i.data} for i in live],
        "dismissed": len(items) - len(live),
    }


@router.post("/dismiss", status_code=204)
def dismiss(payload: DismissIn, db: Session = Depends(get_session)):
    if db.get(AttentionDismissal, payload.key) is None:
        db.add(AttentionDismissal(key=payload.key))
        db.commit()


@router.delete("/dismissals", status_code=204)
def restore_all(db: Session = Depends(get_session)):
    db.execute(delete(AttentionDismissal))
    db.commit()
