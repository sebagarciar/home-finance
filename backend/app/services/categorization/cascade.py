"""Categorization cascade.

For a given normalized merchant key, return (category, source) by walking:
    1. Exact match in `category_rules` (learned + seeded)
    2. Substring/contains match against seeded rule patterns (allows merchant
       names that include the rule key, e.g. "wetaca" inside a longer string)
    3. Fuzzy match in `category_rules` via rapidfuzz (handles near-misses)
    4. Local Ollama (if enabled and reachable)
    5. Fallback to "Other"

Every successful classification from steps 2-4 is written back to `category_rules`
so the next occurrence hits step 1 instantly.

Manual corrections (UI) are written back with source=manual via a separate path
and always win over future automatic results.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Category, CategoryRule
from ...models.categories import RuleSource
from .ollama import classify_with_ollama

log = logging.getLogger(__name__)

FUZZY_THRESHOLD = 85  # 0..100, rapidfuzz full-string ratio (NOT partial_ratio)
MIN_FUZZY_KEY_CHARS = 5  # below this, fuzzy is too risky — skip to LLM
MIN_CONTAINS_KEY_CHARS = 4  # don't substring-match against rule keys shorter than this
FALLBACK_CATEGORY = "Other"


@dataclass
class Classification:
    category: str
    source: RuleSource


def _load_taxonomy(db: Session) -> list[str]:
    return list(db.execute(select(Category.name)).scalars().all())


def load_rules(db: Session) -> list[CategoryRule]:
    """Load all category rules once. Callers doing many classifications in a
    batch (e.g. an import) pass this list back into `classify` so the cascade
    scans in memory instead of re-querying the whole table per row."""
    return list(db.execute(select(CategoryRule)).scalars().all())


def _exact_lookup(rules: list[CategoryRule], key: str) -> Classification | None:
    if not key:
        return None
    for r in rules:
        if r.normalized_description == key:
            return Classification(category=r.category, source=r.source)
    return None


def _contains_lookup(rules: list[CategoryRule], key: str) -> Classification | None:
    """A seeded rule's key may be a substring of the merchant key.
    e.g. seed `wetaca` matches normalized merchant `wetaca madrid centro`.
    Walks rules from shortest key first so we match the most specific token.
    """
    if not key:
        return None
    # Rule key must be at least MIN_CONTAINS_KEY_CHARS to count, AND it must
    # appear as a whole word in the merchant key (so "ta" doesn't match "tau...",
    # but "uber" still matches "uber eats pending amsterdam").
    padded_key = f" {key} "
    candidates = []
    for r in rules:
        rk = r.normalized_description
        if len(rk) < MIN_CONTAINS_KEY_CHARS:
            continue
        # Whole-word containment: pad with spaces so we match token boundaries.
        if f" {rk} " in padded_key:
            candidates.append(r)
    if not candidates:
        return None
    best = max(candidates, key=lambda r: len(r.normalized_description))
    return Classification(category=best.category, source=best.source)


def _fuzzy_lookup(rules: list[CategoryRule], key: str) -> Classification | None:
    if not key or len(key) < MIN_FUZZY_KEY_CHARS:
        return None
    if not rules:
        return None
    # Use full-string ratio (NOT partial_ratio) so a short merchant key like
    # "madrid" doesn't latch onto every rule that contains "madrid". We only
    # want fuzzy matches for typos / near-misses of comparable length.
    choices = {r.normalized_description: r for r in rules}
    match = process.extractOne(
        key, list(choices.keys()), scorer=fuzz.ratio, score_cutoff=FUZZY_THRESHOLD
    )
    if match is None:
        return None
    key_match, _score, _ = match
    rule = choices[key_match]
    return Classification(category=rule.category, source=rule.source)


def _writeback(
    db: Session, rules: list[CategoryRule], key: str, category: str, source: RuleSource
) -> None:
    """Upsert a rule for `key` so future occurrences hit the exact lookup.

    Mutates `rules` in place so subsequent classify() calls sharing the same
    list see the new rule without re-querying. Flushes so the row is visible to
    SELECTs in the same session — without this, batched imports collide on the
    unique constraint.
    """
    if not key:
        return
    existing = next((r for r in rules if r.normalized_description == key), None)
    if existing is None:
        rule = CategoryRule(normalized_description=key, category=category, source=source)
        db.add(rule)
        rules.append(rule)
    elif existing.source != RuleSource.manual:
        # Don't overwrite a manual correction with an automatic one.
        existing.category = category
        existing.source = source
    db.flush()


def classify(
    db: Session, normalized_merchant: str, rules: list[CategoryRule] | None = None
) -> Classification:
    # Empty / pure-noise keys (e.g. "Money added via BIZUM" -> "") can't be
    # classified meaningfully. Return Other WITHOUT writeback so we don't
    # pollute category_rules with garbage keys.
    if not normalized_merchant or len(normalized_merchant) < 3:
        return Classification(category=FALLBACK_CATEGORY, source=RuleSource.llm)

    # Load rules once for one-off callers; batch callers pass a shared list so
    # the whole import scans in memory rather than re-querying per row.
    if rules is None:
        rules = load_rules(db)

    # 1. Exact
    hit = _exact_lookup(rules, normalized_merchant)
    if hit is not None:
        return hit

    # 2. Substring (seeded rules may be partial keys)
    hit = _contains_lookup(rules, normalized_merchant)
    if hit is not None:
        _writeback(db, rules, normalized_merchant, hit.category, RuleSource.learned)
        return Classification(category=hit.category, source=RuleSource.learned)

    # 3. Fuzzy
    hit = _fuzzy_lookup(rules, normalized_merchant)
    if hit is not None:
        _writeback(db, rules, normalized_merchant, hit.category, RuleSource.learned)
        return Classification(category=hit.category, source=RuleSource.learned)

    # 4. Ollama
    taxonomy = _load_taxonomy(db)
    llm_category = classify_with_ollama(normalized_merchant, taxonomy)
    if llm_category is not None:
        _writeback(db, rules, normalized_merchant, llm_category, RuleSource.llm)
        return Classification(category=llm_category, source=RuleSource.llm)

    # 5. Fallback — do NOT write back; we don't want "Other" to stick if a rule
    # gets added later. Leaving no rule means the cascade re-runs next time.
    return Classification(category=FALLBACK_CATEGORY, source=RuleSource.llm)


def apply_manual_correction(db: Session, normalized_merchant: str, category: str) -> None:
    """User said this merchant is `category`. Lock it in with source=manual."""
    if not normalized_merchant:
        return
    existing = db.execute(
        select(CategoryRule).where(CategoryRule.normalized_description == normalized_merchant)
    ).scalar_one_or_none()
    if existing is None:
        db.add(CategoryRule(normalized_description=normalized_merchant, category=category, source=RuleSource.manual))
    else:
        existing.category = category
        existing.source = RuleSource.manual
