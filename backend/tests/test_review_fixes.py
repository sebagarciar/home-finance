"""Tests for the code-review polish pass: date-range validation, upload size
cap, and batch rule-cache consistency in the categorization cascade."""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db import Base, get_session
from app.main import app
from app.models import CategoryRule
from app.seeds.defaults import seed


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with TestingSession() as s:
        seed(s)

    def override():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_spending_summary_rejects_inverted_range(client):
    r = client.get("/spending/summary", params={"start": "2026-12-31", "end": "2026-01-01"})
    assert r.status_code == 422
    assert "start must be <= end" in r.text


def test_networth_history_rejects_inverted_range(client):
    r = client.get("/networth/history", params={"start": "2026-12-31", "end": "2026-01-01"})
    assert r.status_code == 422


def test_spending_summary_allows_equal_bounds(client):
    r = client.get("/spending/summary", params={"start": "2026-01-01", "end": "2026-01-01"})
    assert r.status_code == 200


def test_import_rejects_oversized_upload(client, monkeypatch):
    # Shrink the cap so we don't have to build a 10 MB payload.
    get_settings.cache_clear()
    monkeypatch.setattr(get_settings(), "max_upload_bytes", 10, raising=False)
    big = io.BytesIO(b"x" * 50)
    r = client.post(
        "/import/preview",
        data={"parser": "revolut", "account_id": "1"},
        files={"file": ("statement.csv", big, "text/csv")},
    )
    assert r.status_code == 413
    get_settings.cache_clear()


def test_classify_batch_cache_no_duplicate_rules(db):
    """A repeated merchant within one batch must produce exactly one rule row,
    not collide or duplicate, when sharing the in-memory rule cache."""
    seed(db)
    from app.services.categorization.cascade import classify, load_rules

    rules = load_rules(db)
    # "wetaca" is a seeded Restaurant rule; the contains-match writes back a
    # learned exact rule. Running it twice in the same batch must be stable.
    first = classify(db, "wetaca madrid centro", rules)
    second = classify(db, "wetaca madrid centro", rules)
    assert first.category == second.category == "Restaurant"

    db.flush()
    matches = db.execute(
        select(CategoryRule).where(CategoryRule.normalized_description == "wetaca madrid centro")
    ).scalars().all()
    assert len(matches) == 1
