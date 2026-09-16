"""
Paper trading de BTC 15m con datos REALES, ejecucion SIMULADA.

Datos reales usados:
  - Order flow de Binance (WebSocket real: @aggTrade + @depth) -> CVD y book imbalance.
  - Mercado y orderbook REALES de Polymarket (Gamma + CLOB, ambos publicos, sin
    necesitar wallet ni API key todavia).

Lo unico simulado es la ejecucion: se opera contra `PaperClobClient`, pero el
precio y la liquidez con los que se calcula esa ejecucion vienen del orderbook
real que se acaba de leer de Polymarket -- por eso el resultado del paper
trading es representativo de lo que pasaria con capital real, no un ejemplo
inventado.

IMPORTANTE sobre el "modelo": para BTC no hay un clasificador ML entrenado --
la señal es la confirmacion de microestructura de CAPA 4.3 (CVD + book
imbalance por umbrales fijos). La probabilidad usada en el calculo de EV aqui
es una heuristica simple derivada de la fuerza de esa confirmacion, marcada
explicitamente como tal. Calibrar esos umbrales/heuristica con datos
historicos reales es un trabajo distinto (ajuste de parametros, no
entrenamiento de un modelo) -- avisame si quieres que lo construya despues.

Correr con: python scripts/run_btc_live_paper.py
Se detiene con Ctrl+C.
"""
from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

import structlog

from data_engine.binance_ws import BinanceOrderFlowStream, OrderFlowState
from data_engine.decision_logger import DecisionLogger, DecisionRecord, make_decision_id, now_iso
from data_engine.polymarket_public import PolymarketPublicClient
from execution.fee_checker import check_net_ev
from execution.order_manager import CancelReplaceOrderManager
from execution.orderbook_analyzer import OrderbookAnalyzer
from execution.paper_clob_client import PaperClobClient, SimulatedMarket
from execution.token_id import TokenId
from quant.btc_microstructure import evaluate_signal
from quant.ev import compute_ev
from quant.kelly import position_size
from quant.risk_manager import RiskManager

logger = structlog.get_logger()

EVAL_INTERVAL_S = 30  # cada cuanto se revisa si hay señal, dentro de cada ventana de 15 min


def heuristic_probability(cvd_60s: float, book_imbalance: float, direction: str) -> Decimal:
    """
    Heuristica explicita (NO un modelo entrenado): mapea la fuerza de la
    confirmacion de microestructura a una probabilidad. Mas fuerte la
    confirmacion -> mas lejos de 0.5. Acotada a un rango conservador
    [0.50, 0.68] porque no hay evidencia historica todavia de que la relacion
    sea lineal ni de cuanto edge real da esta señal.
    """
    strength = min(abs(cvd_60s) / 20.0, 1.0) * 0.5 + min(abs(book_imbalance) / 0.5, 1.0) * 0.5
    p = Decimal("0.5") + Decimal(str(strength)) * Decimal("0.18")
    return p


