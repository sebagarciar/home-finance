from __future__ import annotations

from datetime import date
from decimal import Decimal
from email.message import EmailMessage
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db import Base, get_session
from app.main import create_app
from app.models import Account, AccountType, Transaction, TxnType
from app.seeds.defaults import seed
from app.services.importers.base import ParsedTxn
from app.services.importers.santander_es_email import parse_santander_email
from app.services.importers.service import commit_import, preview_import

INPUT_DIR = Path(__file__).resolve().parents[2] / "input"


def _raw_email(body: str, when: str = "Tue, 27 May 2026 09:15:00 +0200") -> bytes:
    msg = EmailMessage()
    msg["From"] = "notificaciones@gestiones.bancosantander.es"
    msg["Subject"] = "Movimiento en tu tarjeta"
    msg["Date"] = when
    msg.set_content(body)
    return msg.as_bytes()


# A no-op categorizer so commit_import never reaches Ollama/the network in tests.
def _stub_classify(*_a, **_k):
    return type("C", (), {"category": "Other"})()


# --- Parser --------------------------------------------------------------

def test_parses_card_retencion():
    raw = _raw_email(
        "Maria Jesus,\nte informamos de que Trainline.com ha realizado una "
        "retención de 110.30 EUR en tu tarjeta terminada en 3653.\n"
        "Para más información, entra en tu Banca Online."
    )
    p = parse_santander_email(raw)
    assert p is not None
    assert p.date == date(2026, 5, 27)
    assert p.amount == Decimal("-110.30")
    assert p.currency == "EUR"
    assert p.txn_type == TxnType.card_payment
    assert p.raw_description == "Trainline.com"


def test_parses_transfer_salida():
    raw = _raw_email(
        "Maria Jesus, te confirmamos que tu transferencia de 1650.0 EUR "
        "desde la cuenta acabada en 6176 se ha enviado correctamente."
    )
    p = parse_santander_email(raw)
    assert p is not None
    assert p.amount == Decimal("-1650.0")
    assert p.currency == "EUR"
    assert p.txn_type == TxnType.transfer
    assert p.raw_description == "Transferencia"


def test_unrecognised_email_returns_none():
    raw = _raw_email("Hola, tu extracto mensual ya está disponible en la app.")
    assert parse_santander_email(raw) is None


@pytest.mark.skipif(
    not list(INPUT_DIR.glob("santander_email_*.eml")),
    reason="no real .eml samples in input/",
)
def test_real_samples_parse():
    for path in sorted(INPUT_DIR.glob("santander_email_*.eml")):
        p = parse_santander_email(path.read_bytes())
        assert p is not None, f"failed to parse {path.name}"
        assert p.currency.isalpha() and len(p.currency) == 3
        assert p.amount != 0


# --- Supersede: a statement import archives overlapping email rows --------

def _account(db: Session) -> Account:
    acct = Account(
        name="Santander ES",
        institution="Santander",
        country="ES",
        type=AccountType.checking,
        native_currency="EUR",
        current_balance=Decimal("0"),
    )
    db.add(acct)
    db.commit()
    db.refresh(acct)
    return acct


def _parsed(d: date, amount: str, desc: str) -> ParsedTxn:
    return ParsedTxn(d, Decimal(amount), "EUR", desc, TxnType.card_payment)


def test_statement_supersedes_email_rows(db, monkeypatch):
    import app.services.importers.service as svc

    seed(db)
    monkeypatch.setattr(svc, "to_base", lambda *a, **k: Decimal("1"))
    monkeypatch.setattr(svc, "classify", _stub_classify)
    acct = _account(db)

    # An email row lands first.
    email_prev = preview_import(db, acct.id, [_parsed(date(2026, 5, 15), "-110.30", "Trainline")])
    commit_import(db, acct.id, email_prev, source="email")

    email_row = db.execute(select(Transaction).where(Transaction.source == "email")).scalar_one()
    assert email_row.archived is False

    # The monthly statement covering that date supersedes it.
    stmt_prev = preview_import(
        db,
        acct.id,
        [_parsed(date(2026, 5, 10), "-5.00", "Cafe"), _parsed(date(2026, 5, 20), "-9.00", "Metro")],
    )
    commit_import(db, acct.id, stmt_prev)  # source defaults to "statement"

    db.refresh(email_row)
    assert email_row.archived is True


# --- Endpoint ------------------------------------------------------------

def _make_client(monkeypatch, *, with_account: bool, creds: bool) -> TestClient:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()
    seed(session)
    if with_account:
        session.add(
            Account(
                name="Santander ES", institution="Santander", country="ES",
                type=AccountType.checking, native_currency="EUR", current_balance=Decimal("0"),
            )
        )
        session.commit()

    settings = get_settings()
    monkeypatch.setattr(settings, "gmail_user", "me@gmail.com" if creds else None)
    monkeypatch.setattr(settings, "gmail_app_password", "app-pw" if creds else None)
    monkeypatch.setattr(settings, "santander_email_account_id", 1 if with_account else None)

    import app.routers.imports as imports_router
    import app.services.importers.service as svc

    monkeypatch.setattr(svc, "to_base", lambda *a, **k: Decimal("1"))
    monkeypatch.setattr(svc, "classify", _stub_classify)
    _raw = _raw_email(
        "te informamos de que Trainline.com ha realizado una retención "
        "de 110.30 EUR en tu tarjeta terminada en 3653."
    )
    monkeypatch.setattr(imports_router, "fetch_santander_emails", lambda **k: [("uid1", _raw)])
    monkeypatch.setattr(imports_router, "archive_santander_emails", lambda uids, **k: None)

    def _override():
        yield session

    app = create_app()
    app.dependency_overrides[get_session] = _override
    return TestClient(app)


def test_email_sync_endpoint_imports_then_dedupes(monkeypatch):
    client = _make_client(monkeypatch, with_account=True, creds=True)

    r1 = client.post("/import/email/sync")
    assert r1.status_code == 200, r1.text
    assert r1.json() == {"fetched": 1, "parsed": 1, "imported": 1, "skipped": 0}

    # Second run re-reads the same email; dedup means nothing new is added.
    r2 = client.post("/import/email/sync")
    assert r2.json() == {"fetched": 1, "parsed": 1, "imported": 0, "skipped": 1}


def test_email_sync_503_without_credentials(monkeypatch):
    client = _make_client(monkeypatch, with_account=False, creds=False)
    assert client.post("/import/email/sync").status_code == 503
