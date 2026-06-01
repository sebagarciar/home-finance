"""Import service: dedup flagging and FX capture."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models import Account, AccountType, Transaction
from app.models.transactions import TxnType
from app.services.importers.base import ParsedTxn
from app.services.importers.service import commit_import, preview_import
from tests.conftest import StubFxProvider  # noqa: F401  (re-uses fixture defs)


@pytest.fixture
def account(db):
    a = Account(name="Test", country="ES", type=AccountType.checking, native_currency="EUR")
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _stub_provider():
    return StubFxProvider({
        (date(2026, 1, 5), "EUR", "CLP"): Decimal("1050"),
        (date(2026, 2, 5), "EUR", "CLP"): Decimal("1060"),
    })


def test_preview_flags_first_pass_as_new_and_repass_as_duplicate(db, account, monkeypatch):
    parsed = [
        ParsedTxn(
            date=date(2026, 1, 5),
            amount=Decimal("-10.00"),
            currency="EUR",
            raw_description="COMPRA TRIP.COM, AMSTERDAM, TARJETA 5489 , COMISION 0,11",
            txn_type=TxnType.card_payment,
        ),
        ParsedTxn(
            date=date(2026, 2, 5),
            amount=Decimal("-20.00"),
            currency="EUR",
            raw_description="Card Payment Wetaca",
            txn_type=TxnType.card_payment,
        ),
    ]
    # Patch the FX provider so we don't hit the network.
    from app.services.fx import conversion as conv_mod
    monkeypatch.setattr(conv_mod, "get_provider", _stub_provider)

    previews = preview_import(db, account.id, parsed)
    assert [p.is_duplicate for p in previews] == [False, False]

    result = commit_import(db, account.id, previews)
    assert result.imported == 2
    assert result.duplicates_skipped == 0

    # Second pass: same data should be flagged as duplicates.
    previews2 = preview_import(db, account.id, parsed)
    assert [p.is_duplicate for p in previews2] == [True, True]

    result2 = commit_import(db, account.id, previews2)
    assert result2.imported == 0
    assert result2.duplicates_skipped == 2

    # Forcing re-import should still respect the unique constraint —
    # commit_import would raise on second write; that's the correct guardrail.

    # Verify FX captured at the right historical rate.
    txns = db.query(Transaction).order_by(Transaction.date).all()
    assert len(txns) == 2
    assert Decimal(str(txns[0].fx_rate_to_base)) == Decimal("1050")
    assert Decimal(str(txns[1].fx_rate_to_base)) == Decimal("1060")


def test_dedup_collapses_amazon_order_id_noise(db, account, monkeypatch):
    """Two Amazon rows that differ only in order ID must dedup to the same hash."""
    from app.services.fx import conversion as conv_mod
    monkeypatch.setattr(conv_mod, "get_provider", _stub_provider)

    a = ParsedTxn(
        date=date(2026, 1, 5),
        amount=Decimal("-15.00"),
        currency="EUR",
        raw_description="AMZN MKTP ES*1A2B3C, MADRID ES, TARJ. :*333653",
        txn_type=TxnType.card_payment,
    )
    b = ParsedTxn(
        date=date(2026, 1, 5),
        amount=Decimal("-15.00"),
        currency="EUR",
        raw_description="AMZN MKTP ES*9X8Y7W, MADRID ES, TARJ. :*333653",
        txn_type=TxnType.card_payment,
    )
    previews = preview_import(db, account.id, [a, b])
    assert previews[0].dedup_hash == previews[1].dedup_hash
    assert previews[1].is_duplicate is True  # second in batch flagged
