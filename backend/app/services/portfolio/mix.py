"""Mix vs target: today's net worth by bucket against the policy's ranges.

Pure: takes `current_networth()` output and a `Policy`. Bank cash and
cash-class holdings are the cash bucket; debt is excluded (it shrinks net
worth, it isn't part of the mix).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from . import config as C
from .policy import Policy

Status = Literal["below", "in", "above"]


@dataclass(frozen=True)
class BucketCheck:
    bucket: str
    label: str
    value_base: Decimal
    current_pct: float
    target_pct: float | None  # None for "unclassified"
    min_pct: float | None
    max_pct: float | None
    status: Status | None
    drift_pp: float | None  # current − target midpoint
    drifting: bool = False  # in range but more than the threshold from target


@dataclass(frozen=True)
class MixCheck:
    total_base: Decimal
    buckets: list[BucketCheck]
    out_of_range: int  # buckets outside their range
    drifting: int  # in range but more than the threshold from target


def bucket_values(networth: dict) -> dict[str, Decimal]:
    values = dict.fromkeys((*C.ALLOCATION_BUCKETS, "unclassified"), Decimal("0"))
    for row in networth.get("by_asset_class", []):
        if row["asset_class"] == "cash":
            values["cash"] += max(Decimal(row["total_in_base"]), Decimal("0"))
    for h in networth.get("holdings", []):
        cls = str(h.get("asset_class") or "").strip().lower()
        if cls == "cash":
            continue  # already inside by_asset_class["cash"]
        values[C.ASSET_CLASS_TO_BUCKET.get(cls, "unclassified")] += Decimal(h["value_in_base"])
    return values


def mix_check(networth: dict, policy: Policy) -> MixCheck:
    values = bucket_values(networth)
    total = sum(values.values(), Decimal("0"))

    def pct(v: Decimal) -> float:
        return round(float(v / total * 100), 1) if total > 0 else 0.0

    rows: list[BucketCheck] = []
    out_of_range = drifting = 0
    for bucket in (*C.ALLOCATION_BUCKETS, "unclassified"):
        cur = pct(values[bucket])
        rng = policy.allocation_ranges.get(bucket)
        if rng is None:
            if values[bucket] > 0:
                rows.append(BucketCheck(bucket, C.BUCKET_LABELS[bucket], values[bucket], cur,
                                        None, None, None, None, None))
            continue
        lo, hi = rng
        if lo == 0 and values[bucket] == 0:
            continue  # nothing held and nothing required (e.g. crypto): not worth a row
        status: Status = "above" if cur > hi else "below" if cur < lo else "in"
        target = policy.target_allocation[bucket]
        drift = round(cur - target, 1)
        is_drifting = status == "in" and abs(drift) > C.REBALANCE_THRESHOLD_PCT
        if status != "in":
            out_of_range += 1
        elif is_drifting:
            drifting += 1
        rows.append(BucketCheck(bucket, C.BUCKET_LABELS[bucket], values[bucket], cur,
                                target, lo, hi, status, drift, is_drifting))
    return MixCheck(total, rows, out_of_range, drifting)
