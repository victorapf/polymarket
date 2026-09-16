"""
CAPA 4.5 - Circuit Breakers y gestion de fondos no liquidados.

  - Stop-loss diario: si las perdidas acumuladas del dia alcanzan el X% del
    capital inicial, se cancelan ordenes abiertas y se detiene el bot hasta
    intervencion manual (o reset programado al dia siguiente).
  - Retencion por disputas UMA: las ganancias de un mercado no se suman al
    balance operativo "libre" hasta que su estado on-chain sea RESOLVED
    (Polymarket usa UMA Optimistic Oracle; un mercado disputado puede tardar
    dias en resolverse o revertirse).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum


class MarketStatus(str, Enum):
    PENDING = "PENDING"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"


@dataclass
class DailyPnLTracker:
    day: date
    starting_capital: Decimal
    realized_pnl: Decimal = Decimal(0)


@dataclass
class RiskManager:
    starting_capital: Decimal
    daily_stoploss_pct: Decimal = Decimal("0.05")
    _tracker: DailyPnLTracker | None = field(default=None, repr=False)
    _kill_switch_active: bool = False
    _daily_stoploss_halted: bool = False

    def _ensure_today(self, today: date) -> None:
        if self._tracker is None or self._tracker.day != today:
            self._tracker = DailyPnLTracker(day=today, starting_capital=self.starting_capital)
            # El halt por stop-loss diario se auto-resetea al comenzar un nuevo dia.
            # El kill switch manual (Telegram/dashboard) NO se resetea.
            self._daily_stoploss_halted = False

    def record_realized_pnl(self, amount: Decimal, today: date) -> None:
        self._ensure_today(today)
        self._tracker.realized_pnl += amount

    def daily_loss_pct(self, today: date) -> Decimal:
        self._ensure_today(today)
        if self._tracker.starting_capital <= 0:
            return Decimal(0)
        loss = -self._tracker.realized_pnl
        return loss / self._tracker.starting_capital

    def check_circuit_breaker(self, today: date) -> bool:
        """Devuelve True si el circuit breaker debe dispararse (detener el bot)."""
        self._ensure_today(today)  # primero: resetea el halt diario si cambio de dia
        if self._kill_switch_active or self._daily_stoploss_halted:
            return True
        loss_pct = self.daily_loss_pct(today)
        if loss_pct >= self.daily_stoploss_pct:
            self._daily_stoploss_halted = True
            return True
        return False

    def manual_kill_switch(self) -> None:
        """Invocado desde /stop en Telegram o el boton de emergencia del dashboard."""
        self._kill_switch_active = True

    def reset_kill_switch(self) -> None:
        self._kill_switch_active = False

    @staticmethod
    def is_settleable(status: MarketStatus) -> bool:
        """Solo sumar ganancias al capital operativo libre si el mercado esta RESOLVED."""
        return status == MarketStatus.RESOLVED
