"""End-to-end parsing tests against the real sample files in /input/."""
from __future__ import annotations

import io
from decimal import Decimal
from pathlib import Path

import pytest

from app.models.transactions import TxnType
from app.services.importers import RevolutParser, SantanderEsParser, ScotiabankClParser

INPUT_DIR = Path("/Users/seba/Documents/home_finance/input")


@pytest.mark.skipif(not (INPUT_DIR / "revolut_espana.csv").exists(), reason="sample missing")
def test_revolut_parser():
    with (INPUT_DIR / "revolut_espana.csv").open("rb") as f:
        rows = RevolutParser().parse(f)
    assert len(rows) > 50
    # At least one of each type appears in the sample.
    types = {r.txn_type for r in rows}
    assert TxnType.card_payment in types
    assert TxnType.transfer in types
    assert TxnType.deposit in types
    # Currency is EUR throughout.
    assert all(r.currency == "EUR" for r in rows)
    # Wetaca card payments appear with negative amounts.
    wetaca = [r for r in rows if "wetaca" in r.raw_description.lower() and r.txn_type == TxnType.card_payment]
    assert wetaca and all(r.amount < 0 for r in wetaca)
    # Fees live in a separate column: "Premium plan fee" rows are Amount 0.00,
    # Fee 8.99, and must import as -8.99.
    plan_fees = [r for r in rows if r.raw_description == "Premium plan fee"]
    assert plan_fees and all(r.amount == Decimal("-8.99") for r in plan_fees)
    assert all(r.txn_type == TxnType.fee for r in plan_fees)


def test_revolut_parser_subtracts_fee():
    csv_text = (
        "Type,Product,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance\n"
        "Card Payment,Current,2026-03-01 10:00:00,2026-03-02 10:00:00,Shop,-10.00,0.50,EUR,COMPLETED,89.50\n"
        "Charge,Current,2026-03-03 10:00:00,2026-03-03 10:00:00,Premium plan fee,0.00,8.99,EUR,COMPLETED,80.51\n"
        "Deposit,Current,2026-03-04 10:00:00,2026-03-04 10:00:00,Top up,20.00,,EUR,COMPLETED,100.51\n"
    )
    rows = RevolutParser().parse(io.BytesIO(csv_text.encode()))
    assert [r.amount for r in rows] == [Decimal("-10.50"), Decimal("-8.99"), Decimal("20.00")]
    assert rows[1].txn_type == TxnType.fee


@pytest.mark.skipif(not (INPUT_DIR / "santander_espana.xlsx").exists(), reason="sample missing")
def test_santander_es_parser():
    with (INPUT_DIR / "santander_espana.xlsx").open("rb") as f:
        rows = SantanderEsParser().parse(f)
    assert len(rows) > 500
    # European minus sign correctly parsed to negative Decimal.
    pago_movil = [r for r in rows if r.raw_description.startswith("PAGO MOVIL EN")]
    assert pago_movil
    assert all(r.amount < 0 for r in pago_movil[:20])
    # Currency = EUR, txn_type heuristic landed mostly on card_payment.
    assert all(r.currency == "EUR" for r in rows)
    assert sum(1 for r in rows if r.txn_type == TxnType.card_payment) > 400


@pytest.mark.skipif(not (INPUT_DIR / "scotiabank_chile.xls").exists(), reason="sample missing")
def test_scotiabank_cl_parser_multicurrency():
    with (INPUT_DIR / "scotiabank_chile.xls").open("rb") as f:
        rows = ScotiabankClParser(statement_year=2026).parse(f)
    assert len(rows) >= 3
    # USD purchase from Target (US).
    target = next(r for r in rows if "TARGET" in r.raw_description.upper())
    assert target.currency == "USD"
    assert target.amount < 0
    # EUR purchase from Booking.com (NL).
    booking = next(r for r in rows if "Booking" in r.raw_description)
    assert booking.currency == "EUR"
    # PAGO EN EFECTIVO must be classified as transfer, not card_payment.
    pago = next(r for r in rows if r.raw_description.upper().startswith("PAGO EN"))
    assert pago.txn_type == TxnType.transfer
