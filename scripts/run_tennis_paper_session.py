"""
Sesion de paper trading con tope de 24 horas (configurable via
PAPER_SESSION_MAX_HOURS), pensada para validar el pipeline completo de tenis
de forma continua y dejar un dataset de decisiones para reentrenar el modelo.

LIMITACION IMPORTANTE: hoy no existe un modulo que descubra mercados de tenis
activos en Polymarket en tiempo real (eso requeriria integrar la API Gamma de
Polymarket). Esta sesion simula la LLEGADA de nuevos partidos usando el mismo
generador sintetico del backtest, a intervalos regulares, para que puedas
validar de punta a punta: deteccion -> decision -> registro -> reentrenamiento.
Los resultados (`won`) se conocen de inmediato porque son sinteticos -- en un
despliegue real, `won` quedaria en null hasta que el partido termine, y se
completaria despues con `DecisionLogger.update_outcome()`.

Correr con: python scripts/run_tennis_paper_session.py
Detener antes de las 24h con Ctrl+C -- el log parcial queda guardado igual.
"""
from __future__ import annotations

import asyncio
import signal
from decimal import Decimal

import numpy as np
import structlog

from backtest.synthetic_tennis_data import generate_synthetic_tennis_dataset
from config.settings import settings
from data_engine.decision_logger import DecisionLogger, DecisionRecord, make_decision_id, now_iso
from execution.fee_checker import check_net_ev
from execution.order_manager import CancelReplaceOrderManager
from execution.orderbook_analyzer import OrderbookAnalyzer
from execution.paper_clob_client import PaperClobClient, SimulatedMarket
from execution.token_id import TokenId
from quant.ev import compute_ev
from quant.kelly import position_size
from quant.risk_manager import RiskManager
from quant.sports_features import TENNIS_FEATURES
from quant.sports_model import SportsModel, pinnacle_line_move_gate

logger = structlog.get_logger()


