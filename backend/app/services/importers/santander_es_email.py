"""Parse a single Santander ES transaction-notification email into a ParsedTxn.

These are the per-transaction emails Santander sends, e.g.:

    Maria Jesus,
    te informamos de que Trainline.com ha realizado una retención de
    110.30 EUR en tu tarjeta terminada en 3653.

They are *notifications*, not statements: the amount is typically the card
AUTHORISATION (which can differ from the settled figure), the body carries no
explicit transaction date (we use the email's Date header), and some movements
(direct debits, fees) may never produce one. Hence rows from this parser are
ingested with source="email" as a provisional layer that the monthly .xlsx
statement supersedes.

⚠️ The regexes below are built from the one phrasing the user provided plus
conservative variants. Add patterns (Bizum, transfers, refunds/abonos) as real
.eml samples land in input/. Anything unrecognised returns None and is skipped —
never guessed — so we don't poison categorization with bad rows.
"""
from __future__ import annotations

import email
import logging
import re
from datetime import date
from decimal import Decimal
from email.utils import parsedate_to_datetime

from ...models.transactions import TxnType
from .base import ParsedTxn
from .santander_es import _parse_amount

logger = logging.getLogger(__name__)

# Amount + 3-letter ISO currency, e.g. "33.00 EUR". Accents are optional because
# the text/plain part of these emails strips them ("retencion", not "retención").
_AMT = r"(?P<amount>[\d.,]+)\s*(?P<ccy>[A-Z]{3})"

# Sentence-ending period: a "." at end of body, or followed by a prose word
# (lowercase 2nd letter, e.g. "Consulta"). A bare "\." stops inside dotted
# merchant names ("P.MALLORCA VELA" -> "P", "E.S. REPSOL" -> "E"); terminal
# merchant names are upper-case, so they never look like the next sentence.
# (?-i:) keeps the case test strict under the patterns' IGNORECASE flag.
_EOS = r"\.(?=\s*$|(?-i:\s+[A-ZÁÉÍÓÚÑ¿¡]?[a-záéíóúñ]))"

# (regex, txn_type, sign, default_merchant)
# sign multiplies the magnitude from _parse_amount.
# default_merchant: fixed description when the email carries no merchant name
#   (e.g. own-account transfers); None means extract from the "merchant" group.
_PATTERNS: list[tuple[re.Pattern[str], TxnType, int, str | None]] = [
    # "... has pagado <AMT> con tu tarjeta terminada en NNNN en <MERCHANT>."
    # (Subject: "¡Pago realizado con tu tarjeta!")
    (
        re.compile(
            r"has pagado\s+" + _AMT
            + r"\s+con tu tarjeta(?:\s+terminada en\s+\d+)?\s+en\s+(?P<merchant>.+?)(?:" + _EOS + r"|$)",
            re.IGNORECASE | re.DOTALL,
        ),
        TxnType.card_payment,
        -1,
        None,
    ),
    # "... de que <MERCHANT> ha realizado una retencion de <AMT> en tu tarjeta ..."
    # (Subject: "Dinero de tarjeta retenido")
    (
        re.compile(
            r"de que\s+(?P<merchant>.+?)\s+ha realizado una retenci[oó]?n de\s+" + _AMT,
            re.IGNORECASE | re.DOTALL,
        ),
        TxnType.card_payment,
        -1,
        None,
    ),
    # "... compra de <AMT> en <MERCHANT> ..." / "... cargo de <AMT> en <MERCHANT> ..."
    (
        re.compile(
            r"(?:compra|cargo) de\s+" + _AMT + r"\s+en\s+(?P<merchant>.+?)(?:" + _EOS + r"|\bcon\b|$)",
            re.IGNORECASE | re.DOTALL,
        ),
        TxnType.card_payment,
        -1,
        None,
    ),
    # "... abono/ingreso/devolucion de <AMT> de <MERCHANT> ..." -> inflow
    (
        re.compile(
            r"(?:abono|ingreso|devoluci[oó]?n) de\s+" + _AMT + r"\s+(?:de|por)\s+(?P<merchant>.+?)(?:" + _EOS + r"|$)",
            re.IGNORECASE | re.DOTALL,
        ),
        TxnType.refund,
        1,
        None,
    ),
    # "... tu transferencia de <AMT> desde la cuenta acabada en NNNN se ha enviado correctamente."
    # (Subject: "¡Transferencia realizada!") — outbound transfer, no recipient name in body.
    (
        re.compile(
            r"tu transferencia de\s+" + _AMT
            + r"\s+desde la cuenta acabada en\s+\d+\s+se ha enviado correctamente",
            re.IGNORECASE | re.DOTALL,
        ),
        TxnType.transfer,
        -1,
        "Transferencia",
    ),
]


def _body_text(msg: email.message.Message) -> str:
    """Return the email's text content, preferring text/plain; HTML stripped."""
    plain: str | None = None
    html: str | None = None
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        try:
            payload = part.get_payload(decode=True)
            if not isinstance(payload, bytes):
                continue
            text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        except (LookupError, ValueError):
            continue
        if ctype == "text/plain" and plain is None:
            plain = text
        elif ctype == "text/html" and html is None:
            html = text
    if plain is not None:
        return plain
    if html is not None:
        return _strip_html(html)
    return ""


def _strip_html(html: str) -> str:
    try:
        from bs4 import BeautifulSoup  # lazy: keeps the dep optional at import time

        return BeautifulSoup(html, "html.parser").get_text(separator=" ")
    except ImportError:  # pragma: no cover - bs4 is a declared dependency
        return re.sub(r"<[^>]+>", " ", html)


def parse_santander_email(raw: bytes) -> ParsedTxn | None:
    """Parse one raw RFC822 email into a ParsedTxn, or None if it isn't a
    recognised transaction notification."""
    msg = email.message_from_bytes(raw)

    txn_date: date | None = None
    if msg["Date"]:
        try:
            txn_date = parsedate_to_datetime(msg["Date"]).date()
        except (TypeError, ValueError):
            txn_date = None
    if txn_date is None:
        logger.warning("Santander email missing a parseable Date header; skipping")
        return None

    body = " ".join(_body_text(msg).split())  # collapse whitespace/newlines
    if not body:
        return None

    for pattern, txn_type, sign, default_merchant in _PATTERNS:
        m = pattern.search(body)
        if not m:
            continue
        magnitude = _parse_amount(m.group("amount"))
        if magnitude == 0:
            return None
        if default_merchant is not None:
            merchant = default_merchant
        else:
            merchant = m.group("merchant").strip().rstrip(".").strip()
        return ParsedTxn(
            date=txn_date,
            amount=magnitude.copy_abs() * Decimal(sign),
            currency=m.group("ccy").upper(),
            raw_description=merchant,
            txn_type=txn_type,
        )
    return None
