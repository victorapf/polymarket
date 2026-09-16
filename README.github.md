# Polymarket Bot

Algorithmic trading bot for [Polymarket](https://polymarket.com) (Polygon), built around two
verticals with very different latency requirements:

- **Tennis (low-frequency)** — match and *per-set* winner prediction models.
- **BTC 15m (high-frequency)** — recurring UP/DOWN markets driven by live order-flow microstructure.

The engine is headless (Python asyncio, no UI) and designed to run inside Docker on a VPS,
while Streamlit and Telegram frontends talk to it over a shared state layer.

> **Status: research-grade, paper-traded pipeline.** The full detection → prediction → EV filter →
> Kelly sizing → liquidity check → (simulated) execution loop is implemented and validated with
> `pytest` and paper sessions. It is **not** a proven profit strategy. The ML models are
> validated with time-series cross-validation only and must beat their baseline on *real* data
> before any real capital is connected.

---

## Highlights

- **Per-set tennis prediction** — a real-time scraper for [SofaScore](https://www.sofascore.com)
  (`sport/tennis/events/live` + per-event statistics) builds a labeled dataset of in-progress
  sets, strictly **without look-ahead**: features for a set are computed only from previous sets'
  results and stats, and the label is produced when the match transitions to the next set.
- **BTC 15m microstructure** — Binance WebSocket order flow (CVD, book imbalance) + real
  Polymarket order books via the public Gamma/CLOB APIs. Paper executes into real markets.
- **Paper trading by default** — `PAPER_TRADING=true` runs the full pipeline with an in-memory
  order client: no private key, no gas, no real orders.

## Project layout

```
├── config/            # Pydantic-settings config (env-driven)
├── data_engine/       # Ingestion & normalization
│   ├── sofascore_tennis.py   # SofaScore live scraper + per-set feature builder
│   ├── polymarket_public.py  # Gamma/CLOB public market discovery
│   ├── binance_ws.py         # BTC order-flow websocket
│   ├── sports_api.py         # Sports-data client layer
│   ├── fuzzy_matcher.py      # Athlete name matching
│   ├── decision_logger.py    # Decision log (JSONL)
│   └── chainlink_monitor.py  # Chainlink vs spot divergence
├── quant/             # Signals, models, risk
│   ├── sports_model.py       # LightGBM, TimeSeriesSplit only (no look-ahead)
│   ├── sports_features.py    # Feature column definitions per sport
│   ├── ev.py / kelly.py      # Expected value + fractional Kelly sizing
│   ├── btc_microstructure.py # CVD & book imbalance
│   └── risk_manager.py       # Circuit breakers, daily stop-loss, kill switch
├── execution/         # Order execution & microstructure checks
│   ├── orderbook_analyzer.py # Slippage/spread/liquidity gates
│   ├── order_manager.py      # Cancel-replace limit orders
│   ├── fee_checker.py        # Net-of-fee EV
│   └── clob_client_wrapper.py # py-clob-client-v2 wrapper (production path)
├── backtest/          # Synthetic dataset + full loop replay
├── scripts/           # Runnable entry points (backtest / paper / scraper / discovery)
├── interface/         # Streamlit dashboard + Telegram control bot
├── monitoring/        # External heartbeat
├── infra/             # Hot-wallet custody, RPC failover, clock drift check
└── tests/             # pytest suite
```

## Quick start (local, paper mode)

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows  |  source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt

cp .env.example .env          # leave PAPER_TRADING=true
```

No private keys or API keys are needed for paper mode.

### Run the pipeline

```bash
# 1) Validation: full backtest loop on synthetic tennis data (no network)
python scripts/run_tennis_backtest.py

# 2) End-to-end paper session: model → Pinnacle filter → net EV → Kelly →
#    liquidity → simulated execution, one new "match" every 30 min,
#    every decision appended to data/paper_trading_log.jsonl
python scripts/run_tennis_paper_session.py

# 3) Tests
pytest
```

### Real data

```bash
# Tennis: collect labeled in-progress sets from SofaScore (polling loop)
python scripts/scrape_tennis_sets.py --collect --minutes 30

# Train & evaluate the per-set model vs its majority-class baseline
python scripts/scrape_tennis_sets.py --train

# BTC 15m: live Binance order flow + real Polymarket order book, paper execution
python scripts/run_btc_live_paper.py

# What tennis markets are live right now on Polymarket (public APIs, no keys)
python scripts/discover_tennis_markets.py
```

## Environment variables

Full reference with sensible defaults in [`.env.example`](.env.example).

| Variable | Default | Purpose |
|---|---|---|
| `PAPER_TRADING` | `true` | `true` = simulated orders; `false` = real capital (needs `PRIVATE_KEY`) |
| `DAILY_STOPLOSS_PCT` | `0.05` | Daily risk circuit breaker |
| `KELLY_FRACTION` | `0.25` | Fractional Kelly position sizing |
| `MAX_SLIPPAGE_PCT` / `MAX_SPREAD_PCT` | `0.015` / `0.02` | Execution gates |
| `RPC_URLS` | Alchemy, Infura, Ankr | Polygon RPCs with automatic failover |
| `REDIS_URL` | `redis://localhost:6379/0` | Shared state / cache for UI layer |

**Never commit `PRIVATE_KEY`. The `.env` file is not in the repo.**

## Honest limitations

- **No proven edge.** Models are validated out-of-sample by time (TimeSeriesSplit) but on a small
  real dataset so far. Run `--collect` long enough to accumulate labeled sets before trusting
  `--train` accuracies.
- **BTC probability is a heuristic**, not a trained model — no historical CVD/imbalance +
  outcome dataset exists yet to calibrate it.
- **Tennis match-level features** (Elo, serve %, H2H) need a live data feed; the current real-data
  path focuses on *per-set* features, which need only SofaScore's free public endpoints.
- **`main.py` is a stub** for the always-on engine loop; the validated entry points are the
  `scripts/` ones above.
- Not implemented on purpose: geo-bypass tooling for Polymarket (it's jurisdictionally restricted).

## Disclaimer

Automated trading with real capital carries risk of total loss. This is infrastructure and
research, not investment advice. Psych durations, confirm no edge net of fees with real data,
and size positions conservatively (1/4–1/2 Kelly) before going live.