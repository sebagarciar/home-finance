"""Seed default taxonomy + ES/CL merchant rules + the single Assumptions row.

Idempotent: only inserts if rows are missing. Safe to run on every app start.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Account,
    AccountType,
    Assumptions,
    Category,
    CategoryRule,
    RuleSource,
    Transaction,
)

DEFAULT_CATEGORIES = [
    "Supermarket",
    "Restaurant",
    "Transport",
    "Shopping",
    "Entertainment",
    "Travel",
    "Housing",
    "Health",
    "Subscriptions",
    "Salary",
    "Transfers",
    "Other",
]

# normalized_description (lowercased substring after normalization) -> category.
# Seeded rules; the learned map grows on top of these via use + manual corrections.
SEED_RULES: dict[str, str] = {
    # ===== Spain =====
    # Supermarkets
    "mercadona": "Supermarket",
    "carrefour": "Supermarket",
    "lidl": "Supermarket",
    "dia": "Supermarket",
    "alcampo": "Supermarket",
    "ahorramas": "Supermarket",
    # Restaurants / food delivery (observed in sample: wetaca, pret a manger, brunchit, full of beans, taura)
    "wetaca": "Restaurant",
    "pret a ma": "Restaurant",
    "pret a manger": "Restaurant",
    "brunchit": "Restaurant",
    "full of beans": "Restaurant",
    "taura": "Restaurant",
    "glovo": "Restaurant",
    "uber eats": "Restaurant",
    "just eat": "Restaurant",
    "telepizza": "Restaurant",
    "100 montaditos": "Restaurant",
    # Transport (taxis observed: licencia NNNNN, taxi lic, l: NNNNN)
    "renfe": "Transport",
    "metro madrid": "Transport",
    "cercanias": "Transport",
    "emt madrid": "Transport",
    "taxi": "Transport",
    "taxi lic": "Transport",
    "licencia": "Transport",
    "free now": "Transport",
    "bolt": "Transport",
    # Shopping
    "el corte ingles": "Shopping",
    "zara": "Shopping",
    "decathlon": "Shopping",
    "ikea": "Shopping",
    "amazon": "Shopping",
    # Recurring household bills folded into Subscriptions — Utilities was
    # removed from the taxonomy; telecom + electric + water all show up as
    # monthly Subscriptions to the user.
    "iberdrola": "Subscriptions",
    "endesa": "Subscriptions",
    "movistar": "Subscriptions",
    "vodafone": "Subscriptions",
    "orange": "Subscriptions",
    # ===== Chile =====
    "jumbo": "Supermarket",
    "lider": "Supermarket",
    "santa isabel": "Supermarket",
    "unimarc": "Supermarket",
    "tottus": "Supermarket",
    "enel": "Subscriptions",
    "aguas andinas": "Subscriptions",
    "metro santiago": "Transport",
    "metro stgo": "Transport",
    "bip": "Transport",
    "uber": "Transport",
    "cabify": "Transport",
    "didi": "Transport",
    "pedidosya": "Restaurant",
    "rappi": "Restaurant",
    "falabella": "Shopping",
    "paris": "Shopping",
    "ripley": "Shopping",
    # ===== Travel (observed: trip.com, booking.com) =====
    "trip.com": "Travel",
    "booking.com": "Travel",
    "airbnb": "Travel",
    "ryanair": "Travel",
    "vueling": "Travel",
    "iberia": "Travel",
    "latam": "Travel",
    # ===== Subscriptions (observed: apple.com/bill, grok xai) =====
    "apple.com/bill": "Subscriptions",
    "apple.com bill": "Subscriptions",
    "grok xai": "Subscriptions",
    "openai": "Subscriptions",
    "anthropic": "Subscriptions",
    "icloud": "Subscriptions",
    "github": "Subscriptions",
    # ===== Entertainment / streaming =====
    "netflix": "Entertainment",
    "spotify": "Entertainment",
    "amazon prime": "Entertainment",
    "disney": "Entertainment",
    "hbo": "Entertainment",
    "cinepolis": "Entertainment",
    "cinesa": "Entertainment",
    # ===== Other (taxes are out of scope but flag them) =====
    "agencia tributaria": "Other",
    "aeat": "Other",
}


def seed(db: Session) -> None:
    _migrate_retired_categories(db)
    _seed_categories(db)
    _seed_rules(db)
    _seed_assumptions(db)
    _seed_manual_account(db)
    db.commit()


# Categories that used to exist in the taxonomy but have been folded into another.
# Keyed by old name -> new name. Existing rows pointing at the old name are
# rewritten on every boot so the DB stays consistent with the seed file.
_RETIRED_CATEGORIES: dict[str, str] = {
    "Utilities": "Subscriptions",
}


def _migrate_retired_categories(db: Session) -> None:
    """Rewrite any rules/transactions still pointing at a retired category, then
    drop the orphan Category row. Idempotent — once the rows are gone this is
    a no-op."""
    from sqlalchemy import update
    for old, new in _RETIRED_CATEGORIES.items():
        db.execute(update(CategoryRule).where(CategoryRule.category == old).values(category=new))
        db.execute(update(Transaction).where(Transaction.category == old).values(category=new))
        cat = db.execute(select(Category).where(Category.name == old)).scalar_one_or_none()
        if cat is not None:
            db.delete(cat)


def _seed_manual_account(db: Session) -> None:
    """A catch-all account for hand-entered transactions (cash, IOUs, anything
    not tied to a real bank statement). The transaction itself carries its own
    currency, so the account's native_currency is only a default hint.
    """
    existing = db.execute(select(Account).where(Account.name == "Manual")).scalar_one_or_none()
    if existing is None:
        db.add(
            Account(
                name="Manual",
                institution=None,
                country="ES",
                type=AccountType.checking,
                native_currency="EUR",
            )
        )


def _seed_categories(db: Session) -> None:
    existing = set(db.execute(select(Category.name)).scalars().all())
    for name in DEFAULT_CATEGORIES:
        if name not in existing:
            db.add(Category(name=name, is_system=True))


def _seed_rules(db: Session) -> None:
    existing = set(db.execute(select(CategoryRule.normalized_description)).scalars().all())
    for pattern, category in SEED_RULES.items():
        if pattern not in existing:
            db.add(CategoryRule(normalized_description=pattern, category=category, source=RuleSource.rule))


def _seed_assumptions(db: Session) -> None:
    row = db.execute(select(Assumptions).limit(1)).scalar_one_or_none()
    if row is None:
        db.add(Assumptions())
