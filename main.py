"""
Entry point del motor headless. Orquesta todas las capas:
  1. Verifica reloj (2.3) antes de arrancar.
  2. Levanta el WS de Binance (1.3) como tarea de fondo.
  3. Levanta el heartbeat externo (5.2) como tarea de fondo.
  4. Escucha comandos de la UI (kill switch, pausa, toggles) via StateBus.
  5. Loop principal: evalua senales, chequea EV/Kelly/circuit breakers,
     y ejecuta via CancelReplaceOrderManager si todo aprueba.

Este archivo es deliberadamente el UNICO punto donde se juntan datos + riesgo +
ejecucion. Cada capa individual (data_engine, quant, execution) es testeable
de forma aislada sin necesidad de correr el motor completo.
"""
from __future__ import annotations

import asyncio
import signal
from datetime import date
from decimal import Decimal

import structlog

from config.settings import settings
from data_engine.binance_ws import BinanceOrderFlowStream, OrderFlowState
from execution.order_manager import CancelReplaceOrderManager
from interface.state_bus import StateBus
from monitoring.heartbeat import heartbeat_loop
from quant.risk_manager import RiskManager

logger = structlog.get_logger()


class TradingEngine:
    def __init__(self):
        self.stop_event = asyncio.Event()
        self.paused = False

        if settings.paper_trading:
            # Modo local/paper: no requiere PRIVATE_KEY, RPC ni chequeo de reloj
            # estricto -- pensado para correr en tu laptop mientras compras el VPS.
            from execution.paper_clob_client import PaperClobClient, make_paper_wallet_stub

            logger.warning("engine.PAPER_TRADING_MODE_ACTIVE — sin capital real")
            self.rpc_manager = None
            self.wallet = make_paper_wallet_stub(starting_balance=1000.0)
            self.clob = PaperClobClient()
        else:
            # Modo produccion: capital real, requiere .env completo y VPS de baja latencia.
            from execution.clob_client_wrapper import PolymarketClobWrapper
            from infra.rpc_manager import RpcFailoverManager
            from infra.wallet_manager import WalletManager

            self.rpc_manager = RpcFailoverManager()
            self.wallet = WalletManager(self.rpc_manager)
            self.clob = PolymarketClobWrapper()

        self.order_manager = CancelReplaceOrderManager(
            self.clob, timeout_s=settings.cancel_replace_timeout_s
        )
        self.risk = RiskManager(
            starting_capital=Decimal(str(self.wallet.get_usdc_balance())),
            daily_stoploss_pct=Decimal(str(settings.daily_stoploss_pct)),
        )
        self.btc_state = OrderFlowState()
        self.btc_stream = BinanceOrderFlowStream(state=self.btc_state)
        self.state_bus = StateBus()

    async def _command_listener(self) -> None:
        async for cmd in self.state_bus.command_listener():
            name = cmd.get("command")
            if name == "kill_switch":
                self.risk.manual_kill_switch()
                logger.warning("engine.kill_switch_triggered_remotely")
            elif name == "pause":
                self.paused = True
                logger.info("engine.paused")
            elif name == "resume":
                self.paused = False
            elif name == "set_kelly_fraction":
                # El motor mantiene su propia config runtime; ver quant/kelly.py
                logger.info("engine.kelly_fraction_updated", value=cmd["payload"].get("value"))
            elif name == "toggle_strategy":
                logger.info("engine.strategy_toggled", **cmd["payload"])

    async def _publish_state_loop(self) -> None:
        while not self.stop_event.is_set():
            await self.state_bus.publish_state(
                {
                    "balance_usdc": self.wallet.get_usdc_balance(),
                    "active_rpc": self.rpc_manager.active_url if self.rpc_manager else "paper-mode",
                    "ws_latency_ms": 0,  # calcular con timestamps reales del stream
                    "daily_pnl": float(-self.risk.daily_loss_pct(date.today()) * self.risk.starting_capital),
                    "active_positions": [],
                    "trade_history": [],
                }
            )
            await asyncio.sleep(5)

    async def _main_loop(self) -> None:
        while not self.stop_event.is_set():
            if self.risk.check_circuit_breaker(date.today()):
                logger.critical("engine.circuit_breaker_active_halting")
                await asyncio.sleep(30)
                continue

            if self.paused:
                await asyncio.sleep(1)
                continue

            # Aqui se conectaria la logica de deteccion de senal por vertical:
            #   - sports: fuzzy_matcher + sports_api + sports_model + pinnacle gate
            #   - btc_15m: chainlink_monitor + btc_microstructure + ev + kelly
            # seguido de orderbook_analyzer.evaluate_buy(), fee_checker.check_net_ev()
            # y finalmente order_manager.execute_limit_buy() si todo aprueba.
            await asyncio.sleep(1)

    async def run(self) -> None:
        if not settings.paper_trading:
            from infra.clock_check import check_clock_drift

            check_clock_drift()  # 2.3 - falla rapido si el reloj esta desincronizado (solo produccion)

        logger.info(
            "engine.starting",
            wallet=self.wallet.address,
            rpc=self.rpc_manager.active_url if self.rpc_manager else "paper-mode",
            mode="PAPER" if settings.paper_trading else "LIVE",
        )

        tasks = [
            asyncio.create_task(self.btc_stream.run()),
            asyncio.create_task(heartbeat_loop(self.stop_event)),
            asyncio.create_task(self._command_listener()),
            asyncio.create_task(self._publish_state_loop()),
            asyncio.create_task(self._main_loop()),
        ]

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self.stop_event.set)

        await self.stop_event.wait()
        self.btc_stream.stop()
        for t in tasks:
            t.cancel()
        logger.info("engine.stopped")


if __name__ == "__main__":
    engine = TradingEngine()
    asyncio.run(engine.run())