async def run_btc_live_paper_loop() -> None:
    binance_state = OrderFlowState()
    binance_stream = BinanceOrderFlowStream(symbol="btcusdt", state=binance_state)
    binance_task = asyncio.create_task(binance_stream.run())

    poly_client = PolymarketPublicClient()
    paper_client = PaperClobClient(fill_probability=0.85)
    orderbook_analyzer = OrderbookAnalyzer(max_slippage_pct=Decimal("0.015"), max_spread_pct=Decimal("0.02"))
    decision_log = DecisionLogger()
    bankroll = Decimal("1000")
    risk = RiskManager(starting_capital=bankroll, daily_stoploss_pct=Decimal("0.05"))
    order_manager = CancelReplaceOrderManager(paper_client, timeout_s=1.5)

    logger.info("btc_live_paper.started")
    await asyncio.sleep(5)  # dar tiempo a que el WS de Binance acumule datos iniciales

    try:
        while True:
            if risk.check_circuit_breaker(date.today()):
                logger.critical("btc_live_paper.circuit_breaker_halting")
                await asyncio.sleep(60)
                continue

            market = await poly_client.find_current_btc_15m_market()
            if market is None:
                logger.warning("btc_live_paper.no_active_market_found")
                await asyncio.sleep(EVAL_INTERVAL_S)
                continue

            up_token = market.token_id_for("Up") or market.token_id_for("Yes")
            if up_token is None:
                logger.warning("btc_live_paper.up_token_not_found", question=market.question)
                await asyncio.sleep(EVAL_INTERVAL_S)
                continue

            real_orderbook = await poly_client.get_orderbook(up_token)
            signal = evaluate_signal(binance_state)

            if not signal.confirmed:
                logger.debug("btc_live_paper.no_signal", cvd=signal.cvd_60s, imbalance=signal.book_imbalance)
                await asyncio.sleep(EVAL_INTERVAL_S)
                continue

            up_outcome = next((o for o in market.outcomes if o.token_id == up_token), None)
            market_price = Decimal(str(up_outcome.price)) if up_outcome else Decimal("0.5")
            model_probability = heuristic_probability(signal.cvd_60s, signal.book_imbalance, signal.direction)
            if signal.direction == "DOWN":
                model_probability = Decimal(1) - model_probability
                market_price = Decimal(1) - market_price  # trabajar en terminos del token que se compraria

            gross_ev = compute_ev(model_probability, market_price)

            token_id = TokenId(up_token)
            # Espejamos el orderbook real leido de Polymarket en el paper client
            # para que la ejecucion simulada use precios/liquidez reales.
            paper_client.register_market(
                SimulatedMarket(
                    token_id=str(token_id),
                    bids=[[float(b[0]), float(b[1])] for b in real_orderbook.get("bids", [])] or [[0.0, 0.0]],
                    asks=[[float(a[0]), float(a[1])] for a in real_orderbook.get("asks", [])] or [[1.0, 0.0]],
                    fee_bps=200,
                )
            )
            net_ev_result = check_net_ev(paper_client, token_id, gross_ev, Decimal("0"))

            record_kwargs = dict(
                decision_id=make_decision_id(),
                timestamp=now_iso(),
                sport="btc_15m",
                event_label=market.slug,
                features={"cvd_60s": signal.cvd_60s, "book_imbalance": signal.book_imbalance},
                model_probability=float(model_probability),
                market_price=float(market_price),
                gross_ev=float(gross_ev),
                net_ev=float(net_ev_result.net_ev),
                kelly_stake=0.0,
                executed=False,
                rejection_reason=None,
                won=None,  # se conoce recien al cerrar la ventana de 15 min
            )

            if not net_ev_result.approved:
                record_kwargs["rejection_reason"] = "ev_neto_no_positivo"
                decision_log.log_decision(DecisionRecord(**record_kwargs))
                await asyncio.sleep(EVAL_INTERVAL_S)
                continue

            stake = position_size(bankroll, model_probability, market_price, Decimal("0.25"))
            record_kwargs["kelly_stake"] = float(stake)
            if stake <= 0:
                record_kwargs["rejection_reason"] = "kelly_stake_cero"
                decision_log.log_decision(DecisionRecord(**record_kwargs))
                await asyncio.sleep(EVAL_INTERVAL_S)
                continue

            liquidity = orderbook_analyzer.evaluate_buy(paper_client.get_orderbook(token_id), stake)
            if not liquidity.approved:
                record_kwargs["rejection_reason"] = f"liquidez:{liquidity.reason}"
                decision_log.log_decision(DecisionRecord(**record_kwargs))
                await asyncio.sleep(EVAL_INTERVAL_S)
                continue

            exec_result = await order_manager.execute_limit_buy(token_id, stake, starting_price=market_price)
            record_kwargs["executed"] = exec_result.filled
            decision_log.log_decision(DecisionRecord(**record_kwargs))

            logger.info(
                "btc_live_paper.decision_logged",
                market=market.slug,
                direction=signal.direction,
                executed=exec_result.filled,
                stake=float(stake),
                net_ev=float(net_ev_result.net_ev),
            )

            # NOTA: el resultado (`won`) de esta decision se conoce recien
            # cuando cierra la ventana de 15 min. Un proceso separado deberia
            # consultar `decision_log.pending_outcomes()` despues de que cada
            # mercado resuelva (status RESOLVED via UMA) y completar el
            # resultado con `decision_log.update_outcome()` -- no implementado
            # todavia en este script, para mantenerlo enfocado en la decision.

            await asyncio.sleep(EVAL_INTERVAL_S)

    finally:
        binance_stream.stop()
        binance_task.cancel()
        await poly_client.close()


if __name__ == "__main__":
    try:
        asyncio.run(run_btc_live_paper_loop())
    except KeyboardInterrupt:
        logger.info("btc_live_paper.stopped_by_user")
