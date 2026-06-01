from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal

import httpx

from ...config import get_settings


class FxProvider(ABC):
    """Provider returning a rate such that: 1 unit of `base` = `rate` units of `quote`."""

    @abstractmethod
    def fetch(self, on_date: date, base: str, quote: str) -> Decimal:
        ...


class ExchangerateHostProvider(FxProvider):
    """exchangerate.host — free, covers CLP, supports historical lookups.

    Endpoint shape: GET /{YYYY-MM-DD}?base=XXX&symbols=YYY
    Latest:        GET /latest?base=XXX&symbols=YYY
    """

    def __init__(self, api_base: str | None = None, client: httpx.Client | None = None):
        self.api_base = api_base or get_settings().fx_api_base
        self._client = client

    def _http(self) -> httpx.Client:
        return self._client or httpx.Client(timeout=10.0)

    def fetch(self, on_date: date, base: str, quote: str) -> Decimal:
        if base == quote:
            return Decimal("1")
        path = on_date.isoformat()
        params: dict[str, str] = {"base": base, "symbols": quote}
        api_key = get_settings().fx_api_key
        if api_key:
            params["access_key"] = api_key
        client = self._http()
        try:
            resp = client.get(f"{self.api_base}/{path}", params=params)
            resp.raise_for_status()
            data = resp.json()
        finally:
            if self._client is None:
                client.close()
        rates = data.get("rates") or {}
        if quote not in rates:
            raise LookupError(f"FX rate missing for {base}->{quote} on {on_date}: {data}")
        return Decimal(str(rates[quote]))


def get_provider() -> FxProvider:
    settings = get_settings()
    if settings.fx_provider == "exchangerate_host":
        return ExchangerateHostProvider()
    raise ValueError(f"Unknown fx_provider: {settings.fx_provider}")
