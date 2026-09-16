"""
CAPA 4.2 - Modelos predictivos para deportes (Tenis / Combate / Atletismo).

Usa XGBoost/LightGBM con TimeSeriesSplit (nunca k-fold aleatorio: fuga temporal
invalidaria el backtest). Incluye el filtro de noticias via movimiento abrupto
de Pinnacle como safety gate independiente del modelo.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit

# Definicion de features por deporte: vive en sports_features.py (sin deps pesadas)
# y se re-exporta aqui por compatibilidad con el resto del codigo.
from quant.sports_features import COMBAT_FEATURES, TENNIS_FEATURES, TRACK_FEATURES

__all__ = ["TENNIS_FEATURES", "COMBAT_FEATURES", "TRACK_FEATURES", "SportsModel", "pinnacle_line_move_gate"]


@dataclass
class SportsModel:
    sport: str
    feature_columns: list[str]
    model: lgb.LGBMClassifier | None = field(default=None, repr=False)

    def train(self, df: pd.DataFrame, target_col: str = "won", n_splits: int = 5) -> dict:
        """
        df debe estar ordenado cronologicamente. Se usa TimeSeriesSplit para que
        cada fold entrene solo con datos anteriores a los que valida, evitando
        look-ahead bias.
        """
        X = df[self.feature_columns]
        y = df[target_col]

        tscv = TimeSeriesSplit(n_splits=n_splits)
        fold_scores = []
        for train_idx, val_idx in tscv.split(X):
            model = lgb.LGBMClassifier(
                n_estimators=300,
                learning_rate=0.03,
                max_depth=5,
                subsample=0.8,
                colsample_bytree=0.8,
            )
            model.fit(X.iloc[train_idx], y.iloc[train_idx])
            score = model.score(X.iloc[val_idx], y.iloc[val_idx])
            fold_scores.append(score)

        # Modelo final entrenado con todo el historico disponible
        self.model = lgb.LGBMClassifier(
            n_estimators=300, learning_rate=0.03, max_depth=5, subsample=0.8, colsample_bytree=0.8
        )
        self.model.fit(X, y)

        return {"fold_accuracy": fold_scores, "mean_accuracy": float(np.mean(fold_scores))}

    def predict_probability(self, features: dict) -> float:
        if self.model is None:
            raise RuntimeError("Modelo no entrenado. Llamar train() primero o cargar uno persistido.")
        row = pd.DataFrame([features])[self.feature_columns]
        return float(self.model.predict_proba(row)[0][1])


def pinnacle_line_move_gate(pre_match_price: float, current_price: float, threshold_pct: float = 0.15) -> bool:
    """
    CAPA 4.2 - Filtro de noticias via Pinnacle.

    Si la cuota de Pinnacle se movio mas de `threshold_pct` de forma abrupta
    (tipicamente indicando una lesion o baja de ultimo momento no capturada
    por el modelo), devuelve False para pausar la senal.
    """
    if pre_match_price <= 0:
        return True
    move_pct = abs(current_price - pre_match_price) / pre_match_price
    return move_pct <= threshold_pct
