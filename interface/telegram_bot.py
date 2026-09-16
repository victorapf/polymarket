"""
CAPA 5.4 - Bot de control movil (Telegram).

Igual que el dashboard, solo lee estado y publica comandos via StateBus. Envia
alertas push proactivas cuando el motor publica un evento de "orden ejecutada"
(ver `notify_order_executed`, invocado por el motor principal, no por este
archivo, para mantener la separacion motor/UI).

Correr con: python interface/telegram_bot.py
"""
from __future__ import annotations

import asyncio

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config.settings import settings
from interface.state_bus import StateBus

bus = StateBus()


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = await bus.read_state() or {}
    msg = (
        f"📊 *Estado del bot*\n"
        f"RPC activo: `{state.get('active_rpc', '—')}`\n"
        f"Latencia WS: {state.get('ws_latency_ms', 0):.0f}ms\n"
        f"Estrategias activas: {', '.join(state.get('active_strategies', [])) or 'ninguna'}\n"
        f"Posiciones abiertas: {len(state.get('active_positions', []))}"
    )
    await update.message.reply_markdown(msg)


async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = await bus.read_state() or {}
    msg = (
        f"💰 *Balance*\n"
        f"Operativo: ${state.get('balance_usdc', 0):,.2f}\n"
        f"Cold storage (referencial): ${state.get('cold_storage_balance_usdc', 0):,.2f}"
    )
    await update.message.reply_markdown(msg)


async def pause_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await bus.send_command("pause")
    await update.message.reply_text("⏸ Analisis de mercados pausado.")


async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await bus.send_command("kill_switch")
    await update.message.reply_text("🛑 Circuit breaker de emergencia disparado.")


async def notify_order_executed(app: Application, order_info: dict) -> None:
    """Invocado por el motor principal (via import directo o cola) tras cada fill."""
    msg = (
        f"✅ *Orden ejecutada*\n"
        f"Evento: {order_info['event']}\n"
        f"P. modelo: {order_info['model_probability']:.2%} | Cuota mercado: {order_info['market_price']:.2f}\n"
        f"Tamano: ${order_info['size']:.2f} | EV neto: {order_info['net_ev']:.2%}"
    )
    await app.bot.send_message(chat_id=settings.telegram_chat_id, text=msg, parse_mode="Markdown")


def build_app() -> Application:
    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CommandHandler("pause", pause_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    return app


if __name__ == "__main__":
    application = build_app()
    application.run_polling()
