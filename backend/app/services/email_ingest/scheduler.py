"""Background email sync, run from the FastAPI lifespan.

A plain asyncio loop (no scheduler dependency). The work runs in a worker
thread so IMAP and Ollama calls don't block the event loop, and the loop is
sequential, so runs can never overlap. It lives in the backend process: it only
fires while the backend is up and the machine is awake, and the first run after
a sleep catches up on everything missed (fetch is idempotent).
"""
from __future__ import annotations

import asyncio
import logging

from ...config import get_settings
from ...db import SessionLocal
from .sync import EmailSyncConfigError, record_error, resolve_account_id, run_email_sync

logger = logging.getLogger(__name__)

# Delay the first run so `--reload` restarts don't log into IMAP on every edit.
INITIAL_DELAY_SECONDS = 15


def _run_once() -> None:
    try:
        account_id = resolve_account_id()
    except EmailSyncConfigError as exc:
        logger.info("Scheduled email sync skipped: %s", exc.detail)
        return
    with SessionLocal() as db:
        try:
            result = run_email_sync(db, account_id)
        except Exception as exc:  # noqa: BLE001 — a background job must not die
            logger.exception("Scheduled email sync failed")
            record_error(db, f"{type(exc).__name__}: {exc}")
            return
    logger.info(
        "Scheduled email sync: fetched=%d imported=%d recategorized=%d",
        result.fetched, result.imported, result.recategorized,
    )


async def email_sync_loop(interval_minutes: int) -> None:
    await asyncio.sleep(INITIAL_DELAY_SECONDS)
    while True:
        await asyncio.to_thread(_run_once)
        await asyncio.sleep(interval_minutes * 60)


def start_email_sync() -> asyncio.Task[None] | None:
    interval = get_settings().email_sync_interval_minutes
    if interval <= 0:
        return None
    logger.info("Email sync scheduled every %d min", interval)
    return asyncio.create_task(email_sync_loop(interval))
