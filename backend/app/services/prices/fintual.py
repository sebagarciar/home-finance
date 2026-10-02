"""Fintual price provider + fund resolver.

Fintual (Chilean roboadvisor) publishes daily NAV per fund series on the public,
no-key backend behind its fund pages (`inversiones.fintual.com/api`). Yahoo
doesn't carry these funds, so this provider fills the gap for local holdings.

The old `fintual.cl/api/real_assets/*` endpoints went behind a partner bearer
token in 2026 and their ids are not the ones used here.

Ticker convention: ``FINTUAL:<serie_id>`` — the numeric id of a specific fund
*series* on `/managed_funds/serie` (e.g. Risky Norris series A is
``FINTUAL:6``). Use `search_fintual_funds` to resolve a fund name to its series
+ ticker.

Failures raise `PriceLookupError`; valuation then falls back to the holding's
manual price with a staleness flag, same as any other provider.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import httpx

from .provider import PriceLookupError, PriceProvider, PriceQuote

FINTUAL_PREFIX = "FINTUAL:"
_BASE_URL = "https://inversiones.fintual.com/api"
_TIMEOUT = 15.0
_HEADERS = {"User-Agent": "home-finance"}
# NAV is published daily (weekends included); look back far enough to ride out
# a publishing gap without pulling the whole history.
_LOOKBACK_DAYS = 14


def is_fintual_ticker(ticker: str) -> bool:
    return ticker.upper().startswith(FINTUAL_PREFIX)


def _serie_id(ticker: str) -> str:
    # "FINTUAL:6" -> "6"; tolerate a bare id too.
    return ticker.split(":", 1)[1] if ":" in ticker else ticker


def _get(client: httpx.Client | None, base: str, path: str, **params) -> list | dict:
    own = client is None
    client = client or httpx.Client(timeout=_TIMEOUT, headers=_HEADERS)
    try:
        resp = client.get(f"{base}{path}", params=params or None)
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError) as e:
        raise PriceLookupError(f"Fintual request failed for {path}: {e}") from e
    finally:
        if own:
            client.close()


def _series_index(client: httpx.Client | None, base: str) -> dict[int, dict]:
    """{serie_id: {fund, serie, currency}} from the public series + country lists."""
    countries = _get(client, base, "/geo/countries")
    currency_by_country = {
        c["id"]: (c.get("currency") or {}).get("name", "CLP").upper() for c in countries
    }
    out: dict[int, dict] = {}
    for s in _get(client, base, "/managed_funds/serie"):
        fund = s.get("managed_fund") or {}
        out[s["id"]] = {
            "fund": (fund.get("name") or "").title(),
            "serie": (s.get("name") or "").upper() or None,
            "currency": currency_by_country.get(fund.get("country"), "CLP"),
        }
    return out


class FintualPriceProvider(PriceProvider):
    def __init__(self, base_url: str = _BASE_URL, client: httpx.Client | None = None):
        self._base = base_url.rstrip("/")
        self._client = client  # injectable for tests

    def fetch(self, ticker: str) -> PriceQuote:
        sid = _serie_id(ticker)
        today = date.today()
        days = _get(
            self._client, self._base, "/managed_funds/serie/share_price",
            fund_serie=sid,
            start_date=(today - timedelta(days=_LOOKBACK_DAYS)).isoformat(),
            end_date=today.isoformat(),
        )
        if not days:
            raise PriceLookupError(f"Fintual returned no NAV for {ticker} in the last {_LOOKBACK_DAYS} days")
        # Don't trust response ordering — pick the most recent date.
        newest = max(days, key=lambda d: d["date"])
        if newest.get("value") is None:
            raise PriceLookupError(f"Fintual NAV missing for {ticker}")
        meta = _series_index(self._client, self._base).get(int(sid))
        return PriceQuote(
            ticker=ticker.upper(),
            price=Decimal(str(newest["value"])),
            currency=meta["currency"] if meta else "CLP",
            as_of=date.fromisoformat(newest["date"]),
        )


def search_fintual_funds(query: str, *, base_url: str = _BASE_URL, client: httpx.Client | None = None) -> list[dict]:
    """Resolve a fund name to its series (one row per series), so a user can add
    a holding by name instead of memorizing a series id.

    Returns rows: {fund, serie, symbol, ticker, currency}. `ticker` is ready to
    drop straight into a Holding.
    """
    q = query.strip().lower()
    rows = []
    for sid, meta in sorted(_series_index(client, base_url.rstrip("/")).items()):
        if q in meta["fund"].lower():
            rows.append({
                "fund": meta["fund"],
                "serie": meta["serie"],
                "symbol": None,  # the public API exposes no exchange symbol
                "ticker": f"{FINTUAL_PREFIX}{sid}",
                "currency": meta["currency"],
            })
    return rows
