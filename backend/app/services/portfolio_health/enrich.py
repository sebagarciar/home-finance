"""yfinance metadata enrichment for portfolio holdings (Stage 4).

Fetches sector, country, expense ratio, product type, and related metadata from
yfinance .info. Results are cached in the `security_metadata` table with a
7-day TTL. Manual overrides (source='manual') are never overwritten.

Graceful degradation everywhere: if yfinance is unavailable the function
returns without raising so the review flow continues with whatever is cached.
Fintual tickers (FINTUAL:<id>) are skipped — they don't exist in yfinance.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from ...models.portfolio_health import SecurityMetadata

_CACHE_TTL_DAYS = 7
_FINTUAL_PREFIX = "FINTUAL:"

_COUNTRY_REGION: dict[str, str] = {
    "US": "North America", "CA": "North America",
    "MX": "Latin America", "CL": "Latin America", "BR": "Latin America",
    "AR": "Latin America", "CO": "Latin America", "PE": "Latin America",
    "GB": "Europe", "DE": "Europe", "FR": "Europe", "ES": "Europe",
    "IT": "Europe", "NL": "Europe", "SE": "Europe", "CH": "Europe",
    "BE": "Europe", "PT": "Europe", "NO": "Europe", "DK": "Europe",
    "FI": "Europe", "AT": "Europe", "IE": "Europe", "PL": "Europe",
    "JP": "Asia Pacific", "CN": "Asia Pacific", "HK": "Asia Pacific",
    "AU": "Asia Pacific", "IN": "Asia Pacific", "KR": "Asia Pacific",
    "SG": "Asia Pacific", "TW": "Asia Pacific", "TH": "Asia Pacific",
    "ID": "Asia Pacific", "MY": "Asia Pacific", "NZ": "Asia Pacific",
}

_QTYPE_TO_ASSET_CLASS: dict[str, str] = {
    "etf": "etf",
    "mutualfund": "mutual_fund",
    "equity": "equity",
    "bond": "bond",
    "treasury": "bond",
    "cryptocurrency": "crypto",
}

_QTYPE_TO_PRODUCT: dict[str, str] = {
    "etf": "ETF",
    "mutualfund": "Mutual Fund",
    "equity": "Stock",
    "bond": "Bond",
    "treasury": "Bond",
    "cryptocurrency": "Crypto",
}


def _yfinance_info(ticker: str) -> dict:
    try:
        import yfinance as yf  # noqa: PLC0415
        t = yf.Ticker(ticker)
        info = t.info
        return info if isinstance(info, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _parse_expense_ratio(info: dict) -> float | None:
    """Return expense ratio as a percentage (0–100 scale), or None."""
    raw = info.get("annualReportExpenseRatio") or info.get("expenseRatio")
    if raw is None:
        return None
    try:
        v = float(raw)
        # yfinance returns either a fraction (0.0003) or a percent (0.03%)
        # Values below 0.1 are almost certainly fractions — convert to pct.
        return round(v * 100, 4) if v < 0.1 else round(v, 4)
    except (TypeError, ValueError):
        return None


def _build_fields(ticker: str, info: dict) -> dict:
    qtype = (info.get("quoteType") or "").lower()

    sector = info.get("sector") or None
    country_raw = info.get("country") or None
    country = country_raw[:2].upper() if country_raw and len(country_raw) >= 2 else None
    region = _COUNTRY_REGION.get(country or "", None)
    currency = (info.get("currency") or "").upper() or None

    expense_ratio = _parse_expense_ratio(info)
    asset_class = _QTYPE_TO_ASSET_CLASS.get(qtype)
    product_type = _QTYPE_TO_PRODUCT.get(qtype)

    diversified_fund: bool | None = None
    if qtype in ("etf", "mutualfund"):
        diversified_fund = True
    elif qtype == "equity":
        diversified_fund = False

    liquidity_level: str | None = None
    if qtype in ("etf", "equity"):
        liquidity_level = "high"
    elif qtype == "mutualfund":
        liquidity_level = "medium"
    elif qtype in ("bond", "treasury"):
        liquidity_level = "medium"

    return {
        "asset_class": asset_class,
        "sector": sector,
        "region": region,
        "country": country,
        "currency": currency,
        "product_type": product_type,
        "expense_ratio": expense_ratio,
        "diversified_fund": diversified_fund,
        "liquidity_level": liquidity_level,
    }


def _is_stale(row: SecurityMetadata) -> bool:
    if row.updated_at is None:
        return True
    updated = row.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    cutoff = datetime.now(tz=UTC) - timedelta(days=_CACHE_TTL_DAYS)
    return updated < cutoff


def enrich_ticker(ticker: str, db: Session) -> SecurityMetadata | None:
    """Fetch + cache metadata for one ticker. Never raises.

    - Manual-override rows are returned as-is, never re-fetched.
    - Fintual tickers are skipped (not in yfinance).
    - If yfinance is unreachable the stale/absent row is returned as-is.
    """
    if not ticker or ticker.startswith(_FINTUAL_PREFIX):
        return None

    existing = db.get(SecurityMetadata, ticker)
    if existing is not None and existing.source == "manual":
        return existing
    if existing is not None and not _is_stale(existing):
        return existing

    info = _yfinance_info(ticker)
    if not info:
        return existing  # graceful degrade: keep stale / return None

    fields = _build_fields(ticker, info)

    if existing is None:
        row = SecurityMetadata(ticker=ticker, source="auto", **fields)
        try:
            db.add(row)
            db.flush()
        except Exception:  # noqa: BLE001
            try:
                db.expunge(row)
            except Exception:  # noqa: BLE001
                pass
            return None
    else:
        for k, v in fields.items():
            if v is not None:
                setattr(existing, k, v)
        existing.updated_at = datetime.now(tz=UTC)
        row = existing

    return row


def enrich_all(tickers: list[str], db: Session) -> dict[str, SecurityMetadata]:
    """Enrich a list of tickers and return a metadata map.

    Only fetches from yfinance for tickers that are missing or stale. Returns
    whatever is in the DB for tickers that can't be enriched (graceful degrade).
    """
    result: dict[str, SecurityMetadata] = {}
    for ticker in dict.fromkeys(tickers):  # deduplicate, preserve order
        row = enrich_ticker(ticker, db)
        if row is not None:
            result[ticker] = row
    return result


def get_metadata_map(tickers: list[str], db: Session) -> dict[str, SecurityMetadata]:
    """Return cached metadata only — no yfinance calls."""
    result: dict[str, SecurityMetadata] = {}
    for ticker in dict.fromkeys(tickers):
        row = db.get(SecurityMetadata, ticker)
        if row is not None:
            result[ticker] = row
    return result


def metadata_to_dict(row: SecurityMetadata) -> dict:
    return {
        "ticker": row.ticker,
        "asset_class": row.asset_class,
        "sector": row.sector,
        "region": row.region,
        "country": row.country,
        "currency": row.currency,
        "product_type": row.product_type,
        "expense_ratio": row.expense_ratio,
        "diversified_fund": row.diversified_fund,
        "liquidity_level": row.liquidity_level,
        "source": row.source,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
