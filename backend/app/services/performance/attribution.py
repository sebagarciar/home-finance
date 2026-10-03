"""Split an unrealized gain (base CLP) into asset-price and FX effects.

    value_base      = to_base_current(qty · P_now)
    unrealized_base = value_base − cost_base            (cost at historical FX)
    price_effect    = to_base_current(qty · P_now − cost_native)
    fx_effect       = unrealized_base − price_effect    (= cost_native·FX_now − cost_base)

Only `to_base_current` is used here; historical FX is already baked into
`cost_base` by the ledger. Base-currency holdings have fx_effect == 0.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from ..fx.conversion import to_base_current
from .basis import PositionState


@dataclass(frozen=True)
class Attribution:
    value_base: Decimal
    unrealized_base: Decimal
    price_effect: Decimal
    fx_effect: Decimal


def attribute(db: Session, state: PositionState, price_now: Decimal, currency: str) -> Attribution:
    value_native = state.qty * price_now
    value_base = to_base_current(db, value_native, currency)
    unrealized = value_base - state.cost_base
    price_effect = to_base_current(db, value_native - state.cost_native, currency)
    return Attribution(
        value_base=value_base,
        unrealized_base=unrealized,
        price_effect=price_effect,
        fx_effect=unrealized - price_effect,
    )
