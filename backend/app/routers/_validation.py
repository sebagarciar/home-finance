"""Shared request-validation helpers for routers."""
from __future__ import annotations

from datetime import date as date_type

from fastapi import HTTPException


def validate_date_range(start: date_type | None, end: date_type | None) -> None:
    """Reject an inverted date range. When both bounds are given and start > end
    the query would silently return nothing, masking a caller mistake."""
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=422, detail="start must be <= end")
