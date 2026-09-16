"""
Recopila datos REALES de SofaScore para entrenar el modelo por-SET y evalua su
precision. La etiqueta (won) del set N se obtiene observando el partido pasar
al set N+1: las features guardadas se capturaron a mitad del set N, sin
look-ahead.

Uso:
  python scripts/scrape_tennis_sets.py --collect --minutes 30
  python scripts/scrape_tennis_sets.py --train
"""
from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

import structlog

from data_engine.sofascore_tennis import (
    SofaScoreClient,
    build_snapshot_row,
    set_winner_of,
)
from quant.sports_features import TENNIS_SET_FEATURES

logger = structlog.get_logger()

OUT_CSV = Path("data/tennis_sets_live.csv")
POLL_S = 60

FEATURE_ROWS = [
    "event_id",
    "set_number",
    "home",
    "away",
    "sets_home_prev",
    "sets_away_prev",
    "games_home_cur",
    "games_away_cur",
    "first_serve_pct_diff_prev_sets",
    "first_serve_pts_won_pct_diff_prev_sets",
    "breaks_converted_diff_prev_sets",
    "won",
]


def collect(minutes: float) -> None:
    """Polla live; cuando un set se cierra (transicion al siguiente), lo etiqueta y lo guarda."""
    client = SofaScoreClient()
    # pending[event_id][set_number] = dict (la ultima fila capturada para ese set en curso)
    pending: dict[int, dict[int, dict]] = {}
    # stats_cache[event_id] = (block, ts) reusado entre ticks para no pegolear la API
    stats_cache: dict[int, tuple[dict, float]] = {}
    deadline = time.time() + minutes * 60
    n_labeled = 0
    STATS_TTL_S = 180  # stats casi no cambian durante un set; basta refrescar cada 3 min

    try:
        while time.time() < deadline:
            try:
                matches = client.fetch_live_events()
            except Exception as exc:
                logger.warning("sofascore.poll_error", exc=str(exc))
                time.sleep(30 if "403" in str(exc) else POLL_S)
                continue

            seen = set()

            for m in matches:
                seen.add(m.event_id)
                if m.current_set < 1:
                    continue
                now = time.time()
                cached = stats_cache.get(m.event_id)
                if cached and now - cached[1] < STATS_TTL_S:
                    blocks = cached[0]
                else:
                    blocks = client.fetch_event_statistics(m.event_id)
                    stats_cache[m.event_id] = (blocks, now)

                # Cerrar sets anteriores: al ver el set actual, todos los sets anteriores estan resueltos
                prev = pending.setdefault(m.event_id, {})
                for s in range(1, m.current_set):
                    if s in prev and prev[s].get("won") is None:
                        prev[s]["won"] = bool(set_winner_of(m, s))
                        n_labeled += 1
                        _append_row(prev.pop(s))

                # Snapshot del set en curso (features a mitad de set)
                row = build_snapshot_row(m, None, blocks).__dict__
                row.pop("extra", None)
                pending[m.event_id][m.current_set] = row

            # Eventos que desaparecieron sin transicion visible: no se pueden etiquetar (ponytail:
            # se pierde la ultima set de esos partidos; las transiciones alcanzan para armar dataset)
            for eid in list(pending):
                if eid not in seen:
                    pending.pop(eid, None)

            logger.info("sofascore.collect_tick", live=len(matches), labeled_total=n_labeled,
                        pending=sum(len(v) for v in pending.values()))
            time.sleep(POLL_S)
    finally:
        client.close()
    logger.info("sofascore.collect_done", labeled_total=n_labeled, out=OUT_CSV)


def _append_row(row: dict) -> None:
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    write_header = not OUT_CSV.exists() or OUT_CSV.stat().st_size == 0
    with OUT_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FEATURE_ROWS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def train() -> None:
    import pandas as pd
    from quant.sports_model import SportsModel

    if not OUT_CSV.exists():
        raise SystemExit(f"No hay datos en {OUT_CSV}. Correr primero --collect.")
    df = pd.read_csv(OUT_CSV)
    df = df.dropna(subset=["won"]).reset_index(drop=True)
    print(f"Filas etiquetadas: {len(df)}  (wins home: {int(df['won'].sum())}/{len(df)})")
    if len(df) < 20:
        print("Demasiadas pocas filas para entrenar con sentido.")
        return

    model = SportsModel(sport="tennis", feature_columns=TENNIS_SET_FEATURES)
    metrics = model.train(df, target_col="won")
    acc = metrics["mean_accuracy"]
    majority = max(float(df["won"].mean()), 1 - float(df["won"].mean()))
    print(f"Accuracy TimeSeriesSplit: {acc:.3f}")
    print(f"Baseline (predecir siempre lo mas comun): {majority:.3f}")
    print(f"Ventaja sobre baseline: {acc - majority:+.3f}")

    for set_n in sorted(df["set_number"].unique()):
        sub = df[df["set_number"] == set_n]
        if len(sub) < 5:
            continue
        subacc = model.model.score(sub[TENNIS_SET_FEATURES], sub["won"])
        base = max(float(sub["won"].mean()), 1 - float(sub["won"].mean()))
        print(f"  set {int(set_n)}: n={len(sub)} acc={subacc:.3f} baseline={base:.3f}")

    model.model.booster_.save_model("models/tennis_set_model.txt")
    print("Guardado en models/tennis_set_model.txt")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--collect", action="store_true")
    parser.add_argument("--minutes", type=float, default=30.0)
    parser.add_argument("--train", action="store_true")
    args = parser.parse_args()

    if args.collect:
        collect(minutes=args.minutes)
    elif args.train:
        train()
    else:
        parser.print_help()