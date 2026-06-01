"""Money conversion entry points.

These are the ONLY two functions in the codebase that perform FX conversion. Anywhere else
doing math on amounts in different currencies is a bug.

- `to_base(amount, currency, on_date)`: convert using the FX rate AS OF `on_date`. Use for
  transactions (spending), where the historical rate at the time of the transaction matters.
- `to_base_current(amount, currency)`: convert using the latest FX rate. Use for net-worth
  and holdings valuation, where what it's worth right now matters.

`get_rate` is the shared cached lookup; both helpers go through it.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...models.fx import FxRate
from .provider import FxProvider, get_provider

log = logging.getLogger(__name__)

# Last-ditch approximate mid-market rates (1 base = X quote). Only used when the
# real provider is unreachable AND no cached rate exists. These exist so the app
# remains usable offline / without an API key; the user should set FX_API_KEY for
# accurate historical FX.
_FALLBACK_RATES: dict[tuple[str, str], Decimal] = {
    ("EUR", "CLP"): Decimal("1050"),
    ("USD", "CLP"): Decimal("950"),
    ("GBP", "CLP"): Decimal("1200"),
    ("CLP", "EUR"): Decimal("0.000952"),
    ("CLP", "USD"): Decimal("0.001052"),
    ("CLP", "GBP"): Decimal("0.000833"),
    ("EUR", "USD"): Decimal("1.10"),
    ("USD", "EUR"): Decimal("0.91"),
}


def _today() -> date:
    return date.today()


def get_rate(
    db: Session,
    on_date: date | None,
    base: str,
    quote: str,
    provider: FxProvider | None = None,
) -> Decimal:
    """Return rate such that 1 base = `rate` quote on `on_date` (or latest if None).

    Cached in fx_rates; fetched from the provider on miss. `None` means "latest" and is
    cached against today's date.
    """
    if base == quote:
        return Decimal("1")

    lookup_date = on_date or _today()
    row = db.execute(
        select(FxRate).where(
            FxRate.date == lookup_date,
            FxRate.base_currency == base,
            FxRate.quote_currency == quote,
        )
    ).scalar_one_or_none()
    if row is not None:
        return Decimal(str(row.rate))

    provider = provider or get_provider()
    try:
        rate = provider.fetch(lookup_date, base, quote)
    except (LookupError, Exception) as e:  # noqa: BLE001 — last-resort fallback
        fallback = _FALLBACK_RATES.get((base, quote))
        if fallback is None:
            raise
        log.warning(
            "FX provider unreachable for %s->%s on %s (%s); using fallback rate %s. "
            "Set FX_API_KEY for accurate historical FX.",
            base, quote, lookup_date, e, fallback,
        )
        rate = fallback
    db.add(FxRate(date=lookup_date, base_currency=base, quote_currency=quote, rate=rate))
    db.commit()
    return rate


def to_base(
    db: Session,
    amount: Decimal | float,
    currency: str,
    on_date: date,
    provider: FxProvider | None = None,
) -> Decimal:
    """Historical conversion to base currency (CLP). Use for transactions/spending."""
    base = get_settings().base_currency
    if currency == base:
        return Decimal(str(amount))
    # rate is: 1 currency = ? base
    rate = get_rate(db, on_date, currency, base, provider=provider)
    return Decimal(str(amount)) * rate


def to_base_current(
    db: Session,
    amount: Decimal | float,
    currency: str,
    provider: FxProvider | None = None,
) -> Decimal:
    """Latest conversion to base currency (CLP). Use for holdings/net-worth valuation."""
    base = get_settings().base_currency
    if currency == base:
        return Decimal(str(amount))
    rate = get_rate(db, None, currency, base, provider=provider)
    return Decimal(str(amount)) * rate
