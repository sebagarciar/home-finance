"""Normalize raw bank descriptions into a stable merchant key.

The SAME function is used by:
- The importer, to compute `normalized_description` and `dedup_hash`.
- The categorizer, to look up `category_rules`.

Goal: collapse noisy variants of the same merchant into one string.
e.g. `PAGO MOVIL EN BRUNCHIT MARIA, VITRUVIO ES, TARJ. :*333653` -> `brunchit maria vitruvio`
     `COMPRA SQ *FULL OF BEANS SL, Madrid, TARJETA 548..., COMISION 0,00` -> `full of beans sl madrid`
     `Card Payment ... Wetaca` -> `wetaca`
     `TARGET PL 10079330 10079330` -> `target`
"""
from __future__ import annotations

import re
import unicodedata

# Leading prefixes added by the bank, not by the merchant.
_LEADING_PREFIXES = [
    r"pago movil en\s+",
    r"compra\s+",
    r"card payment\s+",
    r"card refund\s+",
    r"bizum payment to:\s+",
    r"transfer to\s+",
    r"payment from\s+",
    r"money added via bizum",
    r"deposit\s+",
    r"transfer\s+",
    r"refund\s+",
    r"revert of:\s+",
]

# Trailing junk: card numbers, commission notes.
_TRAILING_NOISE = [
    r",\s*tarj\.\s*:\s*\*\d+",
    r",\s*tarjeta\s*\*?\d+(\s*,\s*comision\s*[\d,\.]+)?",
    r",\s*comision\s*[\d,\.]+",
]

# Acquirer / aggregator prefixes attached to the merchant name.
_ACQUIRER_PREFIXES = [
    r"sq\s*\*",          # Square
    r"paypal\s*\*",
    r"stripe\s*\*",
    r"sumup\s*\*",
    r"transbank\s+",
    r"webpay\s+",
    r"amzn mktp es\*[a-z0-9]+\s*",  # Amazon Marketplace ES with order id
]

# Reference-ID strips. Patterns where we KEEP the merchant-kind token (so
# "LICENCIA 10691" -> "licencia", a useful key that maps to Transport via
# the seeded rule). For `l:NNNNN` we drop the whole thing — it's not a
# meaningful merchant name on its own.
_REFERENCE_PATTERNS = [
    (r"\b(licencia)\s+\d+", r"\1"),
    (r"\b(lic)\.\s*\d+", r"\1"),
    (r"\bl:\s*\d+", ""),
    (r"\b\d{6,}\b", ""),  # any standalone 6+ digit run (txn/order IDs)
]

# Generic location tokens we strip after merchant cleanup. Without this, bare
# city names leak into the merchant key for transactions where the actual
# merchant name was unique-per-row (taxi license, etc.) and got stripped.
_CITY_STOPWORDS = {
    # Spain
    "madrid", "barcelona", "valencia", "sevilla", "zaragoza", "malaga",
    "bilbao", "alicante", "vitoria", "getafe", "leganes", "mostoles",
    "alcorcon", "fuenlabrada", "las rozas", "majadahonda", "arroyomolinoses",
    # Chile
    "santiago", "providencia", "las condes", "vitacura", "nunoa", "lo barnechea",
    "vina del mar", "valparaiso", "concepcion", "antofagasta",
    # Common foreign cities seen in samples
    "amsterdam", "palo alto", "cork", "luxembourg", "london", "paris",
}

# Country suffixes that appear at end of merchant tokens.
_COUNTRY_SUFFIXES = re.compile(r"\b(es|us|nl|cl|uk|fr|de|it|pt)\b", re.IGNORECASE)

# Punctuation we strip entirely (preserve '.' for things like "trip.com").
_PUNCT_TO_SPACE = re.compile(r"[,;:!?()\[\]{}\"'`*+]+")

_WHITESPACE = re.compile(r"\s+")


def normalize_description(raw: str) -> str:
    if not raw:
        return ""

    s = raw.strip().lower()

    # Strip accents so "comisión" -> "comision", "andrés" -> "andres".
    s = "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))

    # Order matters: trailing junk first (it can contain "tarjeta" + digit runs
    # that would otherwise match the reference pattern).
    for pat in _TRAILING_NOISE:
        s = re.sub(pat, " ", s)

    for pat in _LEADING_PREFIXES:
        s = re.sub(r"^" + pat, " ", s)

    for pat in _ACQUIRER_PREFIXES:
        s = re.sub(pat, " ", s)

    for pat, repl in _REFERENCE_PATTERNS:
        s = re.sub(pat, repl, s)

    s = _PUNCT_TO_SPACE.sub(" ", s)
    s = _COUNTRY_SUFFIXES.sub(" ", s)
    # Strip leading till/cashier numbers like "218 - pret a manger"
    s = re.sub(r"^\s*\d+\s*[-–]\s*", "", s)
    s = _WHITESPACE.sub(" ", s).strip()

    # Drop city stopwords as standalone tokens. Done last so multi-word cities
    # like "las condes" or "palo alto" are matched.
    if s:
        for stop in sorted(_CITY_STOPWORDS, key=len, reverse=True):
            s = re.sub(rf"\b{re.escape(stop)}\b", "", s)
        s = _WHITESPACE.sub(" ", s).strip()
    return s
