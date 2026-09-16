"""
Descubre partidos de tenis REALMENTE activos en Polymarket ahora mismo (via
Gamma API, publica, sin credenciales) y muestra su precio real.

Esto prueba que la conexion a datos reales de mercado funciona. Lo que NO
resuelve: las features del modelo (Elo, % de servicio, H2H, etc.) para esos
partidos en vivo -- eso requiere un feed de estadisticas (Sportradar/
Tennis-Data, de pago) o carga manual. Ver scripts/load_real_tennis_history.py
para el entrenamiento con datos historicos reales, que si es gratuito.

Correr con: python scripts/discover_tennis_markets.py
"""
from __future__ import annotations

import asyncio

from data_engine.polymarket_public import PolymarketPublicClient


async def main() -> None:
    client = PolymarketPublicClient()
    try:
        events = await client.find_active_tennis_events(limit=20)
        if not events:
            print("No se encontraron eventos de tenis activos ahora mismo (o el tag 'tennis' "
                  "no coincidio -- revisar GET /tags si esto persiste).")
            return

        print(f"=== {len(events)} evento(s) de tenis activo(s) en Polymarket ===\n")
        for ev in events:
            print(f"Evento: {ev['event_title']}  (slug: {ev['event_slug']})")
            for market in ev["markets"]:
                print(f"  Mercado: {market.question}")
                for outcome in market.outcomes:
                    print(f"    - {outcome.label}: precio={outcome.price:.3f}  token_id={outcome.token_id}")
            print()
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
