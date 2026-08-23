"""Persist parsed transactions: dedup, FX capture, write-back."""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ...models import Account, Transaction
from ..categorization.cascade import classify, load_rules
from ..categorization.normalize import normalize_description
from ..fx import to_base
from .base import ParsedTxn


def compute_dedup_hash(account_id: int, parsed: ParsedTxn, normalized: str) -> str:
    # amount * 10000 to fold Numeric(18,4) into an integer-stable string
    amount_cents = int((parsed.amount * Decimal(10000)).to_integral_value())
    payload = f"{account_id}|{parsed.date.isoformat()}|{amount_cents}|{normalized}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class ImportPreview:
    parsed: ParsedTxn
    normalized: str
    dedup_hash: str
    is_duplicate: bool


@dataclass
class ImportResult:
    imported: int
    duplicates_skipped: int
    duplicates: list[ImportPreview]


def preview_import(db: Session, account_id: int, parsed_rows: list[ParsedTxn]) -> list[ImportPreview]:
    """Return previews flagging which incoming rows would be duplicates."""
    previews: list[ImportPreview] = []
    seen_in_batch: set[str] = set()
    for p in parsed_rows:
        normalized = normalize_description(p.raw_description)
        h = compute_dedup_hash(account_id, p, normalized)
        existing = db.execute(
            select(Transaction.id).where(Transaction.dedup_hash == h)
        ).scalar_one_or_none()
        is_dup = existing is not None or h in seen_in_batch
        seen_in_batch.add(h)
        previews.append(ImportPreview(parsed=p, normalized=normalized, dedup_hash=h, is_duplicate=is_dup))
    return previews


def commit_import(
    db: Session,
    account_id: int,
    previews: list[ImportPreview],
    *,
    force: bool = False,
    source: str = "statement",
) -> ImportResult:
    """Persist non-duplicates (or all when force=True). Captures FX rate per row.

    `source` records each row's origin ("statement" for uploaded bank files,
    "email" for provisional rows from transaction-notification emails). A
    statement import is authoritative: it archives any overlapping "email" rows
    for this account in the imported date range, so the statement supersedes the
    provisional email rows it covers (auth amounts, missing fees, etc.).
    """
    account = db.get(Account, account_id)

    # Statement imports win over provisional email rows they cover. Archive (not
    # delete) so the rows stay restorable; archived rows are already excluded
    # from the dashboard and net-worth.
    if source == "statement" and previews:
        dates = [p.parsed.date for p in previews]
        min_date, max_date = min(dates), max(dates)

        # Fetch email rows before bulk-archiving so we can reverse the balance
        # deltas they previously applied to account.current_balance.
        if account is not None:
            email_rows = db.execute(
                select(Transaction).where(
                    Transaction.account_id == account_id,
                    Transaction.source == "email",
                    Transaction.archived.is_(False),
                    Transaction.date >= min_date,
                    Transaction.date <= max_date,
                    Transaction.currency == account.native_currency,
                )
            ).scalars().all()
            if email_rows:
                reversal = sum(r.amount for r in email_rows)
                account.current_balance -= reversal
                account.balance_updated_at = datetime.now(UTC)

        db.execute(
            update(Transaction)
            .where(
                Transaction.account_id == account_id,
                Transaction.source == "email",
                Transaction.archived.is_(False),
                Transaction.date >= min_date,
                Transaction.date <= max_date,
            )
            .values(archived=True)
        )

    imported = 0
    skipped = 0
    duplicates: list[ImportPreview] = []
    # Load category rules once for the whole batch; classify() mutates this list
    # on write-back so repeat merchants in the same import hit the in-memory
    # cache instead of re-querying the rules table per row.
    rules = load_rules(db)
    email_balance_delta = Decimal("0")
    for prev in previews:
        if prev.is_duplicate and not force:
            skipped += 1
            duplicates.append(prev)
            continue
        # Capture historical FX rate at the transaction's date.
        fx_rate = to_base(db, Decimal("1"), prev.parsed.currency, prev.parsed.date)
        # Cascade runs on every row regardless of txn_type. Internal moves the
        # user wants out of the dashboard are removed via archive, not by type.
        category = classify(db, prev.normalized, rules).category
        # Force-inserting a duplicate needs a distinct hash to satisfy the unique
        # constraint — use a random UUID hex (32 chars, fits String(64)).
        dedup_hash = uuid.uuid4().hex if prev.is_duplicate and force else prev.dedup_hash
        db.add(
            Transaction(
                account_id=account_id,
                date=prev.parsed.date,
                amount=prev.parsed.amount,
                currency=prev.parsed.currency,
                fx_rate_to_base=fx_rate,
                txn_type=prev.parsed.txn_type,
                category=category,
                raw_description=prev.parsed.raw_description,
                normalized_description=prev.normalized,
                dedup_hash=dedup_hash,
                source=source,
            )
        )
        # Accumulate native-currency delta for email imports so we can update
        # account.current_balance without summing all historical transactions.
        if source == "email" and account is not None and prev.parsed.currency == account.native_currency:
            email_balance_delta += prev.parsed.amount
        imported += 1

    # Apply the running delta to the account balance for email-sourced imports.
    # Statement-sourced imports don't auto-adjust — the user sets the balance
    # manually from the statement's closing figure.
    if source == "email" and account is not None and email_balance_delta:
        account.current_balance += email_balance_delta
        account.balance_updated_at = datetime.now(UTC)

    db.commit()
    return ImportResult(imported=imported, duplicates_skipped=skipped, duplicates=duplicates)
