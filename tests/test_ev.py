from decimal import Decimal

import pytest

from quant.ev import compute_ev, is_positive_ev


def test_positive_ev():
    # modelo cree 60%, mercado precio 0.5 (cuota implicita 2.0) -> EV = 0.6*2 - 1 = 0.2
    ev = compute_ev(Decimal("0.6"), Decimal("0.5"))
    assert ev == Decimal("0.2")


def test_negative_ev():
    # modelo cree 40%, mercado precio 0.5 -> EV = 0.4*2 - 1 = -0.2
    ev = compute_ev(Decimal("0.4"), Decimal("0.5"))
    assert ev == Decimal("-0.2")


def test_is_positive_ev_threshold():
    assert is_positive_ev(Decimal("0.6"), Decimal("0.5"), min_edge=Decimal("0.1"))
    assert not is_positive_ev(Decimal("0.55"), Decimal("0.5"), min_edge=Decimal("0.1"))


def test_invalid_market_price_raises():
    with pytest.raises(ValueError):
        compute_ev(Decimal("0.5"), Decimal("0"))
