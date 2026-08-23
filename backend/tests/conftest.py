from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import get_current_user
from app.db import Base
from app.main import app
from app.services.fx.provider import FxProvider


@pytest.fixture(autouse=True)
def _auth_override():
    """Every router except /health and /auth is behind get_current_user; tests
    exercise the endpoints, not the auth layer, so bypass it globally."""
    app.dependency_overrides[get_current_user] = lambda: "test"
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


class StubFxProvider(FxProvider):
    """Deterministic FX for tests. Rates keyed on (date, base, quote)."""

    def __init__(self, rates: dict[tuple[date | None, str, str], Decimal]):
        self.rates = rates
        self.calls: list[tuple[date, str, str]] = []

    def fetch(self, on_date, base, quote):
        self.calls.append((on_date, base, quote))
        if base == quote:
            return Decimal("1")
        if (on_date, base, quote) in self.rates:
            return self.rates[(on_date, base, quote)]
        if (None, base, quote) in self.rates:
            return self.rates[(None, base, quote)]
        raise LookupError(f"no stub rate for {base}->{quote} on {on_date}")


@pytest.fixture
def stub_fx():
    return StubFxProvider
