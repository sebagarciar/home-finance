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

# A days payload deliberately NOT sorted newest-first, to prove we pick max date.
_DAYS = {
    "data": [
        {"attributes": {"date": "2026-05-20", "net_asset_value": 3900.0, "net_asset_value_type": "clp"}},
        {"attributes": {"date": "2026-05-28", "net_asset_value": 3971.9244, "net_asset_value_type": "clp"}},
        {"attributes": {"date": "2026-05-27", "net_asset_value": 3960.0, "net_asset_value_type": "clp"}},
    ]
}


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://fintual.cl/api")


def test_is_fintual_ticker():
    assert is_fintual_ticker("FINTUAL:186")
    assert is_fintual_ticker("fintual:186")
    assert not is_fintual_ticker("SPY")


def test_fintual_fetch_picks_latest_nav():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/real_assets/186/days"
        return httpx.Response(200, json=_DAYS)

    prov = FintualPriceProvider(base_url="https://fintual.cl/api", client=_client(handler))
    q = prov.fetch("FINTUAL:186")
    assert q.price == Decimal("3971.9244")
    assert q.currency == "CLP"
    assert q.as_of == date(2026, 5, 28)
    assert q.ticker == "FINTUAL:186"


def test_fintual_fetch_empty_raises():
    prov = FintualPriceProvider(client=_client(lambda r: httpx.Response(200, json={"data": []})))
    with pytest.raises(PriceLookupError):
        prov.fetch("FINTUAL:999")


def test_fintual_fetch_http_error_raises():
    prov = FintualPriceProvider(client=_client(lambda r: httpx.Response(404, text="nope")))
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
    assert comp.fetch("FINTUAL:186").currency == "CLP"  # -> fintual


def test_search_resolves_name_to_series_tickers():
    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if p == "/api/conceptual_assets":
            assert request.url.params.get("name") == "Risky Norris"
            return httpx.Response(200, json={
                "data": [{"id": "36", "attributes": {"name": "Risky Norris", "currency": "CLP"}}]
            })
        if p == "/api/conceptual_assets/36/real_assets":
            return httpx.Response(200, json={"data": [
                {"id": "186", "attributes": {"serie": "A", "symbol": "FM-FIN-RCN-A"}},
                {"id": "245", "attributes": {"serie": "APV", "symbol": "FM-FIN-RCN-APV"}},
            ]})
        return httpx.Response(404)

    rows = search_fintual_funds("Risky Norris", client=_client(handler))
    assert {r["ticker"] for r in rows} == {"FINTUAL:186", "FINTUAL:245"}
    a = next(r for r in rows if r["serie"] == "A")
    assert a["fund"] == "Risky Norris"
    assert a["currency"] == "CLP"
    assert a["ticker"] == "FINTUAL:186"
