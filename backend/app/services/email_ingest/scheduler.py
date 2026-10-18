"""Background email sync at fixed local times, run from the FastAPI lifespan.

A plain asyncio loop (no scheduler dependency) that wakes every minute and runs
the sync when a configured slot has passed since the last run. Because it compares
against the *recorded* last run instead of waiting on a timer, a slot missed while
the Mac slept (or the backend was down) fires on the next wake/start. Work runs in
a worker thread so IMAP and Ollama calls don't block the event loop; the loop is
sequential, so runs never overlap.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, time, timedelta

from ...config import get_settings
from ...db import SessionLocal
from .sync import EmailSyncConfigError, get_status, record_error, resolve_account_id, run_email_sync

logger = logging.getLogger(__name__)

# Delay the first check so `--reload` restarts don't log into IMAP on every edit.
INITIAL_DELAY_SECONDS = 15
CHECK_EVERY_SECONDS = 60
# After a failed run, retry sooner than the next slot.
RETRY_AFTER = timedelta(minutes=15)


def parse_times(raw: str) -> list[time]:
    out: list[time] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        hh, _, mm = part.partition(":")
        out.append(time(int(hh), int(mm or 0)))
    return sorted(out)


def latest_slot(now: datetime, times: list[time]) -> datetime | None:
    """Most recent configured slot at or before `now` (local, tz-aware)."""
    if not times:
        return None
    for day_offset in (0, 1):
        day = (now - timedelta(days=day_offset)).date()
        past = [
            datetime.combine(day, t).astimezone()
            for t in times
            if datetime.combine(day, t).astimezone() <= now
        ]
        if past:
            return max(past)
    return None


def is_due(
    now: datetime, last_run_at: datetime | None, last_ok: bool | None, times: list[time]
) -> bool:
    slot = latest_slot(now, times)
    if slot is None:
        return False
    if last_run_at is None:
        return True
    if last_run_at.tzinfo is None:
        last_run_at = last_run_at.replace(tzinfo=UTC)
    if last_run_at < slot:
        return True
    return last_ok is False and now - last_run_at >= RETRY_AFTER


def _check_and_run(times: list[time]) -> None:
    try:
        account_id = resolve_account_id()
    except EmailSyncConfigError as exc:
        logger.info("Scheduled email sync skipped: %s", exc.detail)
        return
    with SessionLocal() as db:
        st = get_status(db)
        db.commit()
        if not is_due(datetime.now().astimezone(), st.last_run_at, st.last_ok, times):
            return
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


async def email_sync_loop(times: list[time]) -> None:
    await asyncio.sleep(INITIAL_DELAY_SECONDS)
    while True:
        try:
            await asyncio.to_thread(_check_and_run, times)
        except Exception:  # noqa: BLE001
            logger.exception("Email sync scheduler tick failed")
        await asyncio.sleep(CHECK_EVERY_SECONDS)


def start_email_sync() -> asyncio.Task[None] | None:
    times = parse_times(get_settings().email_sync_times)
    if not times:
        return None
    logger.info("Email sync scheduled daily at %s", ", ".join(t.strftime("%H:%M") for t in times))
    return asyncio.create_task(email_sync_loop(times))
