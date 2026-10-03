"""Cost basis + investment performance.

- `basis.replay` — average-cost replay of a holding's trade ledger (pure).
- `attribution.attribute` — split unrealized gain into price vs FX effect.
- `returns.xirr` — money-weighted return over dated cash flows (pure).
- `service` — DB-facing per-holding / portfolio aggregation for GET /performance.

Valuation and net worth are unaffected: `Holding.quantity` stays the manual
source of truth; the ledger only supplies basis and returns.
"""
from .basis import LedgerError, PositionState, TradeInput, replay, validate_ledger
from .returns import xirr

__all__ = ["LedgerError", "PositionState", "TradeInput", "replay", "validate_ledger", "xirr"]