class TennisPaperSession:
    def __init__(self, max_hours: float | None = None, interval_minutes: float | None = None):
        self.max_seconds = (max_hours if max_hours is not None else settings.paper_session_max_hours) * 3600
        self.interval_seconds = (
            interval_minutes if interval_minutes is not None else settings.paper_session_interval_minutes
        ) * 60
        self.stop_event = asyncio.Event()
        self.decision_log = DecisionLogger()

        # Modelo inicial: entrenado una vez al arrancar con un dataset sintetico
        # de "calentamiento". Se reentrena periodicamente con lo acumulado en
        # el log (ver _maybe_retrain).
        self.training_df = generate_synthetic_tennis_dataset(n_matches=600, seed=1)
        self.model = SportsModel(sport="tennis", feature_columns=TENNIS_FEATURES)
        self.model.train(self.training_df, target_col="won")

        self.bankroll = Decimal("1000")
        self.risk = RiskManager(starting_capital=self.bankroll, daily_stoploss_pct=Decimal(str(settings.daily_stoploss_pct)))
        self.paper_client = PaperClobClient(fill_probability=0.85)
        self.orderbook_analyzer = OrderbookAnalyzer(
            max_slippage_pct=Decimal(str(settings.max_slippage_pct)),
            max_spread_pct=Decimal(str(settings.max_spread_pct)),
        )
        self.order_manager = CancelReplaceOrderManager(self.paper_client, timeout_s=settings.cancel_replace_timeout_s)

        self._match_counter = 0
        self._rng = np.random.default_rng(7)

    def _simulate_incoming_match(self) -> dict:
        """
        Genera UN partido sintetico "nuevo". Sustituir esta funcion es el unico
        cambio necesario para conectar un feed real de mercados de tenis de
        Polymarket + stats reales (Sportradar) cuando ese modulo exista.
        """
        row = generate_synthetic_tennis_dataset(n_matches=1, seed=int(self._rng.integers(0, 1_000_000))).iloc[0]
        self._match_counter += 1
        return row.to_dict()

    async def _evaluate_one_match(self) -> None:
        row = self._simulate_incoming_match()
        features = {col: row[col] for col in TENNIS_FEATURES}
        model_probability = Decimal(str(self.model.predict_probability(features)))
        market_price = Decimal(str(row["market_price"]))
        event_label = f"synthetic_match_{self._match_counter}"

        # Filtro Pinnacle (mock: sin movimiento en esta simulacion)
        if not pinnacle_line_move_gate(float(market_price), float(market_price)):
            logger.info("session.pinnacle_gate_paused", event=event_label)
            return

        gross_ev = compute_ev(model_probability, market_price)

        token_id = TokenId(str(10_000_000_000 + self._match_counter))
        self.paper_client.register_market(
            SimulatedMarket(
                token_id=str(token_id),
                bids=[[float(market_price) - 0.01, 300]],
                asks=[[float(market_price), 300], [float(market_price) + 0.01, 300]],
                fee_bps=200,
            )
        )
        net_ev_result = check_net_ev(self.paper_client, token_id, gross_ev, Decimal("0"))

        record_kwargs = dict(
            decision_id=make_decision_id(),
            timestamp=now_iso(),
            sport="tennis",
            event_label=event_label,
            features={k: float(v) for k, v in features.items()},
            model_probability=float(model_probability),
            market_price=float(market_price),
            gross_ev=float(gross_ev),
            net_ev=float(net_ev_result.net_ev),
            kelly_stake=0.0,
            executed=False,
            rejection_reason=None,
            won=None,
        )

        if not net_ev_result.approved:
            record_kwargs["rejection_reason"] = "ev_neto_no_positivo"
            self.decision_log.log_decision(DecisionRecord(**record_kwargs))
            return

        stake = position_size(self.bankroll, model_probability, market_price, Decimal(str(settings.kelly_fraction)))
        record_kwargs["kelly_stake"] = float(stake)
        if stake <= 0:
            record_kwargs["rejection_reason"] = "kelly_stake_cero"
            self.decision_log.log_decision(DecisionRecord(**record_kwargs))
            return

        orderbook = self.paper_client.get_orderbook(token_id)
        liquidity = self.orderbook_analyzer.evaluate_buy(orderbook, stake)
        if not liquidity.approved:
            record_kwargs["rejection_reason"] = f"liquidez:{liquidity.reason}"
            self.decision_log.log_decision(DecisionRecord(**record_kwargs))
            return

        exec_result = await self.order_manager.execute_limit_buy(token_id, stake, starting_price=market_price)
        record_kwargs["executed"] = exec_result.filled

        # En esta simulacion el resultado se conoce de inmediato (dataset
        # sintetico). En produccion, `won` quedaria None hasta que el partido
        # termine y se completaria via decision_log.update_outcome().
        won = bool(row["won"]) if exec_result.filled else None
        record_kwargs["won"] = won

        if exec_result.filled and won is not None:
            payout = (Decimal(1) / market_price) - Decimal(1)
            pnl = stake * payout if won else -stake
            self.bankroll += pnl
            from datetime import date
            self.risk.record_realized_pnl(pnl, date.today())
            logger.info(
                "session.trade_executed",
                match=event_label,
                won=won,
                pnl=float(pnl),
                bankroll=float(self.bankroll),
            )

        self.decision_log.log_decision(DecisionRecord(**record_kwargs))

    def _maybe_retrain(self) -> None:
        """Reentrena el modelo si ya hay suficientes decisiones resueltas acumuladas."""
        resolved = self.decision_log.resolved_for_training()
        if len(resolved) < 100 or len(resolved) % 50 != 0:
            return
        import pandas as pd

        df = pd.DataFrame(
            [{**r["features"], "market_price": r["market_price"], "won": r["won"]} for r in resolved]
        )
        metrics = self.model.train(df, target_col="won")
        logger.info("session.model_retrained", n_samples=len(df), accuracy=metrics["mean_accuracy"])

    async def run(self) -> None:
        from datetime import date

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self.stop_event.set)
            except NotImplementedError:
                pass  # Windows no soporta add_signal_handler; Ctrl+C sigue funcionando via KeyboardInterrupt

        elapsed = 0.0
        logger.info(
            "session.started",
            max_hours=self.max_seconds / 3600,
            interval_minutes=self.interval_seconds / 60,
            mode="PAPER",
        )

        while not self.stop_event.is_set() and elapsed < self.max_seconds:
            if self.risk.check_circuit_breaker(date.today()):
                logger.critical("session.circuit_breaker_active_halting_session")
                break

            await self._evaluate_one_match()
            self._maybe_retrain()

            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                pass  # transcurrio el intervalo normal, seguir al proximo partido
            elapsed += self.interval_seconds

        logger.info(
            "session.finished",
            elapsed_hours=round(elapsed / 3600, 2),
            final_bankroll=float(self.bankroll),
            decisions_logged=len(self.decision_log.load_all()),
        )


async def main() -> None:
    session = TennisPaperSession()
    try:
        await session.run()
    except KeyboardInterrupt:
        logger.info("session.stopped_by_user")


if __name__ == "__main__":
    asyncio.run(main())
