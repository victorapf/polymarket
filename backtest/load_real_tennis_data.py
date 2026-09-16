"""
Carga datos REALES de tenis para entrenar el modelo, desde el dataset publico
y gratuito de Jeff Sackmann (github.com/JeffSackmann/tennis_atp y
tennis_wta). Es el dataset que usa la mayor parte de la comunidad de
analitica de tenis -- resultados desde 1968, estadisticas de partido
(servicio, break points) desde 1991 para el circuito principal ATP.

Licencia: Creative Commons Attribution-NonCommercial-ShareAlike 4.0.
Atribucion requerida si publicas resultados derivados de estos datos.

Esto SI responde "como entreno con datos reales": este loader arma un
DataFrame con exactamente las columnas de TENNIS_FEATURES a partir de datos
historicos reales, listo para pasarle a SportsModel.train() o a
backtest/engine.py. Lo que este loader NO resuelve es el precio de mercado de
Polymarket para esos partidos historicos (Sackmann no tiene eso) -- por eso
approximate_market_price() genera un proxy razonable a partir del ranking
para poder correr el backtest completo; para un backtest fiel de EV real hace
falta cruzar esto con historial de precios real de Polymarket (CLOB timeseries
API), que es un modulo aparte.

Requiere conexion a internet real (no funciona en este sandbox de Claude).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from quant.sports_features import TENNIS_FEATURES

RAW_CSV_BASE = "https://raw.githubusercontent.com/JeffSackmann/tennis_{tour}/master/{tour}_matches_{year}.csv"

K_FACTOR = 32  # constante estandar de Elo


@dataclass
class LoadedTennisDataset:
    df: pd.DataFrame
    n_matches: int
    years: list[int]
    tour: str


def _download_year(tour: str, year: int) -> pd.DataFrame:
    url = RAW_CSV_BASE.format(tour=tour, year=year)
    return pd.read_csv(url, low_memory=False)


def load_raw_matches(years: list[int], tour: str = "atp") -> pd.DataFrame:
    """
    tour: "atp" o "wta". Descarga y concatena un CSV por año directo desde
    GitHub (requiere internet real). Cada fila es un partido con columnas
    winner_*, loser_*, surface, tourney_date, y estadisticas w_*/l_* (servicio,
    break points) para partidos de nivel tour desde 1991.
    """
    frames = []
    for year in years:
        try:
            frames.append(_download_year(tour, year))
        except Exception as exc:
            print(f"Aviso: no se pudo descargar {tour} {year}: {exc}")
    if not frames:
        raise RuntimeError("No se pudo descargar ningun año. Revisar conexion a internet.")
    df = pd.concat(frames, ignore_index=True)
    df["tourney_date"] = pd.to_datetime(df["tourney_date"], format="%Y%m%d", errors="coerce")
    df = df.sort_values("tourney_date").reset_index(drop=True)
    return df


def _compute_elo_by_surface(raw: pd.DataFrame) -> pd.DataFrame:
    """
    Elo incremental ponderado por superficie, calculado cronologicamente
    (nunca mirando hacia adelante -- el Elo de un partido usa solo partidos
    anteriores). Empieza en 1500 para cada jugador/superficie nuevo.
    """
    elo: dict[tuple[str, str], float] = {}
    winner_elo_pre = np.zeros(len(raw))
    loser_elo_pre = np.zeros(len(raw))

    for i, row in enumerate(raw.itertuples()):
        surface = getattr(row, "surface", "Hard") or "Hard"
        w_key = (row.winner_name, surface)
        l_key = (row.loser_name, surface)
        w_elo = elo.get(w_key, 1500.0)
        l_elo = elo.get(l_key, 1500.0)

        winner_elo_pre[i] = w_elo
        loser_elo_pre[i] = l_elo

        expected_w = 1 / (1 + 10 ** ((l_elo - w_elo) / 400))
        elo[w_key] = w_elo + K_FACTOR * (1 - expected_w)
        elo[l_key] = l_elo + K_FACTOR * (0 - (1 - expected_w))

    raw = raw.copy()
    raw["winner_elo_pre"] = winner_elo_pre
    raw["loser_elo_pre"] = loser_elo_pre
    return raw


def _compute_h2h(raw: pd.DataFrame) -> np.ndarray:
    """H2H historico del 'winner' contra el 'loser' ANTES de este partido (0.5 si es el primer cruce)."""
    history: dict[tuple[str, str], list[int]] = {}
    h2h = np.zeros(len(raw))
    for i, row in enumerate(raw.itertuples()):
        pair = tuple(sorted([row.winner_name, row.loser_name]))
        record = history.setdefault(pair, [])
        wins_for_winner = sum(1 for w in record if w == row.winner_name)
        h2h[i] = wins_for_winner / len(record) if record else 0.5
        record.append(row.winner_name)
    return h2h


def build_tennis_features_from_real_matches(raw: pd.DataFrame) -> pd.DataFrame:
    """
    Transforma el CSV crudo de Sackmann en el esquema TENNIS_FEATURES + won +
    market_price (proxy). Cada partido real aporta DOS filas de entrenamiento
    (perspectiva del ganador con won=1, perspectiva del perdedor con won=0)
    para no sesgar el dataset -- si solo tomaramos la fila "winner vs loser"
    el modelo aprenderia trivialmente a decir que el primero gana siempre.
    """
    required_cols = {
        "winner_name", "loser_name", "winner_rank", "loser_rank", "surface",
        "tourney_date", "w_1stIn", "w_1stWon", "w_2ndWon", "w_svpt",
        "l_1stIn", "l_1stWon", "l_2ndWon", "l_svpt",
        "w_bpSaved", "w_bpFaced", "l_bpSaved", "l_bpFaced",
    }
    missing = required_cols - set(raw.columns)
    if missing:
        raise ValueError(
            f"Faltan columnas esperadas del formato Sackmann: {missing}. "
            "Los años sin MatchStats (pre-1991) no tienen estas columnas."
        )

    raw = raw.dropna(subset=list(required_cols)).reset_index(drop=True)
    raw = _compute_elo_by_surface(raw)
    raw["h2h_winner_pre"] = _compute_h2h(raw)

    def pct(made, attempted):
        attempted = attempted.replace(0, np.nan)
        return (made / attempted * 100).fillna(0)

    w_serve1_pct = pct(raw["w_1stWon"], raw["w_1stIn"])
    l_serve1_pct = pct(raw["l_1stWon"], raw["l_1stIn"])
    w_serve2_pct = pct(raw["w_2ndWon"], raw["w_svpt"] - raw["w_1stIn"])
    l_serve2_pct = pct(raw["l_2ndWon"], raw["l_svpt"] - raw["l_1stIn"])
    w_bp_pct = pct(raw["w_bpFaced"] - raw["w_bpSaved"], raw["l_bpFaced"].replace(0, np.nan))
    l_bp_pct = pct(raw["l_bpFaced"] - raw["l_bpSaved"], raw["w_bpFaced"].replace(0, np.nan))

    rows = []
    for i in range(len(raw)):
        # Perspectiva "winner" (won=1)
        rows.append(
            {
                "elo_surface_weighted": raw["winner_elo_pre"].iat[i] - raw["loser_elo_pre"].iat[i],
                "pct_points_won_1st_serve": w_serve1_pct.iat[i] - l_serve1_pct.iat[i],
                "pct_points_won_2nd_serve": w_serve2_pct.iat[i] - l_serve2_pct.iat[i],
                "h2h_win_pct": raw["h2h_winner_pre"].iat[i],
                "break_points_converted_pct": w_bp_pct.iat[i] - l_bp_pct.iat[i],
                "ranking_diff": (raw["loser_rank"].iat[i] or 999) - (raw["winner_rank"].iat[i] or 999),
                "surface_win_pct_last_12m": 0.0,  # requiere ventana rolling adicional, placeholder
                "won": 1,
            }
        )
        # Perspectiva "loser" (won=0), features espejadas
        rows.append(
            {
                "elo_surface_weighted": raw["loser_elo_pre"].iat[i] - raw["winner_elo_pre"].iat[i],
                "pct_points_won_1st_serve": l_serve1_pct.iat[i] - w_serve1_pct.iat[i],
                "pct_points_won_2nd_serve": l_serve2_pct.iat[i] - w_serve2_pct.iat[i],
                "h2h_win_pct": 1 - raw["h2h_winner_pre"].iat[i],
                "break_points_converted_pct": l_bp_pct.iat[i] - w_bp_pct.iat[i],
                "ranking_diff": (raw["winner_rank"].iat[i] or 999) - (raw["loser_rank"].iat[i] or 999),
                "surface_win_pct_last_12m": 0.0,
                "won": 0,
            }
        )

    df = pd.DataFrame(rows)
    df["market_price"] = approximate_market_price(df["ranking_diff"])
    return df[TENNIS_FEATURES + ["market_price", "won"]]


def approximate_market_price(ranking_diff: pd.Series) -> pd.Series:
    """
    Proxy de precio de mercado a partir del ranking, SOLO para poder correr
    backtest/engine.py con datos historicos reales cuando no se tiene el
    historial real de precios de Polymarket para esos partidos. No es una
    fuente de EV confiable -- reemplazar por precios historicos reales del
    CLOB timeseries API en cuanto esten disponibles.
    """
    logit = ranking_diff.clip(-200, 200) / 100
    return (1 / (1 + np.exp(-logit))).clip(0.03, 0.97)


def load_real_tennis_dataset(years: list[int], tour: str = "atp") -> LoadedTennisDataset:
    raw = load_raw_matches(years, tour=tour)
    df = build_tennis_features_from_real_matches(raw)
    return LoadedTennisDataset(df=df, n_matches=len(df) // 2, years=years, tour=tour)


if __name__ == "__main__":
    # Ejemplo: los ultimos 2 años completos disponibles del ATP tour
    dataset = load_real_tennis_dataset(years=[2023, 2024], tour="atp")
    print(f"Cargados {dataset.n_matches} partidos reales ({dataset.tour}, {dataset.years})")
    print(dataset.df.describe())
    dataset.df.to_csv("backtest/data/tennis_real_atp_2023_2024.csv", index=False)
    print("Guardado en backtest/data/tennis_real_atp_2023_2024.csv")
