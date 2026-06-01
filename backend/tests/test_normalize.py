from app.services.categorization.normalize import normalize_description as n


def test_strips_santander_pago_movil():
    assert n("PAGO MOVIL EN BRUNCHIT MARIA, VITRUVIO ES, TARJ. :*333653") == "brunchit maria vitruvio"


def test_strips_santander_compra_with_card_and_commission():
    # Amsterdam is stripped as a city stopword so the key is stable across
    # transactions at the same merchant in different cities.
    assert n("COMPRA TRIP.COM, AMSTERDAM, TARJETA 5489010516333653 , COMISION 5,11") == "trip.com"


def test_strips_sq_acquirer_prefix():
    assert n("COMPRA SQ *FULL OF BEANS SL, Madrid, TARJETA 5489010516333653 , COMISION 0,00") == "full of beans sl"


def test_strips_till_number_prefix():
    assert n("PAGO MOVIL EN 218 - PRET A MA, MADRID ES, TARJ. :*333653") == "pret a ma"


def test_keeps_merchant_kind_when_only_reference_id_remains():
    # Taxi rows: the bank stores the license number as the "merchant", and the
    # actual merchant indicator is the word "licencia". Normalization must keep
    # it (not strip it together with the number) so the seeded `licencia` rule
    # matches.
    assert n("PAGO MOVIL EN LICENCIA 10691, MADRID ES, TARJ. :*333653") == "licencia"
    assert n("PAGO MOVIL EN TAXI LIC. 13818, MADRID ES, TARJ. :*333653") == "taxi lic"


def test_drops_long_reference_runs():
    # Should drop the long numeric reference, leaving just the merchant.
    assert n("TARGET PL 10079330 10079330") == "target pl"


def test_revolut_card_payment_to_merchant():
    assert n("Card Payment Wetaca") == "wetaca"


def test_handles_bizum_money_added():
    # Pure boilerplate -> empty key (this is a deposit; category falls through to Other)
    assert n("Money added via BIZUM") == ""


def test_strips_accents():
    assert n("COMPRA CAFÉ MADRID, TARJETA 1234") == "cafe"


def test_repeated_merchant_collapses_across_amazon_orders():
    # The Amazon Marketplace prefix carries a different order ID each time;
    # normalization must collapse them.
    assert n("AMZN MKTP ES*1A2B3C, MADRID ES, TARJ. :*333653") == n(
        "AMZN MKTP ES*9X8Y7W, MADRID ES, TARJ. :*333653"
    )
