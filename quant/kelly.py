"""
CAPA 4.4 - Dimensionamiento de posiciones via Criterio de Kelly Fraccionado.

f* = (p*b - (1-p)) / b

  p: probabilidad de exito segun el modelo
  b: cuota neta (payout por unidad apostada, ej. si el token cuesta 0.40, b = (1/0.40) - 1 = 1.5)

Se aplica una fraccion (1/4 o 1/2) del Kelly completo para reducir varianza y
evitar quiebra en rachas perdedoras, y se acota el resultado a un maximo
razonable del capital.
"""
from __future__ import annotations

from decimal import Decimal

MAX_POSITION_PCT_OF_BANKROLL = Decimal("0.10")  # tope duro independiente de Kelly


def kelly_fraction_full(win_probability: Decimal, net_odds_b: Decimal) -> Decimal:
    if net_odds_b <= 0:
        return Decimal(0)
    f_star = (win_probability * net_odds_b - (1 - win_probability)) / net_odds_b
    return max(f_star, Decimal(0))


def position_size(
    bankroll: Decimal,
    win_probability: Decimal,
    market_price: Decimal,
    kelly_multiplier: Decimal = Decimal("0.25"),
) -> Decimal:
    """
    market_price: precio del token (0-1). net_odds_b se deriva de el.
    kelly_multiplier: 0.25 = 1/4 Kelly (default conservador), 0.5 = 1/2 Kelly.
    """
    if market_price <= 0 or market_price >= 1:
        raise ValueError("market_price debe estar en (0, 1)")

    net_odds_b = (Decimal(1) / market_price) - Decimal(1)
    full_kelly = kelly_fraction_full(win_probability, net_odds_b)
    fractional_kelly = full_kelly * kelly_multiplier

    capped_fraction = min(fractional_kelly, MAX_POSITION_PCT_OF_BANKROLL)
    return (bankroll * capped_fraction).quantize(Decimal("0.01"))
