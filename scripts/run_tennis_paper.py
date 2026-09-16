"""
Demo end-to-end del vertical de tenis, corrible 100% en local:

  fuzzy_matcher (resolver nombre de Polymarket) -> sports_model (probabilidad)
  -> pinnacle_line_move_gate (filtro de noticias) -> ev (EV bruto y neto)
  -> kelly (tamano de posicion) -> orderbook_analyzer (liquidez/slippage)
  -> paper_clob_client (ejecucion simulada, cancel-replace real)

No requiere PRIVATE_KEY, RPC, ni claves de Sportradar/Pinnacle -- todo esta
mockeado con datos de ejemplo para que puedas ver el pipeline completo
decidiendo en tiempo real. Cuando tengas datos/API keys reales, solo se
reemplazan las funciones marcadas con "# TODO: reemplazar por fuente real".

Correr con:  python scripts/run_tennis_paper.py
"""
from __future__ import annotations

import asyncio
from decimal import Decimal

from backtest.synthetic_tennis_data import generate_synthetic_tennis_dataset
from data_engine.fuzzy_matcher import AthleteResolver
from execution.token_id import TokenId
from execution.fee_checker import check_net_ev
from execution.order_manager import CancelReplaceOrderManager
from execution.orderbook_analyzer import OrderbookAnalyzer
from execution.paper_clob_client import PaperClobClient, SimulatedMarket
from quant.ev import compute_ev
from quant.kelly import position_size
from quant.risk_manager import RiskManager
from quant.sports_model import TENNIS_FEATURES, SportsModel, pinnacle_line_move_gate
from datetime import date


# TODO: reemplazar por el roster real que devuelva sports_api.SportsDataClient
ROSTER = {
    "carlos alcaraz garfia": "sr:competitor:1234",
    "novak djokovic": "sr:competitor:5678",
}
STATIC_ALIASES = {
    "alcaraz c": "sr:competitor:1234",
    "djokovic n": "sr:competitor:5678",
}


