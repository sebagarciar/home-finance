"""PriceProvider interface and the yfinance implementation.

Mirrors the FxProvider pattern: a single abstract `PriceProvider.fetch(ticker)`
returning a `PriceQuote(price, currency, as_of)`. Swap providers in one file.

Failures (unknown ticker, network down, rate limit) raise `PriceLookupError`.
Callers decide what to do — typically fall back to `holdings.manual_price` and
surface a staleness flag in the UI.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ...config import get_settings


class PriceLookupError(LookupError):
    """The provider could not return a price for this ticker."""


@dataclass(frozen=True)
class PriceQuote:
    ticker: str
    price: Decimal
    currency: str  # ISO 4217 (yfinance currencies are normalized to upper-case)
    as_of: date


class PriceProvider(ABC):
    @abstractmethod
    def fetch(self, ticker: str) -> PriceQuote:
        ...


class YFinancePriceProvider(PriceProvider):
    """Latest close from yfinance. No API key required.

    yfinance returns the trading currency on `Ticker.info['currency']`. We never
    convert here — the caller (valuation) is responsible for going to base via
    `to_base_current`.
    """

    def fetch(self, ticker: str) -> PriceQuote:
        # Import lazily so tests that stub the provider don't need yfinance.
        try:
            import yfinance as yf
        except ImportError as e:  # pragma: no cover — guarded by pyproject
            raise PriceLookupError(f"yfinance not installed: {e}") from e

        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="5d", auto_adjust=False)
        except Exception as e:  # noqa: BLE001 — yfinance raises a zoo of errors
            raise PriceLookupError(f"yfinance fetch failed for {ticker}: {e}") from e

        if hist is None or hist.empty:
            raise PriceLookupError(f"yfinance returned no rows for {ticker}")

        last_row = hist.iloc[-1]
        price = Decimal(str(last_row["Close"]))
        as_of = hist.index[-1].date() if hasattr(hist.index[-1], "date") else date.today()

        currency = None
        try:
            info = t.fast_info  # cheap; avoids slow .info
            currency = getattr(info, "currency", None) or info.get("currency")
        except Exception:  # noqa: BLE001
            currency = None
        if not currency:
            # Final fallback: assume USD for US-listed tickers without a suffix.
            currency = "USD"

        return PriceQuote(
            ticker=ticker.upper(),
            price=price,
            currency=currency.upper(),
            as_of=as_of,
        )


class CompositePriceProvider(PriceProvider):
    """Routes by ticker prefix. `FINTUAL:<id>` tickers go to Fintual (Chilean
    funds, not on Yahoo); everything else goes to the default provider."""

    def __init__(self, default: PriceProvider, fintual: PriceProvider):
        self._default = default
        self._fintual = fintual

    def fetch(self, ticker: str) -> PriceQuote:
        # Lazy import avoids a circular import at module load.
        from .fintual import is_fintual_ticker

        if is_fintual_ticker(ticker):
            return self._fintual.fetch(ticker)
        return self._default.fetch(ticker)


def get_provider() -> PriceProvider:
    name = get_settings().price_provider
    if name == "yfinance":
        default: PriceProvider = YFinancePriceProvider()
    else:
        raise ValueError(f"Unknown price_provider: {name}")
    # Fintual routing is always available regardless of the default provider.
    from .fintual import FintualPriceProvider

    return CompositePriceProvider(default=default, fintual=FintualPriceProvider())
