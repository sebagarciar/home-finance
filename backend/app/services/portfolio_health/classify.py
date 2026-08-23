"""Holding classification — enriched with SecurityMetadata in Stage 4.

Maps each holding into the policy allocation buckets. Stage 1 used only data
already in the app (free-form asset_class string, price_currency, a hardcoded
ticker map). Stage 4 enriches via the SecurityMetadata table when available:
- sector, region, country, expense_ratio, diversified_fund override the
  defaults for any ticker that has been auto- or manually-enriched.

Classification is pure: the metadata dict is pre-fetched by the router and
passed in; no DB calls happen here.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

# asset_class string (lowercased) -> policy bucket
_ASSET_CLASS_TO_BUCKET: dict[str, str] = {
    "cash": "cash",
    "money_market": "cash",
    "bond": "bonds",
    "bonds": "bonds",
    "fixed_income": "bonds",
    "equity": "global_equities",
    "equities": "global_equities",
    "stock": "global_equities",
    "etf": "global_equities",
    "fund": "global_equities",
    "mutual_fund": "global_equities",
    "index_fund": "global_equities",
    "crypto": "crypto",
    "cryptocurrency": "crypto",
    "real_estate": "alternatives",
    "reit": "alternatives",
    "commodity": "alternatives",
    "commodities": "alternatives",
    "gold": "alternatives",
    "alternative": "alternatives",
    "alternatives": "alternatives",
}

# Asset-class strings that denote a diversified product (not a single stock).
_DIVERSIFIED_CLASSES = {"etf", "fund", "mutual_fund", "index_fund", "bond", "bonds", "fixed_income"}

# Well-known diversified-fund tickers (used by the forecast engine + common holdings).
_KNOWN_DIVERSIFIED_TICKERS = {
    "VT", "VTI", "VOO", "SPY", "QQQ", "VXUS", "VEA", "VWO", "ITOT", "IVV",
    "AGG", "BND", "BNDX", "VGIT", "VCIT", "TLT", "SCHB", "SCHF", "SCHZ",
}

# Fintual tickers (Chilean mutual funds) are namespaced "FINTUAL:<id>" — diversified.
_FINTUAL_PREFIX = "FINTUAL:"


@dataclass(frozen=True)
class HoldingClass:
    holding_id: int
    ticker: str
    value_in_base: Decimal
    policy_bucket: str  # one of ALLOCATION_BUCKETS or "unknown"
    currency: str
    is_single_stock: bool
    is_diversified_fund: bool
    is_crypto: bool
    asset_class_known: bool
    missing_price: bool
    # Stage 4 enrichment fields — None when metadata is absent.
    sector: str | None = None
    region: str | None = None
    country: str | None = None
    expense_ratio: float | None = None


def classify_holding(snapshot_holding: dict, meta: dict | None = None) -> HoldingClass:
    """Classify one entry from current_networth()['holdings'].

    `meta` is a plain dict with SecurityMetadata fields for this ticker
    (pre-fetched and serialised by the router). When provided, enriched fields
    override the defaults derived from asset_class / ticker alone.
    """
    raw_class = str(snapshot_holding.get("asset_class") or "").strip().lower()
    ticker = str(snapshot_holding.get("ticker") or "").strip().upper()
    currency = str(snapshot_holding.get("price_currency") or "").strip().upper()
    value = Decimal(str(snapshot_holding.get("value_in_base") or "0"))
    missing_price = bool(snapshot_holding.get("missing_price"))

    # --- bucket from asset_class field ---
    bucket = _ASSET_CLASS_TO_BUCKET.get(raw_class, "unknown")

    # --- Stage 4: upgrade bucket from enriched asset_class if we got one ---
    if meta and meta.get("asset_class"):
        meta_bucket = _ASSET_CLASS_TO_BUCKET.get(str(meta["asset_class"]).lower(), "unknown")
        if meta_bucket != "unknown" and bucket == "unknown":
            bucket = meta_bucket

    asset_class_known = bucket != "unknown"
    is_crypto = bucket == "crypto"

    is_diversified = (
        raw_class in _DIVERSIFIED_CLASSES
        or ticker in _KNOWN_DIVERSIFIED_TICKERS
        or ticker.startswith(_FINTUAL_PREFIX)
        or bucket in ("bonds",)
    )
    # Stage 4: trust the enriched diversified_fund flag if present.
    if meta and meta.get("diversified_fund") is not None:
        is_diversified = bool(meta["diversified_fund"])

    is_single_stock = bucket == "global_equities" and not is_diversified

    # --- Stage 4: enriched metadata fields ---
    sector: str | None = meta.get("sector") if meta else None
    region: str | None = meta.get("region") if meta else None
    country: str | None = meta.get("country") if meta else None
    expense_ratio: float | None = meta.get("expense_ratio") if meta else None

    return HoldingClass(
        holding_id=int(snapshot_holding.get("holding_id") or 0),
        ticker=ticker,
        value_in_base=value,
        policy_bucket=bucket,
        currency=currency,
        is_single_stock=is_single_stock,
        is_diversified_fund=is_diversified,
        is_crypto=is_crypto,
        asset_class_known=asset_class_known,
        missing_price=missing_price,
        sector=sector,
        region=region,
        country=country,
        expense_ratio=expense_ratio,
    )


def classify_all(
    snapshot: dict,
    metadata_map: dict[str, dict] | None = None,
) -> list[HoldingClass]:
    """Classify all holdings in a networth snapshot.

    `metadata_map` is a pre-serialised dict of ticker -> metadata fields dict
    (built by the router from SecurityMetadata ORM rows).
    """
    mm = metadata_map or {}
    return [classify_holding(h, mm.get(h.get("ticker", "").upper())) for h in snapshot.get("holdings", [])]
