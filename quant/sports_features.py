"""
Definicion de columnas de features por deporte. Se separa de sports_model.py
a proposito: este modulo no importa lightgbm/sklearn, por lo que puede usarse
desde cualquier parte del sistema (fuzzy matching, backtesting, dashboard)
sin arrastrar una dependencia pesada solo para leer una constante.
"""
from __future__ import annotations

TENNIS_FEATURES = [
    "elo_surface_weighted",
    "pct_points_won_1st_serve",
    "pct_points_won_2nd_serve",
    "h2h_win_pct",
    "break_points_converted_pct",
    "ranking_diff",
    "surface_win_pct_last_12m",
]

# Features para predecir quien gana el SET en curso. Calculadas solo con
# informacion disponible ANTES de que el set se cierre (sets previos + stats
# de los sets anteriores + games del set actual) -- sin look-ahead.
TENNIS_SET_FEATURES = [
    "sets_home_prev",
    "sets_away_prev",
    "games_home_cur",
    "games_away_cur",
    "first_serve_pct_diff_prev_sets",
    "first_serve_pts_won_pct_diff_prev_sets",
    "breaks_converted_diff_prev_sets",
]

COMBAT_FEATURES = [
    "reach_diff_cm",
    "stance_orthodox_vs_southpaw",
    "significant_strikes_per_min",
    "takedown_accuracy_pct",
    "takedown_defense_pct",
    "age_diff",
    "win_streak",
]

TRACK_FEATURES = [
    "personal_best_seconds",
    "season_best_seconds",
    "wind_speed_ms",
    "reaction_time_ms",
    "lane_assignment",
]
