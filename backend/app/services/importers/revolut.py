"""Revolut CSV parser.

Columns: Type, Product, Started Date, Completed Date, Description, Amount, Fee,
         Currency, State, Balance.

Type maps directly to TxnType.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal
from typing import BinaryIO

from ...models.transactions import TxnType
from .base import ParsedTxn, Parser

_TYPE_MAP = {
    "card payment": TxnType.card_payment,
    "card refund": TxnType.refund,
    "transfer": TxnType.transfer,
    "deposit": TxnType.deposit,
    "refund": TxnType.refund,
    "fee": TxnType.fee,
    "exchange": TxnType.other,
    "topup": TxnType.deposit,
}


class RevolutParser(Parser):
    name = "revolut"

    def parse(self, file: BinaryIO) -> list[ParsedTxn]:
        text = io.TextIOWrapper(file, encoding="utf-8-sig", newline="")
        reader = csv.DictReader(text)
        out: list[ParsedTxn] = []
        for row in reader:
            state = (row.get("State") or "").strip().upper()
            if state and state != "COMPLETED":
                continue  # skip pending/declined
            started = (row.get("Started Date") or "").strip()
            if not started:
                continue
            try:
                txn_date = datetime.fromisoformat(started.split(".")[0]).date()
            except ValueError:
                # Some Revolut variants use "YYYY-MM-DD HH:MM:SS"
                txn_date = datetime.strptime(started[:19], "%Y-%m-%d %H:%M:%S").date()
            amount = Decimal((row.get("Amount") or "0").strip())
            currency = (row.get("Currency") or "EUR").strip().upper()
            descr = (row.get("Description") or "").strip()
            raw_type = (row.get("Type") or "").strip().lower()
            txn_type = _TYPE_MAP.get(raw_type, TxnType.other)
            out.append(
                ParsedTxn(
                    date=txn_date,
                    amount=amount,
                    currency=currency,
                    raw_description=descr,
                    txn_type=txn_type,
                )
            )
        return out
