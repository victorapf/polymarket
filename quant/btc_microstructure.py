"""
CAPA 4.3 - Confirmacion por microestructura para BTC 15m.

No basta con que el precio suba: se exige que el movimiento este respaldado
por absorcion real de volumen (CVD positivo sostenido) y desequilibrio del
libro (mas profundidad del lado agresor), para filtrar movimientos de "mecha"
sin sustento que revertirian antes del cierre de la ventana de 15 minutos.
"""
from __future__ import annotations

from dataclasses import dataclass

from data_engine.binance_ws import OrderFlowState


@dataclass
class MicrostructureSignal:
    direction: str  # "UP" | "DOWN" | "NEUTRAL"
    cvd_60s: float
    book_imbalance: float
    confirmed: bool


def book_imbalance(state: OrderFlowState) -> float:
    """
    Valor entre -1 (todo el libro es ask/venta) y +1 (todo el libro es bid/compra).
    """
    total = state.bid_depth + state.ask_depth
    if total == 0:
        return 0.0
    return (state.bid_depth - state.ask_depth) / total


def evaluate_signal(
    state: OrderFlowState,
    cvd_threshold: float = 5.0,
    imbalance_threshold: float = 0.15,
) -> MicrostructureSignal:
    cvd = state.cvd_last_n_seconds(60)
    imbalance = book_imbalance(state)

    up_confirmed = cvd > cvd_threshold and imbalance > imbalance_threshold
    down_confirmed = cvd < -cvd_threshold and imbalance < -imbalance_threshold

    if up_confirmed:
        direction = "UP"
    elif down_confirmed:
        direction = "DOWN"
    else:
        direction = "NEUTRAL"

    return MicrostructureSignal(
        direction=direction,
        cvd_60s=cvd,
        book_imbalance=imbalance,
        confirmed=direction != "NEUTRAL",
    )
