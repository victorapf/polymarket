"""
CAPA 2.5 - Custodia y clave privada.

Reglas de diseno:
  - La PRIVATE_KEY se lee UNICAMENTE desde variables de entorno / Secrets Manager,
    nunca hardcodeada ni logueada. `settings.private_key` es la unica fuente.
  - Este proceso (el motor de trading) NUNCA tiene la clave privada de la cold
    storage -- solo su direccion publica como destino de barrido. Es decir, el
    bot puede enviar fondos a cold storage pero no puede moverlos de vuelta.
  - `auto_sweep` se pensa como un script/cron INDEPENDIENTE del motor de trading
    (proceso separado, ver infra/sweep_daemon.py en produccion), para que un
    fallo o compromiso del motor no controle cuando se hace el barrido.
"""
from __future__ import annotations

import structlog
from eth_account import Account
from web3 import Web3

from config.settings import settings
from infra.rpc_manager import RpcFailoverManager

logger = structlog.get_logger()

USDC_POLYGON_ADDRESS = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"  # USDC nativo en Polygon
_ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [{"name": "_to", "type": "address"}, {"name": "_value", "type": "uint256"}],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
]


class WalletManager:
    def __init__(self, rpc_manager: RpcFailoverManager):
        if not settings.private_key:
            raise ValueError("PRIVATE_KEY no configurada (usar .env o Secrets Manager)")
        self._rpc = rpc_manager
        self._account = Account.from_key(settings.private_key)

    @property
    def address(self) -> str:
        return self._account.address

    def _usdc_contract(self):
        w3 = self._rpc.get_web3()
        return w3.eth.contract(address=Web3.to_checksum_address(USDC_POLYGON_ADDRESS), abi=_ERC20_ABI)

    def get_usdc_balance(self) -> float:
        contract = self._usdc_contract()
        decimals = contract.functions.decimals().call()
        raw = contract.functions.balanceOf(self._account.address).call()
        return raw / (10 ** decimals)

    def auto_sweep(self, threshold: float | None = None, keep: float | None = None) -> str | None:
        """
        Si el balance operativo supera `threshold`, transfiere el excedente por
        encima de `keep` hacia COLD_STORAGE_ADDRESS. Devuelve el tx hash o None
        si no hubo barrido. Disenado para ejecutarse periodicamente (cron/APScheduler)
        en un proceso separado del motor de trading.
        """
        threshold = threshold if threshold is not None else settings.sweep_threshold_usdc
        keep = keep if keep is not None else settings.sweep_keep_usdc
        if not settings.cold_storage_address:
            logger.warning("auto_sweep.no_cold_storage_configured")
            return None

        balance = self.get_usdc_balance()
        if balance <= threshold:
            return None

        amount_to_sweep = balance - keep
        contract = self._usdc_contract()
        decimals = contract.functions.decimals().call()
        raw_amount = int(amount_to_sweep * (10 ** decimals))

        w3 = self._rpc.get_web3()
        tx = contract.functions.transfer(
            Web3.to_checksum_address(settings.cold_storage_address), raw_amount
        ).build_transaction(
            {
                "from": self._account.address,
                "nonce": w3.eth.get_transaction_count(self._account.address),
                "gas": 100_000,
                "maxFeePerGas": w3.eth.gas_price * 2,
                "maxPriorityFeePerGas": w3.to_wei(30, "gwei"),
                "chainId": settings.chain_id,
            }
        )
        signed = self._account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        logger.info("auto_sweep.executed", amount=amount_to_sweep, tx_hash=tx_hash.hex())
        return tx_hash.hex()
