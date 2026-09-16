"""CAPA 4.1 - Esperanza Matematica (Value Betting). El bot solo opera si EV > 0."""
from __future__ import annotations

from decimal import Decimal


def compute_ev(model_probability: Decimal, market_price: Decimal) -> Decimal:
    """
    EV = (P_modelo * Cuota_mercado) - 1

    En Polymarket, "Cuota_mercado" equivale a 1/precio_del_token (el token paga
    $1 si acierta). Se acepta directamente el payout implicito para evitar
    ambiguedad: `market_price` es el precio del token (0 a 1), y la cuota
    decimal implicita es 1/market_price.
    """
    if market_price <= 0:
        raise ValueError("market_price debe ser > 0")
    implied_odds = Decimal(1) / market_price
    return (model_probability * implied_odds) - Decimal(1)


def is_positive_ev(model_probability: Decimal, market_price: Decimal, min_edge: Decimal = Decimal("0")) -> bool:
    return compute_ev(model_probability, market_price) > min_edge
