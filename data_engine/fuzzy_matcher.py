"""
CAPA 1.1 - Discrepancia de nombres entre Polymarket y bases de datos deportivas.

Estrategia de dos pasos:
  1. Intentar resolver por un mapa estatico de player_id (ATP/WTA/UFC) cuando ya
     se conoce el evento (mas rapido y sin falsos positivos).
  2. Si no hay mapeo directo, usar rapidfuzz para extraer el mejor candidato del
     roster de la fuente deportiva, con umbral minimo de 85%.
"""
from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz, process

MIN_MATCH_SCORE = 85.0


@dataclass
class AthleteMatch:
    polymarket_label: str
    resolved_name: str
    player_id: str | None
    score: float
    method: str  # "static_map" | "fuzzy"


class AthleteResolver:
    def __init__(self, static_id_map: dict[str, str] | None = None):
        # static_id_map: { "nombre_normalizado": "player_id" }
        self._static_map = static_id_map or {}

    def _normalize(self, text: str) -> str:
        return " ".join(text.lower().replace(".", "").split())

    def resolve(self, polymarket_text: str, roster: dict[str, str]) -> AthleteMatch | None:
        """
        polymarket_text: texto crudo del evento, ej "Will Alcaraz C. win his match?"
        roster: { "nombre_completo_oficial": "player_id" } de la fuente de stats
        """
        normalized = self._normalize(polymarket_text)

        # Paso 1: mapeo estatico directo (alias conocidos curados manualmente)
        for alias, pid in self._static_map.items():
            if alias in normalized:
                official_name = next((n for n, i in roster.items() if i == pid), alias)
                return AthleteMatch(polymarket_text, official_name, pid, 100.0, "static_map")

        # Paso 2: fuzzy matching contra el roster completo
        choices = list(roster.keys())
        best = process.extractOne(
            normalized, choices, scorer=fuzz.token_set_ratio
        )
        if best is None:
            return None
        name, score, _ = best
        if score < MIN_MATCH_SCORE:
            return None
        return AthleteMatch(polymarket_text, name, roster[name], float(score), "fuzzy")

    def resolve_or_raise(self, polymarket_text: str, roster: dict[str, str]) -> AthleteMatch:
        match = self.resolve(polymarket_text, roster)
        if match is None:
            raise ValueError(
                f"No se pudo resolver '{polymarket_text}' con confianza >= {MIN_MATCH_SCORE}%"
            )
        return match
