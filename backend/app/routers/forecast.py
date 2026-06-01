"""Monte Carlo forecast endpoint.

POST /forecast/run — runs the simulation off the seeded `assumptions` row, with a
few inline run controls (horizon, real/nominal, target, life events). Full
assumptions editing is Phase 7; this router reads, it does not mutate.

Output is base currency (CLP); the EUR display toggle is applied client-side.
"""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_session
from ..services.forecast import run_forecast

router = APIRouter(prefix="/forecast", tags=["forecast"])


class LifeEventIn(BaseModel):
    month: int = Field(ge=1, description="1-based month offset from today")
    amount: Decimal
    currency: str = Field(default="CLP", min_length=3, max_length=3)
    label: str | None = None


class ForecastRequest(BaseModel):
    horizon_years: int | None = Field(default=None, ge=1, le=60)
    real: bool = True
    target: Decimal | None = None
    n_paths: int = Field(default=10000, ge=200, le=50000)
    seed: int | None = None
    life_events: list[LifeEventIn] = Field(default_factory=list)


class Band(BaseModel):
    month: int
    date: str
    p10: float
    p25: float
    p50: float
    p75: float
    p90: float


class Terminal(BaseModel):
    p10: float
    p50: float
    p90: float


class ForecastResponse(BaseModel):
    currency: str
    real: bool
    n_paths: int
    horizon_years: int
    start_networth: float
    bands: list[Band]
    terminal: Terminal
    target: float | None
    prob_hit_target: float | None


@router.post("/run", response_model=ForecastResponse)
def post_run(req: ForecastRequest, db: Session = Depends(get_session)) -> dict:
    overrides = {
        "horizon_years": req.horizon_years,
        "real": req.real,
        "target": req.target,
        "life_events": [ev.model_dump() for ev in req.life_events],
    }
    return run_forecast(db, overrides=overrides, n_paths=req.n_paths, seed=req.seed)
