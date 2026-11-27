"""Needs-attention checks: computed signals that the data has gone stale.

Everything here is derived from rows that already exist; nothing new is
entered. Each check returns `Item`s with a stable `key`, used for
dismissals. Keys embed the state they were raised on (a balance's update
date, a count), so a dismissed item comes back once that state changes.

Read-only and network-free: prices are judged from `price_cache` and the
manual-price timestamp, never by calling a provider.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ...models import Account, AccountType, Holding, PriceCacheEntry, Transaction

STALE_BALANCE_DAYS = 30
STALE_PRICE_CACHE_DAYS = 7
STALE_MANUAL_PRICE_DAYS = 30
UNCATEGORIZED_WINDOW_DAYS = 183  # ~6 months, same horizon as "spend vs usual"
TRANSFER_WINDOW_DAYS = 120
TRANSFER_MAX_GAP_DAYS = 3
FALLBACK_CATEGORY = "Other"


@dataclass
class Item:
    kind: str  # stale_balance | statement_missing | uncategorized | transfer_pair | stale_price
    key: str
    data: dict[str, Any] = field(default_factory=dict)


def stale_balances(db: Session, today: date) -> list[Item]:
    """Accounts whose manual cash balance hasn't been touched in a month.

    Skipped, because there is no balance to go stale:
    - zero and never set: the seeded "Manual" catch-all, or an account created
      with no balance (creating one with 0 doesn't stamp `balance_updated_at`);
    - investment accounts holding no cash: their value is in holdings, which
      `stale_prices` covers.
    """
    items: list[Item] = []
    for a in db.execute(select(Account).order_by(Account.id)).scalars():
        updated = a.balance_updated_at.date() if a.balance_updated_at else None
        if not a.current_balance and (updated is None or a.type is AccountType.investment):
            continue
        age = (today - updated).days if updated else None
        if age is not None and age <= STALE_BALANCE_DAYS:
            continue
        items.append(Item(
            kind="stale_balance",
            key=f"stale_balance:{a.id}:{updated.isoformat() if updated else 'never'}",
            data={
                "account_id": a.id,
                "account_name": a.name,
                "currency": a.native_currency,
                "current_balance": str(a.current_balance),
                "updated_on": updated.isoformat() if updated else None,
                "age_days": age,
            },
        ))
    return items


def missing_statements(db: Session, today: date) -> list[Item]:
    """Past months covered only by provisional email rows.

    A statement import archives the overlapping email rows, so a closed month
    that still has live email rows and no statement rows was never statemented.
    Months covered by bank-sync rows count as complete: the bank's booked rows
    are final, so leftover email rows there are not a missing-statement signal.
    The current month is skipped: its statement doesn't exist yet.
    """
    month_start = today.replace(day=1)
    email_rows = db.execute(
        select(Transaction.account_id, Transaction.date).where(
            Transaction.source == "email",
            Transaction.archived.is_(False),
            Transaction.date < month_start,
        )
    ).all()
    counts: dict[tuple[int, date], int] = defaultdict(int)
    for account_id, d in email_rows:
        counts[(account_id, d.replace(day=1))] += 1

    names = dict(db.execute(select(Account.id, Account.name)).tuples().all())
    items: list[Item] = []
    for (account_id, start), n in sorted(counts.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        end = _next_month(start)
        has_statement = db.execute(
            select(Transaction.id).where(
                Transaction.account_id == account_id,
                Transaction.source.in_(("statement", "bank_sync")),
                Transaction.date >= start,
                Transaction.date < end,
            ).limit(1)
        ).first()
        if has_statement:
            continue
        month = start.strftime("%Y-%m")
        items.append(Item(
            kind="statement_missing",
            key=f"statement_missing:{account_id}:{month}",
            data={
                "account_id": account_id,
                "account_name": names.get(account_id, "?"),
                "month": month,
                "email_rows": n,
            },
        ))
    return items


def uncategorized(db: Session, today: date) -> list[Item]:
    """Recent rows the cascade couldn't place (fallback `Other`, or none)."""
    since = today - timedelta(days=UNCATEGORIZED_WINDOW_DAYS)
    n = db.execute(
        select(func.count(Transaction.id)).where(
            Transaction.archived.is_(False),
            Transaction.date >= since,
            or_(Transaction.category.is_(None), Transaction.category == FALLBACK_CATEGORY),
        )
    ).scalar_one()
    if not n:
        return []
    return [Item(
        kind="uncategorized",
        key=f"uncategorized:{n}",
        data={"count": n, "since": since.isoformat(), "category": FALLBACK_CATEGORY},
    )]


def transfer_pairs(db: Session, today: date) -> list[Item]:
    """Likely moves between the household's own accounts, not yet archived.

    A pair is an outflow and an inflow on *different* accounts, in the same
    currency, for exactly the same amount, at most 3 days apart. Cross-currency
    moves are left out on purpose: FX and fees make the amounts differ, and a
    loose match would flag ordinary purchases. Suggestions only; the user
    archives.
    """
    since = today - timedelta(days=TRANSFER_WINDOW_DAYS)
    rows = db.execute(
        select(Transaction).where(
            Transaction.archived.is_(False),
            Transaction.date >= since,
            Transaction.amount != 0,
        ).order_by(Transaction.date, Transaction.id)
    ).scalars().all()

    groups: dict[tuple[str, Decimal], list[Transaction]] = defaultdict(list)
    for t in rows:
        groups[(t.currency, abs(Decimal(str(t.amount))))].append(t)

    names = dict(db.execute(select(Account.id, Account.name)).tuples().all())
    items: list[Item] = []
    for (currency, amount), txns in groups.items():
        outs = [t for t in txns if t.amount < 0]
        ins = [t for t in txns if t.amount > 0]
        # Closest dates pair first, so a same-day match isn't stolen by an
        # earlier outflow that happens to be within the window too.
        edges = sorted(
            (abs((i.date - o.date).days), o.id, i.id, o, i)
            for o in outs for i in ins
            if i.account_id != o.account_id
            and abs((i.date - o.date).days) <= TRANSFER_MAX_GAP_DAYS
        )
        used: set[int] = set()
        for _, _, _, o, i in edges:
            if o.id in used or i.id in used:
                continue
            used.update((o.id, i.id))
            lo, hi = sorted((o.id, i.id))
            items.append(Item(
                kind="transfer_pair",
                key=f"transfer_pair:{lo}:{hi}",
                data={
                    "currency": currency,
                    "amount": str(amount),
                    "out": _txn(o, names),
                    "in": _txn(i, names),
                },
            ))
    items.sort(key=lambda it: it.data["out"]["date"], reverse=True)
    return items


def stale_prices(db: Session, today: date) -> list[Item]:
    """Holdings with no recent live quote and no recent manual price."""
    latest = dict(
        db.execute(
            select(PriceCacheEntry.ticker, func.max(PriceCacheEntry.date))
            .group_by(PriceCacheEntry.ticker)
        ).tuples().all()
    )
    items: list[Item] = []
    for h in db.execute(select(Holding).order_by(Holding.id)).scalars():
        live = latest.get(h.ticker.upper())
        manual = h.manual_price_updated_at.date() if (
            h.manual_price is not None and h.manual_price_updated_at
        ) else None
        if live and (today - live).days <= STALE_PRICE_CACHE_DAYS:
            continue
        if manual and (today - manual).days <= STALE_MANUAL_PRICE_DAYS:
            continue
        last = max((d for d in (live, manual) if d), default=None)
        items.append(Item(
            kind="stale_price",
            key=f"stale_price:{h.id}:{last.isoformat() if last else 'never'}",
            data={
                "holding_id": h.id,
                "ticker": h.ticker,
                "currency": h.price_currency,
                "manual_price": str(h.manual_price) if h.manual_price is not None else None,
                "last_priced_on": last.isoformat() if last else None,
            },
        ))
    return items


CHECKS = (stale_balances, missing_statements, transfer_pairs, uncategorized, stale_prices)


def collect(db: Session, today: date | None = None) -> list[Item]:
    today = today or date.today()
    return [item for check in CHECKS for item in check(db, today)]


def _next_month(d: date) -> date:
    return date(d.year + d.month // 12, d.month % 12 + 1, 1)


def _txn(t: Transaction, names: dict[int, str]) -> dict[str, Any]:
    return {
        "id": t.id,
        "account_id": t.account_id,
        "account_name": names.get(t.account_id, "?"),
        "date": t.date.isoformat(),
        "description": t.raw_description,
    }
