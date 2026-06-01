"""Fintual price provider + fund resolver.

Fintual (Chilean roboadvisor) publishes a free, no-key public API with daily
NAV (`net_asset_value`) per fund series, in CLP. Yahoo doesn't carry these
funds, so this provider fills the gap for local holdings.

Ticker convention: ``FINTUAL:<real_asset_id>`` — the numeric id of a specific
fund *series* (e.g. Risky Norris series A is ``FINTUAL:186``). Use
`search_fintual_funds` to resolve a fund name to its series + ticker.

Failures raise `PriceLookupError`; valuation then falls back to the holding's
manual price with a staleness flag, same as any other provider.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx

from .provider import PriceLookupError, PriceProvider, PriceQuote

FINTUAL_PREFIX = "FINTUAL:"
_BASE_URL = "https://fintual.cl/api"
_TIMEOUT = 15.0
_HEADERS = {"User-Agent": "home-finance"}


def is_fintual_ticker(ticker: str) -> bool:
    return ticker.upper().startswith(FINTUAL_PREFIX)


def _real_asset_id(ticker: str) -> str:
    # "FINTUAL:186" -> "186"; tolerate a bare id too.
    return ticker.split(":", 1)[1] if ":" in ticker else ticker


class FintualPriceProvider(PriceProvider):
    def __init__(self, base_url: str = _BASE_URL, client: httpx.Client | None = None):
        self._base = base_url.rstrip("/")
        self._client = client  # injectable for tests

    def _get(self, path: str, **params) -> dict:
        own = self._client is None
        client = self._client or httpx.Client(timeout=_TIMEOUT, headers=_HEADERS)
        try:
            resp = client.get(f"{self._base}{path}", params=params or None)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise PriceLookupError(f"Fintual request failed for {path}: {e}") from e
        finally:
            if own:
                client.close()

    def fetch(self, ticker: str) -> PriceQuote:
        rid = _real_asset_id(ticker)
        payload = self._get(f"/real_assets/{rid}/days")
        days = payload.get("data") or []
        if not days:
            raise PriceLookupError(f"Fintual returned no NAV history for {ticker}")
        # The endpoint isn't reliably ordered — pick the most recent date.
        newest = max(days, key=lambda d: d["attributes"]["date"])
        attrs = newest["attributes"]
        nav = attrs.get("net_asset_value")
        if nav is None:
            raise PriceLookupError(f"Fintual NAV missing for {ticker}")
        currency = (attrs.get("net_asset_value_type") or "CLP").upper()
        return PriceQuote(
            ticker=ticker.upper(),
            price=Decimal(str(nav)),
            currency=currency,
            as_of=date.fromisoformat(attrs["date"]),
        )


def search_fintual_funds(query: str, *, base_url: str = _BASE_URL, client: httpx.Client | None = None) -> list[dict]:
    """Resolve a fund name to its series (one row per series), so a user can add
    a holding by name instead of memorizing a real_asset id.

    Returns rows: {fund, serie, symbol, ticker, currency}. `ticker` is ready to
    drop straight into a Holding.
    """
    own = client is None
    client = client or httpx.Client(timeout=_TIMEOUT, headers=_HEADERS)
    try:
        try:
            cas = client.get(f"{base_url}/conceptual_assets", params={"name": query})
            cas.raise_for_status()
            conceptual = cas.json().get("data", [])
        except (httpx.HTTPError, ValueError) as e:
            raise PriceLookupError(f"Fintual search failed: {e}") from e

        rows: list[dict] = []
        for ca in conceptual:
            cid = ca["id"]
            cattr = ca.get("attributes", {})
            fund_name = cattr.get("name")
            fund_currency = (cattr.get("currency") or "CLP").upper()
            try:
                ras = client.get(f"{base_url}/conceptual_assets/{cid}/real_assets")
                ras.raise_for_status()
                series = ras.json().get("data", [])
            except (httpx.HTTPError, ValueError):
                continue
            for ra in series:
                a = ra.get("attributes", {})
                rows.append({
                    "fund": fund_name,
                    "serie": a.get("serie"),
                    "symbol": a.get("symbol"),
                    "ticker": f"{FINTUAL_PREFIX}{ra['id']}",
                    "currency": fund_currency,
                })
        return rows
    finally:
        if own:
            client.close()
