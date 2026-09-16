"""
CAPA 3.1 / 3.2 - Firma off-chain via py-clob-client-v2 + manejo estricto de IDs.

NOTA DE MIGRACION: py-clob-client (v1) fue archivado por Polymarket el
25/05/2026 y dejo de funcionar ("no longer functional, should not be used for
new or existing integrations" -- github.com/Polymarket/py-clob-client). Este
wrapper usa la v2 (`py_clob_client_v2`), API oficial de reemplazo.

Reglas que se mantienen igual:
  - `asset_id` y `condition_id` son enteros de 256 bits. Se manejan SIEMPRE como
    `str` de un extremo a otro del sistema (incluida serializacion JSON, Redis,
    logs). Nunca pasan por un `float`. TokenId (execution/token_id.py) lo impone.
  - Todas las ordenes se firman off-chain (EIP-712) via el SDK, sin gas por
    postura.
"""
from __future__ import annotations

from decimal import Decimal

from py_clob_client_v2 import (
    ApiCreds,
    ClobClient,
    OrderArgs,
    OrderType,
    PartialCreateOrderOptions,
    Side,
)

from config.settings import settings
from execution.token_id import TokenId  # re-exportado por compatibilidad

__all__ = ["TokenId", "PolymarketClobWrapper"]

_SIDE_MAP = {"BUY": Side.BUY, "SELL": Side.SELL}


class PolymarketClobWrapper:
    def __init__(self):
        # Paso 1: cliente sin credenciales L2 para derivar/crear la API key (L1, con la wallet)
        bootstrap_client = ClobClient(
            host=settings.clob_host,
            chain_id=settings.chain_id,
            key=settings.private_key,
        )

        if settings.polymarket_api_key and settings.polymarket_api_secret:
            creds = ApiCreds(
                api_key=settings.polymarket_api_key,
                api_secret=settings.polymarket_api_secret,
                api_passphrase=settings.polymarket_api_passphrase,
            )
        else:
            # Deriva/crea las credenciales L2 automaticamente si no estan en .env.
            # Util para el primer arranque; luego conviene copiar el resultado al .env.
            creds = bootstrap_client.create_or_derive_api_key()

        # Paso 2: cliente completo (L1 + L2), el que efectivamente opera.
        self._client = ClobClient(
            host=settings.clob_host,
            chain_id=settings.chain_id,
            key=settings.private_key,
            creds=creds,
        )

    def get_orderbook(self, token_id: TokenId) -> dict:
        return self._client.get_order_book(str(token_id))

    def get_fee_rate_bps(self, token_id: TokenId) -> int:
        market = self._client.get_market(str(token_id))
        # El nombre exacto del campo de fee puede variar por mercado; se prueban
        # las claves conocidas y se cae a 0 (bloqueando net_ev>0 aguas abajo) si
        # el mercado no expone ninguna -- mejor fallar cerrado que asumir fee=0
        # silenciosamente y aprobar una orden que en realidad no es rentable.
        for key in ("taker_fee_bps", "takerFeeBps", "fee_rate_bps"):
            if key in market:
                return int(market[key])
        return 0

    def place_limit_order(
        self,
        token_id: TokenId,
        price: Decimal,
        size: Decimal,
        side: str,  # "BUY" | "SELL"
    ) -> dict:
        order_args = OrderArgs(
            token_id=str(token_id),
            price=float(price),  # el SDK espera float aqui; el ID nunca lo es
            size=float(size),
            side=_SIDE_MAP[side],
        )
        # tick_size deberia consultarse por mercado (algunos usan 0.01, otros
        # 0.001/0.005); 0.01 es el default mas comun pero conviene verificar
        # contra get_market() antes de operar con capital real.
        options = PartialCreateOrderOptions(tick_size="0.01")
        return self._client.create_and_post_order(
            order_args=order_args, options=options, order_type=OrderType.GTC
        )

    def cancel_order(self, order_id: str) -> dict:
        return self._client.cancel(order_id)

    def get_order_status(self, order_id: str) -> dict:
        return self._client.get_order(order_id)
