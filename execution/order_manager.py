"""
CAPA 3.3 - Eliminacion de taker fees mediante ordenes limite + rutina cancel-replace.

Solo se opera con Limit Orders al precio del libro (nunca Market Orders). Si
la orden no se llena dentro de `timeout_s`, se cancela y se reajusta el precio
(sigue el book) para intentar de nuevo, con un numero maximo de reintentos.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

import structlog

from execution.token_id import TokenId

logger = structlog.get_logger()


class ClobClientProtocol(Protocol):
    """
    Interfaz minima que tanto PolymarketClobWrapper (real) como PaperClobClient
    (simulado) cumplen. Usar un Protocol en vez de importar PolymarketClobWrapper
    directamente evita que este modulo arrastre py-clob-client como dependencia
    dura solo para operar en modo paper-trading.
    """

    def get_orderbook(self, token_id: TokenId) -> dict: ...
    def place_limit_order(self, token_id: TokenId, price: Decimal, size: Decimal, side: str) -> dict: ...
    def cancel_order(self, order_id: str) -> dict: ...
    def get_order_status(self, order_id: str) -> dict: ...


@dataclass
class CancelReplaceResult:
    filled: bool
    order_id: str | None
    final_price: Decimal | None
    attempts: int


class CancelReplaceOrderManager:
    def __init__(self, clob: ClobClientProtocol, timeout_s: float = 1.5, max_attempts: int = 5):
        self.clob = clob
        self.timeout_s = timeout_s
        self.max_attempts = max_attempts

    async def execute_limit_buy(
        self, token_id: TokenId, size: Decimal, starting_price: Decimal, side: str = "BUY"
    ) -> CancelReplaceResult:
        price = starting_price
        order_id: str | None = None

        for attempt in range(1, self.max_attempts + 1):
            response = self.clob.place_limit_order(token_id, price, size, side)
            order_id = response.get("orderID") or response.get("order_id")
            logger.info("order.placed", token_id=str(token_id), price=str(price), attempt=attempt)

            filled = await self._wait_for_fill(order_id)
            if filled:
                return CancelReplaceResult(True, order_id, price, attempt)

            # No se lleno a tiempo: cancelar y reajustar precio siguiendo el libro
            self.clob.cancel_order(order_id)
            orderbook = self.clob.get_orderbook(token_id)
            price = self._next_price(orderbook, side, price)
            logger.info("order.cancel_replace", token_id=str(token_id), new_price=str(price))

        return CancelReplaceResult(False, order_id, price, self.max_attempts)

    async def _wait_for_fill(self, order_id: str) -> bool:
        elapsed = 0.0
        poll_interval = 0.2
        while elapsed < self.timeout_s:
            status = self.clob.get_order_status(order_id)
            if status.get("status") == "FILLED":
                return True
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        return False

    def _next_price(self, orderbook: dict, side: str, current_price: Decimal) -> Decimal:
        """Sigue el book: si compramos, subimos al siguiente mejor ask disponible."""
        book_side = orderbook.get("asks" if side == "BUY" else "bids", [])
        for price, _size in book_side:
            p = Decimal(str(price))
            if (side == "BUY" and p > current_price) or (side == "SELL" and p < current_price):
                return p
        return current_price  # sin mejor nivel disponible, mantener
