"""
CAPA 3.2 - Tipo TokenId, separado de clob_client_wrapper.py a proposito.

asset_id/condition_id de Polymarket son enteros de 256 bits; se manejan
SIEMPRE como str para no corromperlos al castear a float. Vive en su propio
modulo (sin importar py-clob-client) para que el modo paper-trading pueda
usarlo sin necesitar el SDK real instalado.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TokenId:
    value: str

    def __post_init__(self):
        if not isinstance(self.value, str):
            raise TypeError(f"TokenId debe ser str, recibido {type(self.value)}")
        if not self.value.isdigit():
            raise ValueError(f"TokenId invalido (no numerico): {self.value}")

    def __str__(self) -> str:
        return self.value
