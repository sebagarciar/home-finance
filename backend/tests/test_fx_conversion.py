from datetime import date
from decimal import Decimal

from app.models.fx import FxRate
from app.services.fx import get_rate, to_base, to_base_current


def test_to_base_same_currency_is_identity(db):
    assert to_base(db, Decimal("100"), "CLP", date(2025, 1, 1)) == Decimal("100")


def test_to_base_historical_uses_date_specific_rate(db, stub_fx):
    provider = stub_fx({
        (date(2025, 1, 1), "EUR", "CLP"): Decimal("1000"),
        (date(2025, 6, 1), "EUR", "CLP"): Decimal("1100"),
    })
    # 100 EUR on Jan 1 should be 100,000 CLP
    assert to_base(db, Decimal("100"), "EUR", date(2025, 1, 1), provider=provider) == Decimal("100000")
    # Same 100 EUR on Jun 1 should be 110,000 CLP — proves the historical rate is used.
    assert to_base(db, Decimal("100"), "EUR", date(2025, 6, 1), provider=provider) == Decimal("110000")


def test_get_rate_caches_in_db(db, stub_fx):
    provider = stub_fx({(date(2025, 3, 1), "EUR", "CLP"): Decimal("1050")})
    r1 = get_rate(db, date(2025, 3, 1), "EUR", "CLP", provider=provider)
    r2 = get_rate(db, date(2025, 3, 1), "EUR", "CLP", provider=provider)
    assert r1 == r2 == Decimal("1050")
    # Second call must hit the cache, not the provider.
    assert len(provider.calls) == 1
    cached = db.query(FxRate).filter_by(date=date(2025, 3, 1), base_currency="EUR", quote_currency="CLP").one()
    assert Decimal(str(cached.rate)) == Decimal("1050")


def test_to_base_current_uses_latest(db, stub_fx):
    # Latest (None) cache; to_base_current must hit it.
    provider = stub_fx({(None, "USD", "CLP"): Decimal("950")})
    assert to_base_current(db, Decimal("1000"), "USD", provider=provider) == Decimal("950000")


def test_usd_holding_to_clp_two_hop(db, stub_fx):
    """A USD-priced holding worth $10,000 at current USD/CLP=950 should be 9,500,000 CLP."""
    provider = stub_fx({(None, "USD", "CLP"): Decimal("950")})
    qty = Decimal("100")
    price_usd = Decimal("100")  # 100 * 100 = 10,000 USD
    value_native = qty * price_usd
    value_base = to_base_current(db, value_native, "USD", provider=provider)
    assert value_base == Decimal("9500000")


def test_usd_holding_via_eur_pricing_does_not_pre_convert(db, stub_fx):
    """Sanity: if a holding is priced in EUR, we go EUR->CLP directly, not via USD."""
    provider = stub_fx({(None, "EUR", "CLP"): Decimal("1100")})
    value_native = Decimal("500")  # 500 EUR
    value_base = to_base_current(db, value_native, "EUR", provider=provider)
    assert value_base == Decimal("550000")
