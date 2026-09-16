"""
CAPA 2.2 - Failover automatico de nodos RPC en Polygon.

Mantiene una lista priorizada de proveedores (Alchemy, Infura, QuickNode, etc).
Si el nodo principal no responde dentro de un timeout corto, conmuta al
siguiente de la lista. Expone un solo objeto Web3 "vivo" al resto del sistema.
"""
from __future__ import annotations

import time

from web3 import HTTPProvider, Web3

from config.settings import settings

_HEALTHCHECK_TIMEOUT_S = 0.1  # <100ms segun spec


class RpcFailoverManager:
    def __init__(self, rpc_urls: list[str] | None = None):
        self._urls = rpc_urls or settings.rpc_url_list
        if not self._urls:
            raise ValueError("No hay RPC_URLS configuradas")
        self._active_idx = 0
        self._w3 = self._connect(self._active_idx)

    def _connect(self, idx: int) -> Web3:
        return Web3(HTTPProvider(self._urls[idx], request_kwargs={"timeout": 5}))

    def _healthy(self, w3: Web3) -> bool:
        try:
            start = time.monotonic()
            w3.eth.block_number
            return (time.monotonic() - start) < _HEALTHCHECK_TIMEOUT_S * 10  # margen realista
        except Exception:
            return False

    def get_web3(self) -> Web3:
        """Devuelve un Web3 sano, conmutando automaticamente si el actual fallo."""
        if self._healthy(self._w3):
            return self._w3

        for offset in range(1, len(self._urls)):
            candidate_idx = (self._active_idx + offset) % len(self._urls)
            candidate = self._connect(candidate_idx)
            if self._healthy(candidate):
                self._active_idx = candidate_idx
                self._w3 = candidate
                return self._w3

        raise ConnectionError("Todos los RPCs configurados estan caidos")

    @property
    def active_url(self) -> str:
        return self._urls[self._active_idx]
