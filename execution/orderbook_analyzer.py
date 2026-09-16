"""
CAPA 3.4 - Control de slippage y liquidez.

Antes de enviar una orden, se consultan las primeras 3 capas del libro de
asks (para compras) y se calcula el precio promedio ponderado (VWAP de
ejecucion). Si el slippage resultante frente al mejor precio excede 1.5%, o
el spread bid/ask supera 2%, la orden se cancela o se fragmenta.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

DEPTH_LEVELS = 3


@dataclass
class LiquidityCheckResult:
    approved: bool
    reason: str
    expected_avg_price: Decimal
    slippage_pct: Decimal
    spread_pct: Decimal
    fillable_size: Decimal


class OrderbookAnalyzer:
    def __init__(self, max_slippage_pct: Decimal, max_spread_pct: Decimal):
        self.max_slippage_pct = max_slippage_pct
        self.max_spread_pct = max_spread_pct

    @staticmethod
    def _spread_pct(best_bid: Decimal, best_ask: Decimal) -> Decimal:
        if best_bid <= 0:
            return Decimal("1")
        return (best_ask - best_bid) / best_bid

    def evaluate_buy(self, orderbook: dict, desired_size: Decimal) -> LiquidityCheckResult:
        """
        orderbook esperado: {"bids": [[price, size], ...], "asks": [[price, size], ...]}
        ordenado de mejor a peor precio.
        """
        asks = [(Decimal(str(p)), Decimal(str(s))) for p, s in orderbook.get("asks", [])][:DEPTH_LEVELS]
        bids = orderbook.get("bids", [])

        if not asks:
            return LiquidityCheckResult(False, "sin_liquidez_asks", Decimal(0), Decimal(0), Decimal(1), Decimal(0))

        best_ask = asks[0][0]
        best_bid = Decimal(str(bids[0][0])) if bids else Decimal(0)
        spread_pct = self._spread_pct(best_bid, best_ask)

        remaining = desired_size
        cost = Decimal(0)
        filled = Decimal(0)
        for price, size in asks:
            take = min(remaining, size)
            cost += take * price
            filled += take
            remaining -= take
            if remaining <= 0:
                break

        if filled == 0:
            return LiquidityCheckResult(False, "sin_fill_en_profundidad", Decimal(0), Decimal(0), spread_pct, Decimal(0))

        avg_price = cost / filled
        slippage_pct = (avg_price - best_ask) / best_ask if best_ask > 0 else Decimal(1)

        if spread_pct > self.max_spread_pct:
            return LiquidityCheckResult(False, "spread_excesivo", avg_price, slippage_pct, spread_pct, filled)
        if slippage_pct > self.max_slippage_pct:
            return LiquidityCheckResult(False, "slippage_excesivo", avg_price, slippage_pct, spread_pct, filled)
        if filled < desired_size:
            # liquidez insuficiente para el tamano completo -> se recomienda fragmentar
            return LiquidityCheckResult(False, "liquidez_insuficiente_fragmentar", avg_price, slippage_pct, spread_pct, filled)

        return LiquidityCheckResult(True, "ok", avg_price, slippage_pct, spread_pct, filled)
