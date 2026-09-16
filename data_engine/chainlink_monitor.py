"""
CAPA 1.4 - Desfase de Oraculo (Chainlink vs Spot).

Polymarket referencia el feed on-chain de Chainlink para resolver mercados
UP/DOWN de BTC. Ese feed actualiza por umbral de desviacion o por heartbeat
temporal, no en cada tick -- lo que genera una ventana donde el precio Spot
(Binance) ya se movio pero la cuota del token todavia no. Este modulo calcula
esa divergencia para decidir si hay ventaja de ejecutar antes del reajuste.
"""
from __future__ import annotations

from dataclasses import dataclass

from web3 import Web3

# ABI minimo de un AggregatorV3Interface de Chainlink
_AGGREGATOR_ABI = [
    {
        "inputs": [],
        "name": "latestRoundData",
        "outputs": [
            {"name": "roundId", "type": "uint80"},
            {"name": "answer", "type": "int256"},
            {"name": "startedAt", "type": "uint256"},
            {"name": "updatedAt", "type": "uint256"},
            {"name": "answeredInRound", "type": "uint80"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
]


@dataclass
class OracleDivergence:
    oracle_price: float
    spot_price: float
    divergence_pct: float
    oracle_updated_at: int
    seconds_since_update: float


class ChainlinkMonitor:
    def __init__(self, w3: Web3, feed_address: str):
        self._contract = w3.eth.contract(
            address=Web3.to_checksum_address(feed_address), abi=_AGGREGATOR_ABI
        )
        self._decimals: int | None = None

    def _get_decimals(self) -> int:
        if self._decimals is None:
            self._decimals = self._contract.functions.decimals().call()
        return self._decimals

    def read_oracle_price(self) -> tuple[float, int]:
        _, answer, _, updated_at, _ = self._contract.functions.latestRoundData().call()
        price = answer / (10 ** self._get_decimals())
        return price, updated_at

    def compute_divergence(self, spot_price: float, now_ts: float) -> OracleDivergence:
        oracle_price, updated_at = self.read_oracle_price()
        divergence_pct = (spot_price - oracle_price) / oracle_price if oracle_price else 0.0
        return OracleDivergence(
            oracle_price=oracle_price,
            spot_price=spot_price,
            divergence_pct=divergence_pct,
            oracle_updated_at=updated_at,
            seconds_since_update=now_ts - updated_at,
        )
