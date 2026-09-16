from datetime import date
from decimal import Decimal

from quant.risk_manager import RiskManager


def test_circuit_breaker_resets_on_new_day():
    r = RiskManager(starting_capital=Decimal("1000"), daily_stoploss_pct=Decimal("0.05"))
    d1 = date(2024, 1, 2)
    d2 = date(2024, 1, 3)
    r.record_realized_pnl(Decimal("-60"), d1)
    assert r.check_circuit_breaker(d1)
    assert not r.check_circuit_breaker(d2)


def test_manual_kill_switch_is_sticky():
    r = RiskManager(starting_capital=Decimal("1000"), daily_stoploss_pct=Decimal("0.05"))
    r.manual_kill_switch()
    assert r.check_circuit_breaker(date(2024, 1, 3))
    assert r.check_circuit_breaker(date(2024, 1, 4))