from decimal import Decimal

from quant.kelly import kelly_fraction_full, position_size


def test_kelly_zero_edge_gives_zero_fraction():
    # p=0.5, precio=0.5 -> b=1, no hay edge -> f* = 0
    f = kelly_fraction_full(Decimal("0.5"), Decimal("1"))
    assert f == Decimal("0")


def test_kelly_positive_edge():
    # p=0.6, precio=0.5 -> b=1 -> f* = (0.6*1 - 0.4)/1 = 0.2
    f = kelly_fraction_full(Decimal("0.6"), Decimal("1"))
    assert f == Decimal("0.2")


def test_position_size_respects_hard_cap():
    size = position_size(
        bankroll=Decimal("1000"),
        win_probability=Decimal("0.95"),
        market_price=Decimal("0.10"),
        kelly_multiplier=Decimal("1.0"),  # full kelly, edge enorme
    )
    # el tope duro es 10% del bankroll
    assert size <= Decimal("100.00")


def test_position_size_scales_with_multiplier():
    full = position_size(Decimal("1000"), Decimal("0.6"), Decimal("0.5"), Decimal("1.0"))
    quarter = position_size(Decimal("1000"), Decimal("0.6"), Decimal("0.5"), Decimal("0.25"))
    assert quarter < full
