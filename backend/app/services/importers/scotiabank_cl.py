"""Scotiabank Chile credit card .xls parser.

Sparse layout (from sample):
    - Data rows alternate with blank rows (real data on odd row indexes).
    - Fixed column offsets (0-indexed):
        col 10 : Fecha Operación (DD/MM)
        col 15 : Descripción
        col 35 : País (e.g. 'US', 'NL', 'CL' — blank for some)
        col 39 : Monto Moneda Origen (signed, European format)
        col 41 : Monto US$ (informational; we ignore)
    - Year is NOT in the row; we infer it from the file's statement date or fall
      back to the current year. For Phase 2 we accept it as a parser argument; the
      uploader UI will pass it.
    - Currency mapping by País:
        'US' -> USD
        'NL', 'ES', 'DE', 'FR', 'IT', 'PT' -> EUR
        'UK' -> GBP
        '', 'CL', else -> CLP
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import BinaryIO

import xlrd

from ...models.transactions import TxnType
from .base import ParsedTxn, Parser

_AMOUNT_CLEAN = re.compile(r"[^\d,.\-−]")

_COUNTRY_TO_CURRENCY = {
    "US": "USD",
    "NL": "EUR",
    "ES": "EUR",
    "DE": "EUR",
    "FR": "EUR",
    "IT": "EUR",
    "PT": "EUR",
    "UK": "GBP",
    "GB": "GBP",
}

_HEADER_TOKEN_HINTS = {"total pagos", "total compras", "comisiones", "intereses", "saldo"}


def _parse_amount(raw) -> Decimal:
    s = str(raw).strip().replace("−", "-")
    s = _AMOUNT_CLEAN.sub("", s)
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    return Decimal(s) if s else Decimal("0")


class ScotiabankClParser(Parser):
    name = "scotiabank_cl"

    def __init__(self, statement_year: int | None = None):
        # If not provided, use the current year. The import endpoint can pass it.
        self.statement_year = statement_year or date.today().year

    def parse(self, file: BinaryIO) -> list[ParsedTxn]:
        wb = xlrd.open_workbook(file_contents=file.read())
        ws = wb.sheet_by_index(0)
        out: list[ParsedTxn] = []
        for i in range(ws.nrows):
            row = ws.row_values(i)
            if len(row) < 42:
                continue
            fecha = str(row[10]).strip()
            descr = str(row[15]).strip()
            if not descr:
                continue
            descr_lower = descr.lower()
            if any(h in descr_lower for h in _HEADER_TOKEN_HINTS):
                continue
            if not fecha or fecha == "00/00":
                continue
            try:
                day, month = fecha.split("/")
                txn_date = date(self.statement_year, int(month), int(day))
            except (ValueError, TypeError):
                continue
            pais = str(row[35]).strip().upper()
            monto_origen = _parse_amount(row[39])
            if monto_origen == 0:
                continue
            currency = _COUNTRY_TO_CURRENCY.get(pais, "CLP")
            # Card statement convention: positive = charge to card = outflow.
            # Flip the sign so outflows are negative like every other parser.
            amount = -monto_origen
            # Credit-card payoffs ("PAGO EN EFECTIVO", "PAGO TARJETA") show as
            # positive on the statement (credit to card). After the flip they are
            # negative — but they represent a transfer from the user's bank, not
            # spending. Classify as transfer.
            if descr_lower.startswith("pago en") or descr_lower.startswith("pago tarjeta"):
                txn_type = TxnType.transfer
            else:
                txn_type = TxnType.card_payment
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
