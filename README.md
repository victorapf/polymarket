# Polymarket Prediction/Trading Bot — Arquitectura

Bot headless de trading algorítmico para Polymarket (Polygon), con dos verticales:

1. **Deportes de baja variabilidad** — Tenis individual, atletismo de pista, deportes de combate.
2. **BTC de alta frecuencia** — mercados recurrentes UP/DOWN de 15 minutos.

## Principio de diseño

- **Motor (engine)**: 100% headless, Python asyncio, sin dependencias de UI. Puede correr en un
  contenedor Docker sin cabeza en un VPS.
- **Interfaz**: Dashboard Streamlit (solo lectura + controles) y bot de Telegram, ambos hablan con
  el motor a través de una capa de estado compartida (Redis pub/sub + una tabla de estado), nunca
  importan lógica de trading directamente. Esto permite reiniciar/actualizar la UI sin tocar el
  motor, y viceversa.

## Estructura de carpetas

```
polymarket_bot/
├── main.py                     # Entry point del motor headless
├── config/
│   └── settings.py             # Config centralizada vía variables de entorno (pydantic-settings)
├── data_engine/                # CAPA 1 — Ingesta y normalización
│   ├── fuzzy_matcher.py        # 1.1 Matching de nombres de atletas
│   ├── sports_api.py           # 1.2 Cliente de APIs deportivas + caché Redis
│   ├── binance_ws.py           # 1.3 WebSocket asíncrono de order flow BTC
│   ├── chainlink_monitor.py    # 1.4 Divergencia oráculo Chainlink vs spot
│   └── cache.py                # Wrapper Redis
├── infra/                      # CAPA 2 — Infraestructura y seguridad
│   ├── rpc_manager.py          # 2.2 Failover automático de RPCs Polygon
│   ├── clock_check.py          # 2.3 Verificación de deriva de reloj
│   └── wallet_manager.py       # 2.5 Custodia hot wallet + auto-sweep a cold storage
├── execution/                  # CAPA 3 — Ejecución y microestructura
│   ├── clob_client_wrapper.py  # 3.1/3.2 Wrapper sobre py-clob-client, IDs como string/int
│   ├── orderbook_analyzer.py   # 3.4 Profundidad de libro, slippage, spread
│   ├── order_manager.py        # 3.3 Rutina cancel-replace con órdenes límite
│   └── fee_checker.py          # 3.5 Deducción de comisiones antes de autorizar EV
├── quant/                      # CAPA 4 — Lógica cuantitativa y riesgo
│   ├── ev.py                   # 4.1 Cálculo de Esperanza Matemática
│   ├── kelly.py                # 4.4 Kelly fraccionado
│   ├── sports_model.py         # 4.2 Features + wrapper XGBoost/LightGBM
│   ├── btc_microstructure.py   # 4.3 CVD y book imbalance
│   └── risk_manager.py         # 4.5 Circuit breakers, stop-loss diario, estado UMA
├── monitoring/
│   └── heartbeat.py            # 5.2 Heartbeat externo (Better Uptime style)
├── interface/
│   ├── state_bus.py            # Canal Redis pub/sub compartido motor <-> UI
│   ├── dashboard.py             # 5.3 Streamlit dashboard
│   └── telegram_bot.py         # 5.4 Bot de control remoto
├── backtest/                   # Validacion pre-produccion
│   ├── synthetic_tennis_data.py  # Dataset sintetico para probar el pipeline sin red
│   └── engine.py                 # Camina el historico aplicando EV/Kelly/riesgo real
├── scripts/                     # Entry points runnables en local
│   ├── run_tennis_backtest.py         # python scripts/run_tennis_backtest.py
│   ├── run_tennis_paper.py            # python scripts/run_tennis_paper.py (paper-trading E2E)
│   └── run_tennis_paper_session.py    # Sesion continua con tope de 24h + log de decisiones
└── tests/
    ├── test_kelly.py
    ├── test_ev.py
    └── test_orderbook_analyzer.py
```

## Modo paper vs modo producción — qué cambia

| Componente | Paper (`PAPER_TRADING=true`) | Producción (`PAPER_TRADING=false`) |
|---|---|---|
| Cliente CLOB | `execution/paper_clob_client.py` (en memoria) | `execution/clob_client_wrapper.py` (py-clob-client real) |
| Wallet | Stub con balance ficticio | `infra/wallet_manager.py` (clave real) |
| RPC Polygon | No se usa | `infra/rpc_manager.py` con failover |
| Chequeo de reloj (2.3) | Se salta | Obligatorio antes de arrancar |
| Requiere VPS | No | Sí, para BTC 15m (tenis es más tolerante) |

## Nota deliberadamente omitida

El punto 2.4 del spec original (enrutar tráfico para evadir geo-bloqueos de Polymarket) **no está
implementado**. Polymarket restringe geográficamente el acceso a ciertas jurisdicciones (incluido
EE.UU.) por motivos regulatorios (acuerdo con la CFTC). Construir infraestructura para eludir esa
restricción no es algo que vaya a implementar. Si operas desde una jurisdicción permitida, esto no
te afecta; si no, la solución correcta es verificar tu elegibilidad, no enmascarar tu ubicación.

## Modo local (antes de comprar el VPS) — recomendado para empezar

No necesitas AWS ni un VPS para probar el pipeline completo. `PAPER_TRADING=true`
(default en `.env.example`) hace que el motor use un cliente CLOB simulado en
memoria en vez de `py-clob-client`: no requiere `PRIVATE_KEY` real, no gasta
gas, y no toca Polymarket. La verificación de deriva de reloj (2.3) también se
salta en este modo, porque no hay firma EIP-712 real que pueda rechazarse.

