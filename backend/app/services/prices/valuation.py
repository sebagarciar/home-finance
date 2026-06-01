"""Holdings valuation.

`current_price(db, ticker)` returns a `PriceQuote` using a daily cache.
The `price_cache` table is keyed on (ticker, date) — the first call of the
calendar day fetches from the provider and writes a row; every subsequent call
that day returns the cached row. There is no intraday refresh and no
background poller; prices update when something reads them (Portfolio page
load, /networth endpoints, /networth/snapshot). Set
`price_cache_enabled=false` to bypass the cache for debugging.

`price_holding(db, holding)` resolves a holding to a `PricedHolding` with the
value in the holding's price_currency. It tries the provider first, falls back
to the holding's `manual_price` (with a staleness flag) on failure. The caller
converts to base via `to_base_current`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...models.holdings import Holding
from ...models.prices import PriceCacheEntry
from .provider import PriceLookupError, PriceProvider, PriceQuote, get_provider

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PricedHolding:
    holding_id: int
    ticker: str
    quantity: Decimal
    price: Decimal
    price_currency: str  # the currency of `price`
    as_of: date
    source: str  # "yfinance" | "cache" | "manual"
    # True when the price came from `manual_price` (no live quote available).
    # The UI shows "manual, as of <date>" when this is set.
    is_manual: bool
    # True when no manual price exists and the provider failed — we have no
    # price for this holding.
    missing: bool = False

    @property
    def value(self) -> Decimal:
        return self.quantity * self.price


def current_price(
    db: Session, ticker: str, provider: PriceProvider | None = None
) -> PriceQuote:
    """Cache-then-provider. Writes the fresh quote back to `price_cache`."""
    ticker = ticker.upper()
    today = date.today()
    cache_enabled = get_settings().price_cache_enabled

    row = db.execute(
        select(PriceCacheEntry).where(
            PriceCacheEntry.ticker == ticker, PriceCacheEntry.date == today
        )
    ).scalar_one_or_none()
    if row is not None and cache_enabled:
        return PriceQuote(
            ticker=ticker,
            price=Decimal(str(row.price)),
            currency=row.currency,
            as_of=row.date,
        )

    provider = provider or get_provider()
    quote = provider.fetch(ticker)

    # Upsert today's cache entry.
    if row is None:
        db.add(
            PriceCacheEntry(
                ticker=ticker, date=today, price=quote.price, currency=quote.currency
            )
        )
    else:
        row.price = quote.price
        row.currency = quote.currency
    db.commit()
    return quote


def price_holding(
    db: Session, holding: Holding, provider: PriceProvider | None = None
) -> PricedHolding:
    """Resolve a holding to a `PricedHolding`. Manual price wins as fallback.

    The holding's stored `price_currency` is treated as authoritative — we trust
    the user knows what currency this asset trades in. The provider's reported
    currency is ignored if it disagrees (a yfinance quirk for non-US tickers
    where `.fast_info` can lie); we log a warning if so.
    """
    qty = Decimal(str(holding.quantity))
    live_source = "fintual" if holding.ticker.upper().startswith("FINTUAL:") else "yfinance"
    try:
        quote = current_price(db, holding.ticker, provider=provider)
        if quote.currency != holding.price_currency:
            log.warning(
                "Holding %s: provider currency %s != stored %s; trusting stored.",
                holding.ticker, quote.currency, holding.price_currency,
            )
        return PricedHolding(
            holding_id=holding.id,
            ticker=holding.ticker,
            quantity=qty,
            price=quote.price,
            price_currency=holding.price_currency,
            as_of=quote.as_of,
            source=live_source,
            is_manual=False,
        )
    except PriceLookupError as e:
        log.info("Live price unavailable for %s (%s); using manual fallback.", holding.ticker, e)

    if holding.manual_price is not None:
        manual_as_of = (
            holding.manual_price_updated_at.date()
            if holding.manual_price_updated_at
            else date.today()
        )
        return PricedHolding(
            holding_id=holding.id,
            ticker=holding.ticker,
            quantity=qty,
            price=Decimal(str(holding.manual_price)),
            price_currency=holding.price_currency,
            as_of=manual_as_of,
            source="manual",
            is_manual=True,
        )

    return PricedHolding(
        holding_id=holding.id,
        ticker=holding.ticker,
        quantity=qty,
        price=Decimal("0"),
        price_currency=holding.price_currency,
        as_of=date.today(),
        source="manual",
        is_manual=True,
        missing=True,
    )
