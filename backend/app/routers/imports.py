from __future__ import annotations

import io
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_session
from ..services.email_ingest import archive_santander_emails, fetch_santander_emails
from ..services.importers import get_parser
from ..services.importers.santander_es_email import parse_santander_email
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
    settings = get_settings()
    if not settings.gmail_user or not settings.gmail_app_password:
        raise HTTPException(503, "Gmail credentials not configured (set GMAIL_USER / GMAIL_APP_PASSWORD)")

    target_account = account_id if account_id is not None else settings.santander_email_account_id
    if target_account is None:
        raise HTTPException(400, "No account_id given and SANTANDER_EMAIL_ACCOUNT_ID is unset")

    uid_raw_pairs = fetch_santander_emails(since=since, limit=limit)
    parsed_pairs: list[tuple[str, object]] = [
        (uid, p)
        for uid, raw in uid_raw_pairs
        if (p := parse_santander_email(raw)) is not None
    ]
    parsed_uids = [uid for uid, _ in parsed_pairs]
    parsed_txns = [p for _, p in parsed_pairs]  # type: ignore[misc]
    previews = preview_import(db, target_account, parsed_txns)
    result = commit_import(db, target_account, previews, source="email")
    # Archive only emails that were parseable; leave unrecognised ones in INBOX.
    archive_santander_emails(parsed_uids)
    return {
        "fetched": len(uid_raw_pairs),
        "parsed": len(parsed_txns),
        "imported": result.imported,
        "skipped": result.duplicates_skipped,
    }
