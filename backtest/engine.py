"""
Motor de backtesting: entrena el modelo con TimeSeriesSplit (sin fuga temporal),
y luego camina cronologicamente sobre los partidos aplicando exactamente la
misma logica de decision que usaria el bot en vivo: EV > 0, tamano via Kelly
fraccionado, respetando el circuit breaker de perdida diaria.

Esto es lo que deberias correr ANTES de conectar capital real o incluso antes
de correr en paper-trading contra Polymarket -- si el backtest no muestra
edge neto de comisiones, no tiene sentido seguir.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd

from quant.ev import compute_ev
from quant.kelly import position_size
from quant.risk_manager import RiskManager
from quant.sports_model import TENNIS_FEATURES, SportsModel


@dataclass
class BacktestResult:
    equity_curve: list[float] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)
    final_bankroll: float = 0.0
    n_trades: int = 0
    win_rate: float = 0.0
    circuit_breaker_triggers: int = 0


def run_tennis_backtest(
    df: pd.DataFrame,
    starting_bankroll: Decimal = Decimal("1000"),
    kelly_multiplier: Decimal = Decimal("0.25"),
    min_ev_threshold: Decimal = Decimal("0.03"),
    fee_bps: int = 200,
    train_fraction: float = 0.4,
) -> BacktestResult:
    """
    df: salida de generate_synthetic_tennis_dataset() o un dataset real con las
        mismas columnas (TENNIS_FEATURES + market_price + won), ordenado
        cronologicamente.
    train_fraction: fraccion inicial del dataset usada solo para entrenar el
        primer modelo (out-of-sample real para el resto del backtest).
    """
    n_train = int(len(df) * train_fraction)
    train_df = df.iloc[:n_train].copy()
    test_df = df.iloc[n_train:].copy()

    model = SportsModel(sport="tennis", feature_columns=TENNIS_FEATURES)
    model.train(train_df, target_col="won")

    bankroll = starting_bankroll
    risk = RiskManager(starting_capital=bankroll, daily_stoploss_pct=Decimal("0.05"))
    result = BacktestResult()
    fee_pct = Decimal(fee_bps) / Decimal(10_000)

    # Simulamos un dia distinto cada N partidos para poder ejercitar el
    # circuit breaker diario de forma realista.
    matches_per_day = 8
    sim_day = date(2024, 1, 1)

    wins = 0
    for i, (_, row) in enumerate(test_df.iterrows()):
        if i % matches_per_day == 0:
            sim_day += timedelta(days=1)

        if risk.check_circuit_breaker(sim_day):
            result.circuit_breaker_triggers += 1
            continue

        features = {col: row[col] for col in TENNIS_FEATURES}
        model_prob = Decimal(str(model.predict_probability(features)))
        market_price = Decimal(str(row["market_price"]))

        gross_ev = compute_ev(model_prob, market_price)
        net_ev = gross_ev - fee_pct
        if net_ev <= min_ev_threshold:
            continue

        stake = position_size(bankroll, model_prob, market_price, kelly_multiplier)
        if stake <= 0:
            continue

        won = bool(row["won"])
        payout = (Decimal(1) / market_price) - Decimal(1)  # cuota neta
        pnl = (stake * payout * (Decimal(1) - fee_pct)) if won else -stake

        bankroll += pnl
        risk.record_realized_pnl(pnl, sim_day)
        wins += 1 if won else 0

        result.trades.append(
            {
                "day": sim_day.isoformat(),
                "model_prob": float(model_prob),
                "market_price": float(market_price),
                "net_ev": float(net_ev),
                "stake": float(stake),
                "won": won,
                "pnl": float(pnl),
                "bankroll": float(bankroll),
            }
        )
        result.equity_curve.append(float(bankroll))

    result.final_bankroll = float(bankroll)
    result.n_trades = len(result.trades)
    result.win_rate = (wins / result.n_trades * 100) if result.n_trades else 0.0
    return result
