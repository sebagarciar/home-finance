"""Net-worth computation + snapshotting.

Net-worth = cash + holdings, in base currency (CLP).
- Cash per account: `account.current_balance`, a manually-maintained figure in
  the account's native currency. We DO NOT derive cash from transaction sums —
  imported transaction history is partial, and using it would silently
  mis-state net worth. The user owns the balance; transactions just power the
  spending dashboard.
- Holdings: `price_holding` → quantity × current price (price_currency), then
  `to_base_current` to base. Two-hop conversion is explicit.
- Debt accounts: `current_balance` is treated as a positive loan amount and
  subtracted from net worth.

`take_snapshot(db, on_date=None)` persists a `networth_snapshots` row with the
total and a per-account / per-asset-class breakdown JSON. Idempotent per date
via the unique constraint — re-running on the same date overwrites the row.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Account, Holding, NetworthSnapshot
from ...services.fx.conversion import to_base_current
from ...services.prices import price_holding


def current_networth(db: Session) -> dict:
    """Live net-worth computation. Returns the same shape as snapshot.breakdown
    plus the total. Used by the dashboard tile and by `take_snapshot`.

    Each `by_account` row reports cash_in_base, holdings_in_base, and
    total_in_base — so an investment account with both a cash sweep and
    positions shows its full value at the account level (cash + holdings).
    """
    accounts = {a.id: a for a in db.execute(select(Account)).scalars().all()}

    by_asset_class: dict[str, Decimal] = defaultdict(Decimal)
    # Net worth grouped by the currency it is *denominated* in (cash by the
    # account's native currency, holdings by their price currency), in base.
    # Surfaces FX exposure for a CLP/EUR/USD household. Pure aggregation of
    # already-converted base values — no new FX math.
    by_currency: dict[str, Decimal] = defaultdict(Decimal)
    cash_total_base = Decimal("0")
    holdings_total_base = Decimal("0")
    holdings_by_account: dict[int, Decimal] = defaultdict(Decimal)
    holdings_out: list[dict] = []

    for h in db.execute(select(Holding)).scalars().all():
        priced = price_holding(db, h)
        if priced.missing:
            value_base = Decimal("0")
        else:
            value_base = to_base_current(db, priced.value, priced.price_currency)
        holdings_total_base += value_base
        holdings_by_account[h.account_id] += value_base
        by_asset_class[h.asset_class] += value_base
        by_currency[priced.price_currency] += value_base
        holdings_out.append({
            "holding_id": h.id,
            "account_id": h.account_id,
            "ticker": h.ticker,
            "asset_class": h.asset_class,
            "quantity": str(priced.quantity),
            "price": str(priced.price),
            "price_currency": priced.price_currency,
            "as_of": priced.as_of.isoformat(),
            "source": priced.source,
            "is_manual": priced.is_manual,
            "missing_price": priced.missing,
            "value_in_base": str(value_base),
        })

    by_account: list[dict] = []
    for acc_id, acc in accounts.items():
        native_balance = Decimal(str(acc.current_balance or 0))
        balance_base = to_base_current(db, native_balance, acc.native_currency)
        # Debt accounts hold a positive loan amount; net-worth subtracts it.
        signed_cash_base = -balance_base if acc.type.value == "debt" else balance_base
        holdings_base = holdings_by_account.get(acc_id, Decimal("0"))
        by_account.append({
            "account_id": acc_id,
            "name": acc.name,
            "type": acc.type.value,
            "native_currency": acc.native_currency,
            "cash_native": str(native_balance),
            "cash_in_base": str(signed_cash_base),
            "holdings_in_base": str(holdings_base),
            "total_in_base": str(signed_cash_base + holdings_base),
            "balance_updated_at": (
                acc.balance_updated_at.isoformat() if acc.balance_updated_at else None
            ),
        })
        cash_total_base += signed_cash_base
        bucket = "debt" if acc.type.value == "debt" else "cash"
        by_asset_class[bucket] += signed_cash_base
        by_currency[acc.native_currency] += signed_cash_base

    total = cash_total_base + holdings_total_base
    return {
        "currency": "CLP",
        "total_in_base": str(total),
        "cash_total_in_base": str(cash_total_base),
        "holdings_total_in_base": str(holdings_total_base),
        "by_account": by_account,
        "by_asset_class": [
            {"asset_class": k, "total_in_base": str(v)}
            for k, v in sorted(by_asset_class.items())
        ],
        "by_currency": [
            {"currency": k, "total_in_base": str(v)}
            for k, v in sorted(by_currency.items(), key=lambda kv: -kv[1])
        ],
        "holdings": holdings_out,
    }


def take_snapshot(db: Session, on_date: date | None = None) -> NetworthSnapshot:
    """Compute + persist a snapshot. Overwrites any existing row for `on_date`."""
    on_date = on_date or date.today()
    breakdown = current_networth(db)
    total = Decimal(breakdown["total_in_base"])

    existing = db.execute(
        select(NetworthSnapshot).where(NetworthSnapshot.date == on_date)
    ).scalar_one_or_none()
    if existing is not None:
        existing.total_networth_in_base = total
        existing.breakdown = breakdown
        snap = existing
    else:
        snap = NetworthSnapshot(
            date=on_date, total_networth_in_base=total, breakdown=breakdown
        )
        db.add(snap)
    db.commit()
    db.refresh(snap)
    return snap
