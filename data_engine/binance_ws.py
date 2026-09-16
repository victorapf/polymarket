"""
CAPA 1.3 - Feed de BTC de baja latencia via WebSockets asincronos.

Se suscribe a @aggTrade (para CVD) y @depth (para book imbalance) en lugar de
poll-eo REST, evitando los 300ms-1s de latencia que destruirian el margen en
mercados de 15 minutos.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from dataclasses import dataclass, field

import structlog
import websockets

from config.settings import settings

logger = structlog.get_logger()


@dataclass
class OrderFlowState:
    """Estado rolling de order flow, consumido por quant/btc_microstructure.py"""
    last_price: float = 0.0
    cumulative_volume_delta: float = 0.0
    best_bid: float = 0.0
    best_ask: float = 0.0
    bid_depth: float = 0.0
    ask_depth: float = 0.0
    last_update_ms: int = 0
    _trade_window: deque = field(default_factory=lambda: deque(maxlen=2000))

    def record_trade(self, price: float, qty: float, is_buyer_maker: bool) -> None:
        # is_buyer_maker=True significa que el agresor fue un vendedor -> delta negativo
        signed_qty = -qty if is_buyer_maker else qty
        self.cumulative_volume_delta += signed_qty
        self._trade_window.append((time.time(), signed_qty))
        self.last_price = price

    def cvd_last_n_seconds(self, seconds: int = 60) -> float:
        cutoff = time.time() - seconds
        return sum(q for ts, q in self._trade_window if ts >= cutoff)


class BinanceOrderFlowStream:
    def __init__(self, symbol: str = "btcusdt", state: OrderFlowState | None = None):
        self.symbol = symbol.lower()
        self.state = state or OrderFlowState()
        self._stop = asyncio.Event()

    def _stream_url(self) -> str:
        streams = f"{self.symbol}@aggTrade/{self.symbol}@depth20@100ms"
        return f"{settings.binance_ws_base}/stream?streams={streams}"

    async def run(self) -> None:
        """
        Loop de reconexion resiliente con watchdog de silencio.

        Ademas de reaccionar a que el socket se cierre (ConnectionClosed/OSError),
        se envuelve cada lectura en un timeout corto: si Binance deja de mandar
        datos sin cerrar formalmente la conexion (desconexion "silenciosa"), el
        bot lo detecta en <= STALE_TIMEOUT_S en vez de quedarse esperando
        indefinidamente con datos desactualizados.
        """
        STALE_TIMEOUT_S = 3.0

        while not self._stop.is_set():
            try:
                async with websockets.connect(self._stream_url(), ping_interval=15) as ws:
                    logger.info("binance_ws.connected", symbol=self.symbol)
                    while not self._stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=STALE_TIMEOUT_S)
                        except asyncio.TimeoutError:
                            logger.warning(
                                "binance_ws.stale_connection",
                                symbol=self.symbol,
                                seconds=STALE_TIMEOUT_S,
                            )
                            break  # sale del while interno -> fuerza reconexion abajo
                        self._handle_message(json.loads(raw))
            except (websockets.ConnectionClosed, OSError) as exc:
                logger.warning("binance_ws.connection_lost", error=str(exc))
            except Exception as exc:  # defensivo: nunca dejar morir el loop de reconexion
                logger.error("binance_ws.unexpected_error", error=str(exc))

            if not self._stop.is_set():
                await asyncio.sleep(1.0)  # backoff simple antes de reconectar

    def _handle_message(self, msg: dict) -> None:
        stream = msg.get("stream", "")
        data = msg.get("data", {})
        now_ms = int(time.time() * 1000)

        if stream.endswith("@aggTrade"):
            price = float(data["p"])
            qty = float(data["q"])
            is_buyer_maker = bool(data["m"])
            self.state.record_trade(price, qty, is_buyer_maker)
            self.state.last_update_ms = now_ms

        elif "@depth" in stream:
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            if bids:
                self.state.best_bid = float(bids[0][0])
                self.state.bid_depth = sum(float(sz) for _, sz in bids[:5])
            if asks:
                self.state.best_ask = float(asks[0][0])
                self.state.ask_depth = sum(float(sz) for _, sz in asks[:5])
            self.state.last_update_ms = now_ms

    def stop(self) -> None:
        self._stop.set()
