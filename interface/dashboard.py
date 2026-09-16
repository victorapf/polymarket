"""
CAPA 5.3 - Dashboard Web de control (Streamlit).

Lee estado publicado por el motor via StateBus (Redis). Los controles (kill
switch, fraccion de Kelly, toggles de estrategia) publican comandos que el
motor consume en su propio loop -- este archivo nunca importa modulos de
`execution/` ni `quant/` directamente.

Correr con: streamlit run interface/dashboard.py
"""
from __future__ import annotations

import asyncio

import pandas as pd
import streamlit as st

from interface.state_bus import StateBus

st.set_page_config(page_title="Polymarket Bot — Control", layout="wide")

bus = StateBus()


def run_async(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


state = run_async(bus.read_state()) or {}

st.title("🎯 Polymarket Bot — Panel de Control")

# --- Metricas principales ---
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Balance USDC", f"${state.get('balance_usdc', 0):,.2f}")
col2.metric("P/L del dia", f"${state.get('daily_pnl', 0):,.2f}")
col3.metric("Win Rate", f"{state.get('win_rate_pct', 0):.1f}%")
col4.metric("Latencia WS (ms)", f"{state.get('ws_latency_ms', 0):.0f}")
col5.metric("RPC activo", state.get("active_rpc", "—"))

st.divider()

# --- Curva de equidad ---
equity_curve = state.get("equity_curve", [])
if equity_curve:
    df_equity = pd.DataFrame(equity_curve)
    st.subheader("Curva de equidad")
    st.line_chart(df_equity.set_index("timestamp")["equity"])

# --- Posiciones activas ---
st.subheader("Apuestas activas")
active_positions = state.get("active_positions", [])
if active_positions:
    st.dataframe(pd.DataFrame(active_positions), use_container_width=True)
else:
    st.caption("Sin posiciones abiertas.")

# --- Orderbook comparativo ---
st.subheader("Orderbook: Polymarket vs Binance")
ob_col1, ob_col2 = st.columns(2)
with ob_col1:
    st.caption("Polymarket (token UP)")
    st.dataframe(pd.DataFrame(state.get("polymarket_orderbook", [])))
with ob_col2:
    st.caption("Binance BTC/USDT")
    st.dataframe(pd.DataFrame(state.get("binance_orderbook", [])))

# --- Historial de operaciones ---
st.subheader("Historial de operaciones")
st.dataframe(pd.DataFrame(state.get("trade_history", [])), use_container_width=True)

st.divider()

# --- Controles manuales ---
st.subheader("⚙️ Controles")
ctrl_col1, ctrl_col2, ctrl_col3 = st.columns(3)

with ctrl_col1:
    if st.button("🛑 KILL SWITCH — Parada de emergencia", type="primary"):
        run_async(bus.send_command("kill_switch"))
        st.error("Comando de parada de emergencia enviado al motor.")

with ctrl_col2:
    kelly_fraction = st.select_slider("Fraccion de Kelly", options=[0.1, 0.25, 0.5, 1.0], value=0.25)
    if st.button("Aplicar fraccion de Kelly"):
        run_async(bus.send_command("set_kelly_fraction", {"value": kelly_fraction}))
        st.success(f"Kelly fraction actualizado a {kelly_fraction}")

with ctrl_col3:
    strategy = st.selectbox("Estrategia", ["sports", "btc_15m"])
    enabled = st.toggle(f"Activar {strategy}", value=True)
    if st.button("Aplicar toggle"):
        run_async(bus.send_command("toggle_strategy", {"strategy": strategy, "enabled": enabled}))
        st.success(f"{strategy} {'activada' if enabled else 'desactivada'}")

st.caption(f"Ultima actualizacion de estado: {state.get('_updated_at', 'N/A')}")