async def main() -> None:
    print("=== Demo local: vertical de tenis, modo paper-trading ===\n")

    # 1) Entrenar un modelo rapido con datos sinteticos (reemplazar por datos
    #    historicos reales de Sportradar/Tennis-Data cuando esten disponibles).
    df = generate_synthetic_tennis_dataset(n_matches=800)
    model = SportsModel(sport="tennis", feature_columns=TENNIS_FEATURES)
    metrics = model.train(df, target_col="won")
    print(f"Modelo entrenado. Accuracy media (TimeSeriesSplit): {metrics['mean_accuracy']:.3f}\n")

    # 2) Resolver el nombre del evento de Polymarket contra el roster (1.1)
    resolver = AthleteResolver(static_id_map=STATIC_ALIASES)
    polymarket_event_text = "Will Alcaraz C. win his match?"
    match = resolver.resolve_or_raise(polymarket_event_text, ROSTER)
    print(f"Nombre resuelto: '{polymarket_event_text}' -> {match.resolved_name} "
          f"(player_id={match.player_id}, score={match.score:.1f}, metodo={match.method})\n")

    # 3) Features del partido (mock -- vendria de sports_api.SportsDataClient en produccion)
    example_features = {
        "elo_surface_weighted": 120.0,
        "pct_points_won_1st_serve": 3.5,
        "pct_points_won_2nd_serve": 1.2,
        "h2h_win_pct": 0.65,
        "break_points_converted_pct": 5.0,
        "ranking_diff": -15.0,
        "surface_win_pct_last_12m": 8.0,
    }
    model_probability = Decimal(str(model.predict_probability(example_features)))
    print(f"Probabilidad del modelo: {model_probability:.2%}")

    # 4) Filtro Pinnacle (mock: precio pre-partido vs actual)
    pinnacle_pre_match = 0.58
    pinnacle_current = 0.60
    if not pinnacle_line_move_gate(pinnacle_pre_match, pinnacle_current):
        print("Senal pausada: movimiento abrupto en Pinnacle (posible lesion).")
        return
    print("Filtro Pinnacle: OK (sin movimiento abrupto)\n")

    # 5) Mercado de Polymarket simulado (paper trading)
    token_id = TokenId("112233445566778899")
    market_price = Decimal("0.55")
    paper_client = PaperClobClient(fill_probability=0.8)
    paper_client.register_market(
        SimulatedMarket(
            token_id=str(token_id),
            bids=[[0.545, 300], [0.540, 300]],
            asks=[[0.550, 300], [0.555, 300], [0.560, 300]],
            fee_bps=200,
        )
    )

    # 6) EV bruto y neto de comisiones
    gross_ev = compute_ev(model_probability, market_price)
    net_ev_result = check_net_ev(_PaperClobAdapter(paper_client), token_id, gross_ev, Decimal("0"))
    print(f"EV bruto: {gross_ev:.2%} | fee: {net_ev_result.fee_bps}bps | EV neto: {net_ev_result.net_ev:.2%}")
    if not net_ev_result.approved:
        print("Operacion rechazada: EV neto no positivo.\n")
        return

    # 7) Tamano de posicion via Kelly fraccionado (1/4 Kelly por defecto)
    bankroll = Decimal("1000")
    stake = position_size(bankroll, model_probability, market_price, kelly_multiplier=Decimal("0.25"))
    print(f"Tamano de posicion (1/4 Kelly, bankroll ${bankroll}): ${stake}\n")

    # 8) Chequeo de liquidez/slippage contra el libro simulado
    analyzer = OrderbookAnalyzer(max_slippage_pct=Decimal("0.015"), max_spread_pct=Decimal("0.02"))
    orderbook = paper_client.get_orderbook(token_id)
    liquidity = analyzer.evaluate_buy(orderbook, stake)
    print(f"Chequeo de liquidez: aprobado={liquidity.approved} "
          f"(slippage={liquidity.slippage_pct:.2%}, spread={liquidity.spread_pct:.2%})")
    if not liquidity.approved:
        print(f"Operacion rechazada por liquidez: {liquidity.reason}\n")
        return

    # 9) Circuit breaker de riesgo diario
    risk = RiskManager(starting_capital=bankroll, daily_stoploss_pct=Decimal("0.05"))
    if risk.check_circuit_breaker(date.today()):
        print("Circuit breaker activo: no se opera.\n")
        return

    # 10) Ejecucion via cancel-replace (simulada)
    order_manager = CancelReplaceOrderManager(_PaperClobAdapter(paper_client), timeout_s=1.5)
    exec_result = await order_manager.execute_limit_buy(token_id, stake, starting_price=Decimal("0.55"))
    print(f"\nResultado de ejecucion: lleno={exec_result.filled}, "
          f"order_id={exec_result.order_id}, precio_final={exec_result.final_price}, "
          f"intentos={exec_result.attempts}")


class _PaperClobAdapter:
    """
    Adaptador minimo para que fee_checker.check_net_ev() y CancelReplaceOrderManager,
    escritos contra PolymarketClobWrapper, funcionen tambien con PaperClobClient
    sin cambiar sus firmas (mismos metodos, distinta implementacion interna).
    """

    def __init__(self, paper_client: PaperClobClient):
        self._c = paper_client

    def get_orderbook(self, token_id):
        return self._c.get_orderbook(token_id)

    def get_fee_rate_bps(self, token_id):
        return self._c.get_fee_rate_bps(token_id)

    def place_limit_order(self, token_id, price, size, side):
        return self._c.place_limit_order(token_id, price, size, side)

    def cancel_order(self, order_id):
        return self._c.cancel_order(order_id)

    def get_order_status(self, order_id):
        return self._c.get_order_status(order_id)


if __name__ == "__main__":
    asyncio.run(main())
