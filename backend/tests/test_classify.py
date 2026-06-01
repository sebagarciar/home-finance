"""Categorization cascade tests.

Ollama is patched out so tests run offline and are deterministic.
"""
from __future__ import annotations

import pytest

from app.models import CategoryRule
from app.models.categories import RuleSource
from app.seeds.defaults import seed
from app.services.categorization import classify
from app.services.categorization.cascade import apply_manual_correction


@pytest.fixture
def seeded_db(db):
    seed(db)
    return db


def _patch_ollama(monkeypatch, return_value):
    """Make the LLM step deterministic."""
    from app.services.categorization import cascade
    monkeypatch.setattr(cascade, "classify_with_ollama", lambda *a, **kw: return_value)


def test_step1_exact_match_hits_seeded_rule(seeded_db, monkeypatch):
    _patch_ollama(monkeypatch, None)
    c = classify(seeded_db, "wetaca")
    assert c.category == "Restaurant"
    # No write-back needed — it was already an exact match.


def test_step2_substring_match_for_longer_merchant_key(seeded_db, monkeypatch):
    _patch_ollama(monkeypatch, None)
    # "wetaca madrid centro" should match the seeded "wetaca" rule.
    c = classify(seeded_db, "wetaca madrid centro")
    assert c.category == "Restaurant"
    # Substring/fuzzy promotes a learned rule for the longer key.
    seeded_db.commit()
    learned = seeded_db.query(CategoryRule).filter_by(normalized_description="wetaca madrid centro").one()
    assert learned.category == "Restaurant"
    assert learned.source == RuleSource.learned


def test_step3_fuzzy_match(seeded_db, monkeypatch):
    _patch_ollama(monkeypatch, None)
    # Typo / near-miss should fuzzy-match an existing rule.
    c = classify(seeded_db, "mercadnoa")  # missing letter
    assert c.category == "Supermarket"


def test_step4_ollama_is_used_when_rules_miss(seeded_db, monkeypatch):
    _patch_ollama(monkeypatch, "Restaurant")
    c = classify(seeded_db, "completely unknown bistro xyz")
    assert c.category == "Restaurant"
    assert c.source == RuleSource.llm
    # Written back so the next call hits step 1.
    seeded_db.commit()
    rule = seeded_db.query(CategoryRule).filter_by(normalized_description="completely unknown bistro xyz").one()
    assert rule.source == RuleSource.llm


def test_fallback_to_other_when_ollama_unreachable(seeded_db, monkeypatch):
    _patch_ollama(monkeypatch, None)
    c = classify(seeded_db, "definitely not in any rule set")
    assert c.category == "Other"
    # No rule written back — keeps the cascade re-trying on next pass.
    seeded_db.commit()
    assert seeded_db.query(CategoryRule).filter_by(
        normalized_description="definitely not in any rule set"
    ).first() is None


def test_manual_correction_locks_in_and_wins_over_future_llm(seeded_db, monkeypatch):
    apply_manual_correction(seeded_db, "grok xai palo alto", "Subscriptions")
    seeded_db.commit()

    # Even if Ollama would have said something else, the exact lookup wins now.
    _patch_ollama(monkeypatch, "Shopping")
    c = classify(seeded_db, "grok xai palo alto")
    assert c.category == "Subscriptions"
    assert c.source == RuleSource.manual

    # And the writeback path must NOT overwrite a manual rule.
    rule = seeded_db.query(CategoryRule).filter_by(normalized_description="grok xai palo alto").one()
    assert rule.source == RuleSource.manual
    assert rule.category == "Subscriptions"
