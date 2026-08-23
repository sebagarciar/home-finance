from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Category

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("")
def list_categories(db: Session = Depends(get_session)):
    rows = db.execute(select(Category).order_by(Category.name)).scalars().all()
    return [
        {"id": c.id, "name": c.name, "is_system": c.is_system, "is_income": c.is_income}
        for c in rows
    ]
