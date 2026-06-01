from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import BinaryIO

from ...models.transactions import TxnType


@dataclass
class ParsedTxn:
    """Bank-parser output before persistence/dedup/categorization.

    `amount` is in `currency` and is SIGNED: outflows negative, inflows positive.
    `txn_type` is the bank's hint about what kind of movement this is.
    """

    date: date
    amount: Decimal
    currency: str
    raw_description: str
    txn_type: TxnType


class Parser(ABC):
    """Bank-statement parser interface."""

    name: str  # short stable identifier, e.g. "revolut"

    @abstractmethod
    def parse(self, file: BinaryIO) -> list[ParsedTxn]:
        ...
