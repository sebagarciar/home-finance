from app.models import Assumptions, Category, CategoryRule
from app.seeds.defaults import seed


def test_seed_is_idempotent(db):
    seed(db)
    seed(db)
    cats = db.query(Category).count()
    rules = db.query(CategoryRule).count()
    assumptions = db.query(Assumptions).count()
    assert cats >= 12  # default taxonomy
    assert rules >= 20  # ES + CL + subscriptions
    assert assumptions == 1


def test_seed_includes_es_and_cl_merchants(db):
    seed(db)
    norms = {r.normalized_description for r in db.query(CategoryRule).all()}
    assert "mercadona" in norms
    assert "jumbo" in norms
    assert "enel" in norms
    assert "renfe" in norms
