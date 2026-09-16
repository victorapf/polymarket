"""
CAPA 3.5 - Deduccion de comisiones nativas antes de autorizar la orden.

Consulta la estructura de fees del mercado y exige que la EV se mantenga
positiva NETA de comisiones, no solo bruta. Este es el ultimo gate antes de
enviar la orden al OrderManager.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from execution.token_id import TokenId


class ClobClientProtocol(Protocol):
    def get_fee_rate_bps(self, token_id: TokenId) -> int: ...


@dataclass
class NetEvResult:
    gross_ev: Decimal
    fee_bps: int
    net_ev: Decimal
    approved: bool


def check_net_ev(clob: ClobClientProtocol, token_id: TokenId, gross_ev: Decimal, stake: Decimal) -> NetEvResult:
    fee_bps = clob.get_fee_rate_bps(token_id)
    fee_cost_pct = Decimal(fee_bps) / Decimal(10_000)
    net_ev = gross_ev - fee_cost_pct
    return NetEvResult(
        gross_ev=gross_ev,
        fee_bps=fee_bps,
        net_ev=net_ev,
        approved=net_ev > 0,
    )
