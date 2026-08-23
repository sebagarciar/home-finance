from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth import get_current_user
from .config import get_settings
from .db import Base, SessionLocal, engine
from .routers import (
    accounts,
    assumptions,
    auth,
    categories,
    forecast,
    fx,
    health,
    holdings,
    imports,
    networth,
    portfolio_health,
    prices,
    spending,
    transactions,
)
from .seeds.defaults import seed


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Phase 1: create tables directly so the app runs end-to-end without alembic upgrade.
    # Alembic migrations are the source of truth for prod-style deploys.
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed(db)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Home Finance API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    _protected = [Depends(get_current_user)]
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(fx.router, dependencies=_protected)
    app.include_router(imports.router, dependencies=_protected)
    app.include_router(transactions.router, dependencies=_protected)
    app.include_router(accounts.router, dependencies=_protected)
    app.include_router(categories.router, dependencies=_protected)
    app.include_router(spending.router, dependencies=_protected)
    app.include_router(holdings.router, dependencies=_protected)
    app.include_router(networth.router, dependencies=_protected)
    app.include_router(prices.router, dependencies=_protected)
    app.include_router(forecast.router, dependencies=_protected)
    app.include_router(assumptions.router, dependencies=_protected)
    app.include_router(portfolio_health.router, dependencies=_protected)
    return app


app = create_app()
