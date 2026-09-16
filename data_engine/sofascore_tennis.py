"""
CAPA 1.2 - Cliente de SofaScore para datos REALES de tenis en vivo.

Usa la API publica (api.sofascore.com) sin login: /sport/tennis/events/live
para partidos en curso (score por set) y /event/{id}/statistics para stats
por periodo (1er/2do saque, breaks, aces). Sirve para entrenar y predecir la
pregunta por SET: quien gana el set en curso.

Sin look-ahead: las features de un set se calculan SOLO con (a) resultado de
los sets anteriores y (b) stats de los sets anteriores. El label (won) de un
set se obtiene observando la transicion a su set siguiente, no desde el mismo
snapshot.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from dataclasses import dataclass, field
from typing import Any

from curl_cffi import requests as cffi_requests

SOFASCORE_BASE = "https://api.sofascore.com/api/v1"

PERIOD_KEY_TO_LABEL = {1: "1ST", 2: "2ND", 3: "3RD", 4: "4TH", 5: "5TH"}


@dataclass
class LiveTennisMatch:
    event_id: int
    home: str
    away: str
    sets_home: int  # sets ganados en total
    sets_away: int
    games_per_set_home: list[int]  # games de cada set jugado (index 0 = set 1)
    games_per_set_away: list[int]
    current_set: int  # 1-based, set en curso
    status_description: str


@dataclass
class SetRow:
    """Una observacion 'a mitad de set' con su label opcional (None = pendiente)."""
    event_id: int
    set_number: int
    home: str
    away: str
    sets_home_prev: int = 0
    sets_away_prev: int = 0
    games_home_cur: int = 0
    games_away_cur: int = 0
    first_serve_pct_diff_prev_sets: float = 0.0
    first_serve_pts_won_pct_diff_prev_sets: float = 0.0
    breaks_converted_diff_prev_sets: float = 0.0
    won: bool | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _set_games(score: dict, set_index: int) -> int:
    return int(score.get(f"period{set_index}", 0) or 0)


def parse_live_events(payload: dict) -> list[LiveTennisMatch]:
    matches = []
    for e in payload.get("events", []):
        hs = e.get("homeScore") or {}
        as_ = e.get("awayScore") or {}
        home = (e.get("homeTeam") or {}).get("name") or "?"
        away = (e.get("awayTeam") or {}).get("name") or "?"
        last_period = e.get("lastPeriod") or ""
        current_set = 1
        for i in range(1, 6):
            if last_period.endswith(f"period{i}"):
                current_set = i
                break
        matches.append(
            LiveTennisMatch(
                event_id=int(e["id"]),
                home=home,
                away=away,
                sets_home=int(hs.get("current", 0) or 0),
                sets_away=int(as_.get("current", 0) or 0),
                games_per_set_home=[_set_games(hs, i) for i in range(1, current_set + 1)],
                games_per_set_away=[_set_games(as_, i) for i in range(1, current_set + 1)],
                current_set=current_set,
                status_description=(e.get("status") or {}).get("description", ""),
            )
        )
    return matches


def _period_blocks(statistics_payload: dict) -> dict[str, dict[str, dict[str, dict[str, float]]]]:
    """Estadisticas por periodo -> {periodo: {groupName: {itemKey: {home, away, homeTotal, awayTotal}}}}"""
    blocks: dict[str, dict[str, dict[str, dict[str, float | int]]]] = {}
    for block in statistics_payload.get("statistics", []):
        period = (block.get("period") or "").upper()
        if not period:
            continue
        groups = {}
        for g in block.get("groups", []):
            items = {}
            for item in g.get("statisticsItems", []):
                items[item.get("key", "")] = {
                    "home": item.get("homeValue", 0),
                    "away": item.get("awayValue", 0),
                    "homeTotal": item.get("homeTotal", 0),
                    "awayTotal": item.get("awayTotal", 0),
                }
            groups[g.get("groupName", "")] = items
        blocks[period] = groups
    return blocks


def _pct_diff(blocks: dict[str, dict], periods: list[str], key: str, group: str = "Service") -> float:
    made_home = sum(blocks[p][group][key]["home"] for p in periods if key in blocks.get(p, {}).get(group, {}))
    made_away = sum(blocks[p][group][key]["away"] for p in periods if key in blocks.get(p, {}).get(group, {}))
    tot_home = sum(blocks[p][group][key]["homeTotal"] for p in periods if key in blocks.get(p, {}).get(group, {}))
    tot_away = sum(blocks[p][group][key]["awayTotal"] for p in periods if key in blocks.get(p, {}).get(group, {}))
    hpct = made_home / tot_home if tot_home else 0.0
    apct = made_away / tot_away if tot_away else 0.0
    return hpct - apct


def set_winner_of(match: LiveTennisMatch, set_index: int) -> bool:
    """True si home gano el set `set_index` (1-based). Solo valido si el set ya termino."""
    if set_index > len(match.games_per_set_home):
        raise ValueError(f"Set {set_index} no terminado para evento {match.event_id}")
    gh = match.games_per_set_home[set_index - 1]
    ga = match.games_per_set_away[set_index - 1]
    return gh > ga


def build_snapshot_row(match: LiveTennisMatch, stats_prev: dict[str, dict], stat_blocks: dict) -> SetRow:
    """Features del set EN CURSO de `match`, calculadas solo con sets anteriores."""
    n = match.current_set
    sets_home_prev = sum(1 for i in range(1, n) if set_winner_of(match, i))
    sets_away_prev = (n - 1) - sets_home_prev
    prev_periods = [PERIOD_KEY_TO_LABEL[i] for i in range(1, n) if PERIOD_KEY_TO_LABEL[i] in stat_blocks]

    gh = match.games_per_set_home[n - 1]
    ga = match.games_per_set_away[n - 1]
    return SetRow(
        event_id=match.event_id,
        set_number=n,
        home=match.home,
        away=match.away,
        sets_home_prev=sets_home_prev,
        sets_away_prev=sets_away_prev,
        games_home_cur=gh,
        games_away_cur=ga,
        first_serve_pct_diff_prev_sets=_pct_diff(stat_blocks, prev_periods, "firstServeAccuracy"),
        first_serve_pts_won_pct_diff_prev_sets=_pct_diff(stat_blocks, prev_periods, "firstServePointsAccuracy"),
        breaks_converted_diff_prev_sets=_pct_diff(stat_blocks, prev_periods, "breakPointsScored", group="Return"),
    )


class SofaScoreClient:
    """Minimo: live events + estadisticas por evento, con curl_cffi para fingerprint de Chrome."""

    def __init__(self):
        self._impersonate = "chrome136"

    def _get_json(self, url: str) -> dict:
        resp = cffi_requests.get(url, impersonate=self._impersonate, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def fetch_live_events(self) -> list[LiveTennisMatch]:
        payload = self._get_json(f"{SOFASCORE_BASE}/sport/tennis/events/live")
        return parse_live_events(payload)

    def fetch_event_statistics(self, event_id: int) -> dict:
        try:
            payload = self._get_json(f"{SOFASCORE_BASE}/event/{event_id}/statistics")
            return _period_blocks(payload)
        except cffi_requests.exceptions.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return {}
            raise

    def close(self) -> None:
        pass