```bash
pip install -r requirements.txt --break-system-packages   # o dentro de un venv
cp .env.example .env                                       # dejar PAPER_TRADING=true

# 1) Backtest con datos sinteticos de tenis (sin red, sin API keys)
python scripts/run_tennis_backtest.py

# 2) Demo end-to-end de una decision de trading en tenis, en paper-trading
python scripts/run_tennis_paper.py

# 3) Motor completo en modo paper (requiere Redis local, ej. `docker run -p 6379:6379 redis:7-alpine`)
python main.py
streamlit run interface/dashboard.py   # en otra terminal
python interface/telegram_bot.py       # opcional, en otra terminal
```

Por qué tenis primero: es el vertical menos sensible a latencia (los mercados
no se resuelven cada 15 minutos como BTC), así que un desfase de unos cientos
de ms en tu laptop no invalida la estrategia. BTC de alta frecuencia sí
necesita el VPS en `us-east-1` (2.1) antes de operar en serio.

**Antes de pasar a capital real**, reemplaza el dataset sintético de
`backtest/synthetic_tennis_data.py` por historial real (Sportradar/Tennis-Data
+ tu propio histórico de precios de Polymarket) y vuelve a correr el backtest.
Si no muestra edge neto de comisiones con datos reales, no tiene sentido
conectar `PAPER_TRADING=false`.

## Datos reales (Polymarket + Sportradar/Sackmann)

**Descubrimiento de mercados real** (`data_engine/polymarket_public.py`): usa
las APIs públicas de Polymarket (Gamma para descubrir mercados, CLOB para
precio/orderbook) — ninguna de las dos necesita wallet ni API key.

```bash
python scripts/discover_tennis_markets.py     # partidos de tenis activos ahora mismo, con precio real
python scripts/run_btc_live_paper.py          # BTC 15m: order flow real de Binance + mercado/orderbook real de
                                                # Polymarket + ejecución simulada, todo registrado en el log de decisiones
```

**Entrenamiento con datos históricos reales de tenis** (`backtest/load_real_tennis_data.py`):
usa el dataset público y gratuito de Jeff Sackmann (resultados ATP/WTA desde
1968, estadísticas de partido desde 1991). Requiere internet real (no corre
en el sandbox de desarrollo).

```bash
python backtest/load_real_tennis_data.py   # descarga 2023-2024, arma el dataset con TENNIS_FEATURES reales
```

**Lo que queda pendiente, sin maquillar:**
- Para **tenis**, calcular las features (Elo, % de servicio, H2H) de un partido que está por jugarse *ahora* necesita datos en vivo — el dataset de Sackmann es histórico, no en tiempo real. Eso requiere un feed pago (Sportradar/Tennis-Data) o carga manual de esas cifras antes de cada partido.
- Para **BTC**, la probabilidad usada en `scripts/run_btc_live_paper.py` es una heurística explícita basada en la fuerza de la confirmación de microestructura, no un modelo entrenado — no existe un dataset histórico de CVD/book-imbalance + resultado todavía para calibrarla con evidencia real.
- El precio de mercado histórico de Polymarket (para backtestear tenis con EV real, no un proxy) requiere integrar el timeseries API del CLOB — no está construido.


```bash
python scripts/run_tennis_paper_session.py
```

Corre hasta `PAPER_SESSION_MAX_HOURS` (24h por defecto, configurable en `.env`)
evaluando un "partido nuevo" cada `PAPER_SESSION_INTERVAL_MINUTES` (30 min por
defecto), corriendo el pipeline completo (modelo → filtro Pinnacle → EV neto →
Kelly → liquidez → ejecución simulada) y registrando cada decisión en
`data/paper_trading_log.jsonl`. Cada ~50 decisiones resueltas, reentrenar el
modelo automáticamente con lo acumulado (`_maybe_retrain`). Se puede detener
antes con `Ctrl+C` sin perder el log parcial.

**Limitación real, no cosmética:** hoy no hay un módulo que descubra mercados
de tenis activos en Polymarket — la sesión simula la llegada de partidos con
el mismo generador sintético del backtest. Sirve para validar que todo el
ciclo (detección → decisión → registro → reentrenamiento) funciona de punta a
punta, pero el dataset resultante es sintético, no real. Para que esta sesión
opere contra mercados y resultados reales hace falta construir la integración
con la API Gamma de Polymarket (descubrimiento de mercados) — no está hecha
todavía.

## Modo producción (VPS + capital real)

```bash
cp .env.example .env        # completar credenciales reales, PAPER_TRADING=false
docker compose up --build   # levanta redis + engine (con chrony para 2.3)
streamlit run interface/dashboard.py   # UI aparte, en el VPS o via SSH tunnel
python interface/telegram_bot.py       # bot de control aparte
```

## Advertencia

Este es un esqueleto de arquitectura de nivel producción, no una estrategia con edge probado.
El trading automatizado con capital real conlleva riesgo de pérdida total. Los módulos de
predicción (XGBoost/LightGBM) requieren backtesting riguroso con validación temporal antes de
operar con dinero real, y el dimensionamiento de posiciones (Kelly) debe calibrarse de forma
conservadora (1/4–1/2 Kelly como mínimo). No soy asesor financiero; esto es infraestructura, no
una recomendación de inversión.
