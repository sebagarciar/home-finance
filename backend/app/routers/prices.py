"""Price-source lookups (provider-specific resolvers).

`GET /prices/fintual/search?q=` resolves a Fintual fund name to its series and
ready-to-use `FINTUAL:<id>` tickers, so a holding can be added by name instead
of memorizing an id.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..services.prices.fintual import search_fintual_funds
from ..services.prices.provider import PriceLookupError

router = APIRouter(prefix="/prices", tags=["prices"])


@router.get("/fintual/search")
def fintual_search(q: str = Query(..., min_length=2)):
    try:
        return {"results": search_fintual_funds(q)}
    except PriceLookupError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
