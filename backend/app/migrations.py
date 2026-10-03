"""Run Alembic migrations from inside the app (used at startup).

Alembic is the source of truth for schema; the app never `create_all`s the
real database. Tests still build in-memory schemas from `Base.metadata`.
"""
from __future__ import annotations

from pathlib import Path

from alembic.config import Config

from alembic import command

_BACKEND_DIR = Path(__file__).resolve().parents[1]


def upgrade_to_head(database_url: str | None = None) -> None:
    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    # Absolute so startup works regardless of the process's cwd.
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    # env.py's fileConfig() would disable uvicorn's already-configured loggers.
    cfg.attributes["configure_logging"] = False
    if database_url is not None:
        cfg.attributes["database_url"] = database_url
    command.upgrade(cfg, "head")
