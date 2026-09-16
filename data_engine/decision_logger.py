"""
Registro de decisiones de paper trading, persistido a disco como JSONL.

Cada linea es una decision completa (features usadas, probabilidad del modelo,
precio de mercado, EV, tamano de Kelly, si se ejecuto, y el resultado si ya se
conoce). Este archivo es la materia prima para reentrenar el modelo despues de
una sesion de paper trading: `won` puede ser `null` mientras el partido no
haya terminado, y se completa despues via `update_outcome`.

Deliberadamente en disco local (no Redis) para que sobreviva a reinicios del
bot y a que borres el contenedor de Redis por error -- es tu dataset de
entrenamiento, no estado efimero.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_LOG_PATH = Path("data/paper_trading_log.jsonl")


@dataclass
class DecisionRecord:
    decision_id: str
    timestamp: str
    sport: str
    event_label: str
    features: dict[str, float]
    model_probability: float
    market_price: float
    gross_ev: float
    net_ev: float
    kelly_stake: float
    executed: bool
    rejection_reason: str | None = None
    won: bool | None = None  # se completa despues via update_outcome()


class DecisionLogger:
    def __init__(self, path: Path | str = DEFAULT_LOG_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log_decision(self, record: DecisionRecord) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record)) + "\n")

    def load_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def update_outcome(self, decision_id: str, won: bool) -> bool:
        """
        Reescribe el archivo completo actualizando el resultado de una decision.
        Suficientemente rapido para el volumen de una sesion de 24h (decenas a
        cientos de registros, no millones); si el dataset crece mucho, migrar
        a sqlite es la evolucion natural.
        """
        records = self.load_all()
        found = False
        for r in records:
            if r["decision_id"] == decision_id:
                r["won"] = won
                found = True
                break
        if found:
            with self.path.open("w", encoding="utf-8") as f:
                for r in records:
                    f.write(json.dumps(r) + "\n")
        return found

    def pending_outcomes(self) -> list[dict[str, Any]]:
        """Decisiones ejecutadas cuyo resultado (won) todavia no se conoce."""
        return [r for r in self.load_all() if r["executed"] and r["won"] is None]

    def resolved_for_training(self) -> list[dict[str, Any]]:
        """Decisiones ejecutadas con resultado conocido -- listas para reentrenar."""
        return [r for r in self.load_all() if r["executed"] and r["won"] is not None]


def make_decision_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
