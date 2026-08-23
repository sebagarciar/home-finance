from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import date, timedelta
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


class CurrencyApiProvider(FxProvider):
    """fawazahmed0/currency-api — free, no key, served from CDNs.

    Daily snapshots (weekends included, history back to ~2024) for ~200
    currencies including CLP. Primary URL on jsDelivr with a Cloudflare Pages
    mirror. The dataset has occasional missing days (e.g. 2025-12-10), so a
    404 walks back up to 3 days; a same-day request additionally falls back to
    the `latest` tag.
    """

    _PRIMARY = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{tag}/v1/currencies/{base}.json"
    _MIRROR = "https://{tag}.currency-api.pages.dev/v1/currencies/{base}.json"

    def __init__(self, client: httpx.Client | None = None):
        self._client = client

    def fetch(self, on_date: date, base: str, quote: str) -> Decimal:
        if base == quote:
            return Decimal("1")
        tags = [(on_date - timedelta(days=back)).isoformat() for back in range(4)]
        if on_date >= date.today():
            tags.insert(1, "latest")
        client = self._client or httpx.Client(timeout=10.0, follow_redirects=True)
        try:
            last_exc: Exception | None = None
            for tag in tags:
                for template in (self._PRIMARY, self._MIRROR):
                    url = template.format(tag=tag, base=base.lower())
                    try:
                        resp = client.get(url)
                        resp.raise_for_status()
                        data = resp.json()
                    except (httpx.HTTPError, ValueError) as e:
                        last_exc = e
                        continue
                    rate = (data.get(base.lower()) or {}).get(quote.lower())
                    if rate is None:
                        raise LookupError(
                            f"FX rate missing for {base}->{quote} on {on_date} ({url})"
                        )
                    return Decimal(str(rate))
            raise LookupError(
                f"currency-api unreachable for {base}->{quote} on {on_date}"
            ) from last_exc
        finally:
            if self._client is None:
                client.close()


class FrankfurterProvider(FxProvider):
    """frankfurter.app — free, no API key, ECB reference rates.

    Covers ~30 major currencies but NOT CLP. Date queries clamp to the most
    recent banking day, so weekends/holidays/today-before-publish all work.
    Endpoint shape: GET /{YYYY-MM-DD}?from=XXX&to=YYY
    """

    def __init__(self, api_base: str | None = None, client: httpx.Client | None = None):
        self.api_base = api_base or get_settings().frankfurter_api_base
        self._client = client

    def fetch(self, on_date: date, base: str, quote: str) -> Decimal:
        if base == quote:
            return Decimal("1")
        client = self._client or httpx.Client(timeout=10.0)
        try:
            resp = client.get(
                f"{self.api_base}/{on_date.isoformat()}",
                params={"from": base, "to": quote},
            )
            resp.raise_for_status()
            data = resp.json()
        finally:
            if self._client is None:
                client.close()
        rates = data.get("rates") or {}
        if quote not in rates:
            raise LookupError(f"FX rate missing for {base}->{quote} on {on_date}: {data}")
        return Decimal(str(rates[quote]))


class MindicadorClient:
    """mindicador.cl — free, no API key, Banco Central de Chile data.

    Only knows CLP per USD ("dolar") and CLP per EUR ("euro"). Fetches a whole
    year per request (GET /{indicator}/{YYYY}) and caches it on the instance,
    so a backfill over hundreds of dates costs ~one request per year. Values
    exist only for banking days; lookups walk back up to 10 days (crossing the
    year boundary if needed).
    """

    _INDICATORS = {"USD": "dolar", "EUR": "euro"}

    def __init__(self, api_base: str | None = None, client: httpx.Client | None = None):
        self.api_base = api_base or get_settings().mindicador_api_base
        self._client = client
        self._series: dict[tuple[str, int], dict[date, Decimal]] = {}

    def supports(self, currency: str) -> bool:
        return currency in self._INDICATORS

    def clp_per(self, currency: str, on_date: date) -> Decimal:
        """1 unit of `currency` = ? CLP on the nearest banking day <= on_date."""
        indicator = self._INDICATORS[currency]
        d = on_date
        for _ in range(10):
            value = self._year_series(indicator, d.year).get(d)
            if value is not None:
                return value
            d -= timedelta(days=1)
        raise LookupError(f"mindicador has no {indicator} value near {on_date}")

    def _year_series(self, indicator: str, year: int) -> dict[date, Decimal]:
        key = (indicator, year)
        if key not in self._series:
            data = self._get_with_retries(f"{self.api_base}/{indicator}/{year}")
            self._series[key] = {
                date.fromisoformat(item["fecha"][:10]): Decimal(str(item["valor"]))
                for item in data.get("serie") or []
            }
        return self._series[key]

    def _get_with_retries(self, url: str) -> dict:
        # mindicador.cl is erratic: the year endpoint takes ~13 s on a good
        # request and intermittently 500s or drops the connection. Long timeout
        # + a few retries make it dependable enough; the fx_rates cache means
        # each (date, pair) only ever pays this once.
        client = self._client or httpx.Client(timeout=30.0)
        try:
            last_exc: Exception | None = None
            for attempt in range(3):
                if attempt:
                    time.sleep(2.0 * attempt)
                try:
                    resp = client.get(url)
                    resp.raise_for_status()
                    return resp.json()
                except (httpx.HTTPError, ValueError) as e:
                    last_exc = e
            raise LookupError(f"mindicador unreachable: {url}") from last_exc
        finally:
            if self._client is None:
                client.close()


class FreeCompositeFxProvider(FxProvider):
    """Key-less FX from two free sources.

    - Anything <-> CLP goes through mindicador.cl (central-bank fixings; only
      USD and EUR are published, other currencies cross via ECB EUR rates).
    - Non-CLP pairs go to frankfurter.app (ECB) directly.
    """

    def __init__(
        self,
        mindicador: MindicadorClient | None = None,
        frankfurter: FrankfurterProvider | None = None,
    ):
        self.mindicador = mindicador or MindicadorClient()
        self.frankfurter = frankfurter or FrankfurterProvider()

    def fetch(self, on_date: date, base: str, quote: str) -> Decimal:
        if base == quote:
            return Decimal("1")
        if "CLP" not in (base, quote):
            return self.frankfurter.fetch(on_date, base, quote)
        other = quote if base == "CLP" else base
        clp_per_other = self._clp_per(other, on_date)
        return clp_per_other if base == other else Decimal("1") / clp_per_other

    def _clp_per(self, currency: str, on_date: date) -> Decimal:
        if self.mindicador.supports(currency):
            return self.mindicador.clp_per(currency, on_date)
        eur_per_ccy = self.frankfurter.fetch(on_date, currency, "EUR")
        return eur_per_ccy * self.mindicador.clp_per("EUR", on_date)


def get_provider() -> FxProvider:
    settings = get_settings()
    if settings.fx_provider == "free":
        return CurrencyApiProvider()
    if settings.fx_provider == "mindicador":
        return FreeCompositeFxProvider()
    if settings.fx_provider == "exchangerate_host":
        return ExchangerateHostProvider()
    raise ValueError(f"Unknown fx_provider: {settings.fx_provider}")
