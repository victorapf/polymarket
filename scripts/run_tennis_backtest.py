"""
Corre el backtest del vertical de tenis con datos sinteticos y muestra un
resumen. Reemplaza `generate_synthetic_tennis_dataset()` por un DataFrame con
datos historicos reales (mismas columnas) en cuanto tengas acceso a
Sportradar/Tennis-Data + tu propio historico de precios de Polymarket.

Correr con: python scripts/run_tennis_backtest.py
"""
from __future__ import annotations

from decimal import Decimal

from backtest.engine import run_tennis_backtest
from backtest.synthetic_tennis_data import generate_synthetic_tennis_dataset


def main() -> None:
    df = generate_synthetic_tennis_dataset(n_matches=1500)

    result = run_tennis_backtest(
        df,
        starting_bankroll=Decimal("1000"),
        kelly_multiplier=Decimal("0.25"),
        min_ev_threshold=Decimal("0.03"),
        fee_bps=200,
    )

    print("=== Resultado del backtest (datos sinteticos) ===")
    print(f"Partidos evaluados (out-of-sample): {len(df) - int(len(df) * 0.4)}")
    print(f"Operaciones ejecutadas: {result.n_trades}")
    print(f"Win rate: {result.win_rate:.1f}%")
    print(f"Bankroll inicial: $1000.00")
    print(f"Bankroll final: ${result.final_bankroll:.2f}")
    print(f"Retorno: {(result.final_bankroll / 1000 - 1) * 100:.1f}%")
    print(f"Veces que se disparo el circuit breaker diario: {result.circuit_breaker_triggers}")

    if result.trades:
        print("\nUltimas 5 operaciones:")
        for t in result.trades[-5:]:
            print(
                f"  {t['day']} | EV neto={t['net_ev']:.2%} | stake=${t['stake']:.2f} | "
                f"gano={t['won']} | pnl=${t['pnl']:.2f} | bankroll=${t['bankroll']:.2f}"
            )

    print(
        "\nRecordatorio: esto corre sobre datos SINTETICOS con un edge inyectado a "
        "proposito para validar el pipeline. No es evidencia de que la estrategia "
        "funcione con datos reales de tenis -- eso requiere reemplazar el dataset "
        "por historico real y volver a correr."
    )


if __name__ == "__main__":
    main()
