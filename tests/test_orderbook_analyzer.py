from decimal import Decimal

from execution.orderbook_analyzer import OrderbookAnalyzer


def make_analyzer():
    return OrderbookAnalyzer(max_slippage_pct=Decimal("0.015"), max_spread_pct=Decimal("0.02"))


def test_approves_clean_fill():
    ob = {
        "bids": [[0.495, 100]],
        "asks": [[0.50, 200], [0.501, 200], [0.502, 200]],
    }
    result = make_analyzer().evaluate_buy(ob, Decimal("100"))
    assert result.approved
    assert result.reason == "ok"


def test_rejects_excessive_spread():
    ob = {
        "bids": [[0.40, 100]],
        "asks": [[0.50, 200]],
    }
    result = make_analyzer().evaluate_buy(ob, Decimal("50"))
    assert not result.approved
    assert result.reason == "spread_excesivo"


def test_rejects_insufficient_liquidity():
    ob = {
        "bids": [[0.49, 100]],
        "asks": [[0.50, 10], [0.505, 10], [0.51, 10]],
    }
    result = make_analyzer().evaluate_buy(ob, Decimal("1000"))
    assert not result.approved
    assert result.reason in ("liquidez_insuficiente_fragmentar", "slippage_excesivo", "spread_excesivo")


def test_rejects_no_asks():
    ob = {"bids": [[0.49, 100]], "asks": []}
    result = make_analyzer().evaluate_buy(ob, Decimal("10"))
    assert not result.approved
    assert result.reason == "sin_liquidez_asks"
