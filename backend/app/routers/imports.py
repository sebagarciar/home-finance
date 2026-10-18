from __future__ import annotations

import io
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_session
from ..services.email_ingest.scheduler import parse_times
from ..services.email_ingest.sync import (
    EmailSyncConfigError,
    get_status,
    resolve_account_id,
    run_email_sync,
)
from ..services.importers import get_parser
from ..services.importers.service import commit_import, preview_import

router = APIRouter(prefix="/import", tags=["import"])


async def _read_capped(file: UploadFile) -> bytes:
    """Read an upload, rejecting anything over the configured size cap so a
    runaway file can't exhaust memory."""
    limit = get_settings().max_upload_bytes
    contents = await file.read(limit + 1)
    if len(contents) > limit:
        raise HTTPException(413, f"File exceeds {limit} byte limit")
    return contents


@router.post("/preview")
async def preview(
    parser: str = Form(...),
    account_id: int = Form(...),
    statement_year: int | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
):
    kwargs = {"statement_year": statement_year} if parser == "scotiabank_cl" and statement_year else {}
    try:
        p = get_parser(parser, **kwargs)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    contents = await _read_capped(file)
    parsed = p.parse(io.BytesIO(contents))
    previews = preview_import(db, account_id, parsed)
    return {
        "total": len(previews),
        "duplicates": sum(1 for x in previews if x.is_duplicate),
        "rows": [
            {
                "date": x.parsed.date.isoformat(),
                "amount": str(x.parsed.amount),
                "currency": x.parsed.currency,
                "txn_type": x.parsed.txn_type.value,
                "raw_description": x.parsed.raw_description,
                "normalized": x.normalized,
                "is_duplicate": x.is_duplicate,
            }
            for x in previews
        ],
    }


@router.post("/commit")
async def commit(
    parser: str = Form(...),
    account_id: int = Form(...),
    force: bool = Form(False),
    statement_year: int | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
):
    kwargs = {"statement_year": statement_year} if parser == "scotiabank_cl" and statement_year else {}
    try:
        p = get_parser(parser, **kwargs)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    contents = await _read_capped(file)
    parsed = p.parse(io.BytesIO(contents))
    previews = preview_import(db, account_id, parsed)
    result = commit_import(db, account_id, previews, force=force)
    return {
        "imported": result.imported,
        "duplicates_skipped": result.duplicates_skipped,
    }


@router.post("/email/sync")
def email_sync(
    account_id: int | None = None,
    since: date | None = None,
    limit: int = 200,
    db: Session = Depends(get_session),
):
    """Pull Santander ES notification emails over IMAP and ingest the parseable
    ones as provisional (source="email") transactions. Idempotent: re-running
    only adds genuinely new rows. The monthly .xlsx statement supersedes these."""
    try:
        target_account = resolve_account_id(account_id)
    except EmailSyncConfigError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    r = run_email_sync(db, target_account, since=since, limit=limit)
    return {
        "fetched": r.fetched,
        "parsed": r.parsed,
        "imported": r.imported,
        "skipped": r.skipped,
        "recategorized": r.recategorized,
    }


@router.get("/email/status")
def email_status(db: Session = Depends(get_session)):
    """Outcome of the latest email sync (scheduled or manual)."""
    st = get_status(db)
    db.commit()

    def _iso(dt: datetime | None) -> str | None:
        if dt is None:
            return None
        return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).isoformat()

    return {
        "scheduled_times": [
            t.strftime("%H:%M") for t in parse_times(get_settings().email_sync_times)
        ],
        "last_run_at": _iso(st.last_run_at),
        "last_ok": st.last_ok,
        "last_error": st.last_error,
        "last_fetched": st.last_fetched,
        "last_imported": st.last_imported,
    }
