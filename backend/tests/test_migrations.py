"""In-process Alembic upgrade used at app startup."""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import create_engine, inspect

from app.migrations import upgrade_to_head


def test_upgrade_to_head_builds_schema_and_is_idempotent(tmp_path: Path):
    url = f"sqlite:///{tmp_path / 'startup.db'}"
    upgrade_to_head(url)
    upgrade_to_head(url)  # second run is a no-op, as on every restart
    eng = create_engine(url)
    tables = set(inspect(eng).get_table_names())
    eng.dispose()
    assert {"alembic_version", "transactions", "holdings", "investment_trades"} <= tables


def test_upgrade_to_head_leaves_app_loggers_alone(tmp_path: Path):
    log = logging.getLogger("uvicorn.error")
    log.disabled = False
    upgrade_to_head(f"sqlite:///{tmp_path / 'log.db'}")
    assert log.disabled is False
