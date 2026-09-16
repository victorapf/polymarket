"""
Cliente de paper-trading: misma interfaz publica que PolymarketClobWrapper
(get_orderbook, get_fee_rate_bps, place_limit_order, cancel_order,
get_order_status) pero opera contra un libro simulado en memoria, sin firmar
nada, sin gas y sin tocar la PRIVATE_KEY real.

Uso: correr localmente antes de conectar el VPS o capital real, para validar
que la logica de decision (EV, Kelly, gates) hace lo que esperas contra
escenarios de mercado que tu defines.
"""
from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from execution.token_id import TokenId


@dataclass
class SimulatedMarket:
    """Libro de ordenes sintetico para un token dado. Tu lo defines o lo generas."""
    token_id: str
    bids: list[list[float]]  # [[precio, tamano], ...] mejor a peor
    asks: list[list[float]]
    fee_bps: int = 200  # 2% por defecto, tipico en Polymarket


@dataclass
class _SimOrder:
    order_id: str
    token_id: str
    price: Decimal
    size: Decimal
    side: str
    status: str = "LIVE"


class PaperClobClient:
    """
    Reemplazo drop-in de PolymarketClobWrapper para modo paper trading.
    `fill_probability` simula que no toda orden limite se llena de inmediato,
    para que la rutina cancel-replace de order_manager.py tenga algo real
    que hacer incluso en modo simulado.
    """

    def __init__(self, fill_probability: float = 0.7):
        self.markets: dict[str, SimulatedMarket] = {}
        self.orders: dict[str, _SimOrder] = {}
        self.fill_probability = fill_probability

    def register_market(self, market: SimulatedMarket) -> None:
        self.markets[market.token_id] = market

    def get_orderbook(self, token_id: TokenId) -> dict:
        market = self.markets.get(str(token_id))
        if market is None:
            return {"bids": [], "asks": []}
        return {"bids": market.bids, "asks": market.asks}

    def get_fee_rate_bps(self, token_id: TokenId) -> int:
        market = self.markets.get(str(token_id))
        return market.fee_bps if market else 200

    def place_limit_order(self, token_id: TokenId, price: Decimal, size: Decimal, side: str) -> dict:
        order_id = str(uuid.uuid4())
        order = _SimOrder(order_id, str(token_id), price, size, side)

        # Simular fill: se llena si el precio cruza el mejor nivel contrario,
        # o probabilisticamente si queda "en cola" al precio limite.
        market = self.markets.get(str(token_id))
        crosses = False
        if market:
            if side == "BUY" and market.asks and price >= Decimal(str(market.asks[0][0])):
                crosses = True
            if side == "SELL" and market.bids and price <= Decimal(str(market.bids[0][0])):
                crosses = True

        if crosses or random.random() < self.fill_probability:
            order.status = "FILLED"

        self.orders[order_id] = order
        return {"orderID": order_id, "status": order.status}

    def cancel_order(self, order_id: str) -> dict:
        order = self.orders.get(order_id)
        if order and order.status == "LIVE":
            order.status = "CANCELLED"
        return {"orderID": order_id, "status": order.status if order else "UNKNOWN"}

    def get_order_status(self, order_id: str) -> dict:
        order = self.orders.get(order_id)
        return {"orderID": order_id, "status": order.status if order else "UNKNOWN"}


def make_paper_wallet_stub(starting_balance: float = 1000.0):
    """
    Stub minimo con la misma superficie que WalletManager.get_usdc_balance(),
    para que main.py pueda arrancar en modo local sin RPC ni PRIVATE_KEY real.
    """

    class _PaperWallet:
        address = "0xPAPER0000000000000000000000000000000000"

        def __init__(self, balance: float):
            self._balance = balance

        def get_usdc_balance(self) -> float:
            return self._balance

    return _PaperWallet(starting_balance)
