"""Fintual price provider + composite routing + search resolver.

Uses httpx.MockTransport so no network is touched.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.services.prices.fintual import (
    FintualPriceProvider,
    is_fintual_ticker,
    search_fintual_funds,
)
from app.services.prices.provider import (
    CompositePriceProvider,
    PriceLookupError,
    PriceProvider,
    PriceQuote,
)

# Share-price payload deliberately NOT sorted newest-first, to prove we pick max date.
_DAYS = [
    {"id": 1, "managed_fund_serie": 6, "date": "2026-09-29", "value": 4375.9249},
    {"id": 3, "managed_fund_serie": 6, "date": "2026-10-01", "value": 4450.2229},
    {"id": 2, "managed_fund_serie": 6, "date": "2026-09-30", "value": 4389.1716},
]
_COUNTRIES = [
    {"id": 1, "name": "chile", "currency": {"id": 1, "name": "CLP"}, "iso_code": "CL"},
    {"id": 91, "name": "mexico", "currency": {"id": 58, "name": "MXN"}, "iso_code": "MX"},
]
_SERIES = [
    {"id": 6, "managed_fund": {"id": 4, "name": "risky norris", "country": 1}, "name": "a"},
    {"id": 7, "managed_fund": {"id": 4, "name": "risky norris", "country": 1}, "name": "apv"},
    {"id": 4, "managed_fund": {"id": 3, "name": "moderate pitt", "country": 1}, "name": "a"},
    {"id": 11, "managed_fund": {"id": 6, "name": "risky hayek", "country": 91}, "name": "f10"},
]


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://inversiones.fintual.com/api")


def _api(days=_DAYS):
    """Handler serving the public endpoints; `days` is the share_price payload."""
    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if p == "/api/managed_funds/serie/share_price":
            return httpx.Response(200, json=days)
        if p == "/api/managed_funds/serie":
            return httpx.Response(200, json=_SERIES)
        if p == "/api/geo/countries":
            return httpx.Response(200, json=_COUNTRIES)
        return httpx.Response(404)
    return handler


def test_is_fintual_ticker():
    assert is_fintual_ticker("FINTUAL:186")
    assert is_fintual_ticker("fintual:186")
    assert not is_fintual_ticker("SPY")


def test_fintual_fetch_picks_latest_nav():
    seen: dict = {}
    inner = _api()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/share_price"):
            seen["params"] = dict(request.url.params)
        return inner(request)

    q = FintualPriceProvider(client=_client(handler)).fetch("FINTUAL:6")
    assert seen["params"]["fund_serie"] == "6"
    assert q.price == Decimal("4450.2229")
    assert q.currency == "CLP"
    assert q.as_of == date(2026, 10, 1)
    assert q.ticker == "FINTUAL:6"


def test_fintual_fetch_currency_follows_fund_country():
    q = FintualPriceProvider(client=_client(_api())).fetch("FINTUAL:11")
    assert q.currency == "MXN"


def test_fintual_fetch_empty_raises():
    prov = FintualPriceProvider(client=_client(_api(days=[])))
    with pytest.raises(PriceLookupError):
        prov.fetch("FINTUAL:999")


def test_fintual_fetch_http_error_raises():
    # Unknown series -> the API answers 422.
    prov = FintualPriceProvider(client=_client(lambda r: httpx.Response(422, json={"detail": []})))
    with pytest.raises(PriceLookupError):
        prov.fetch("FINTUAL:186")


def test_composite_routes_by_prefix():
    class StubDefault(PriceProvider):
        def fetch(self, ticker: str) -> PriceQuote:
            return PriceQuote(ticker=ticker, price=Decimal("500"), currency="USD", as_of=date(2026, 5, 28))

    class StubFintual(PriceProvider):
        def fetch(self, ticker: str) -> PriceQuote:
            return PriceQuote(ticker=ticker, price=Decimal("3971"), currency="CLP", as_of=date(2026, 5, 28))

    comp = CompositePriceProvider(default=StubDefault(), fintual=StubFintual())
    assert comp.fetch("SPY").currency == "USD"          # -> default (yfinance)
    assert comp.fetch("FINTUAL:6").currency == "CLP"  # -> fintual


def test_search_resolves_name_to_series_tickers():
    rows = search_fintual_funds("Risky Norris", client=_client(_api()))
    assert {r["ticker"] for r in rows} == {"FINTUAL:6", "FINTUAL:7"}
    a = next(r for r in rows if r["serie"] == "A")
    assert a["fund"] == "Risky Norris"
    assert a["currency"] == "CLP"
    assert a["ticker"] == "FINTUAL:6"


def test_search_is_case_insensitive_substring():
    rows = search_fintual_funds("hayek", client=_client(_api()))
    assert [(r["ticker"], r["currency"]) for r in rows] == [("FINTUAL:11", "MXN")]
