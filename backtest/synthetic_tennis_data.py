"""
Genera un dataset sintetico de tenis para backtesting. NO son datos reales --
sirven para probar que el pipeline (features -> modelo -> EV -> Kelly ->
bankroll) funciona de punta a punta antes de conectar una fuente real
(Sportradar / Tennis-Data API).

El dataset se genera con una relacion real (no ruido puro) entre las features
y el resultado, para que el modelo tenga algo que aprender y el backtest no
sea trivialmente plano.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from quant.sports_features import TENNIS_FEATURES


def generate_synthetic_tennis_dataset(n_matches: int = 1500, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    elo_diff = rng.normal(0, 150, n_matches)  # diferencia de Elo ponderado por superficie
    serve1_diff = rng.normal(0, 5, n_matches)  # diferencia % puntos ganados 1er servicio
    serve2_diff = rng.normal(0, 4, n_matches)
    h2h = rng.uniform(0, 1, n_matches)
    bp_diff = rng.normal(0, 8, n_matches)
    ranking_diff = rng.normal(0, 30, n_matches)
    surface_wr_diff = rng.normal(0, 10, n_matches)

    # Probabilidad "verdadera" generada por una combinacion logistica de las
    # features -- esto es lo que el modelo debe aproximar.
    logit = (
        0.008 * elo_diff
        + 0.05 * serve1_diff
        + 0.03 * serve2_diff
        + 1.2 * (h2h - 0.5)
        + 0.02 * bp_diff
        - 0.01 * ranking_diff
        + 0.02 * surface_wr_diff
    )
    true_prob = 1 / (1 + np.exp(-logit))
    won = rng.binomial(1, true_prob)

    # Precio de mercado (token de Polymarket) = probabilidad "de mercado", que
    # tiene ruido/sesgo propio respecto a la probabilidad verdadera -- asi se
    # generan oportunidades de EV positivo y negativo, como en la realidad.
    market_noise = rng.normal(0, 0.06, n_matches)
    market_price = np.clip(true_prob + market_noise, 0.03, 0.97)

    df = pd.DataFrame(
        {
            "elo_surface_weighted": elo_diff,
            "pct_points_won_1st_serve": serve1_diff,
            "pct_points_won_2nd_serve": serve2_diff,
            "h2h_win_pct": h2h,
            "break_points_converted_pct": bp_diff,
            "ranking_diff": ranking_diff,
            "surface_win_pct_last_12m": surface_wr_diff,
            "market_price": market_price,
            "won": won,
        }
    )
    assert list(TENNIS_FEATURES) == [c for c in TENNIS_FEATURES], "features desalineadas"
    return df


if __name__ == "__main__":
    df = generate_synthetic_tennis_dataset()
    df.to_csv("backtest/data/tennis_sample.csv", index=False)
    print(f"Generado backtest/data/tennis_sample.csv con {len(df)} partidos sinteticos")
