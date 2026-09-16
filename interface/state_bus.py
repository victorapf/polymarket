"""
Canal de estado compartido entre el motor headless y las interfaces (Streamlit,
Telegram). El motor escribe estado (balance, posiciones, latencias) en Redis;
las interfaces solo leen. Los controles (kill switch, pausa, fraccion de Kelly)
se escriben como comandos en una cola separada que el motor consume en su loop
principal -- las interfaces NUNCA llaman directamente a funciones de trading.
"""
from __future__ import annotations

import json
import time
from typing import Any

import redis.asyncio as redis

from config.settings import settings

STATE_KEY = "bot:state"
COMMAND_CHANNEL = "bot:commands"


class StateBus:
    def __init__(self, url: str | None = None):
        self._redis = redis.from_url(url or settings.redis_url, decode_responses=True)

    # --- Motor -> UI (estado, solo el motor escribe) ---
    async def publish_state(self, state: dict[str, Any]) -> None:
        state["_updated_at"] = time.time()
        await self._redis.set(STATE_KEY, json.dumps(state))

    async def read_state(self) -> dict[str, Any] | None:
        raw = await self._redis.get(STATE_KEY)
        return json.loads(raw) if raw else None

    # --- UI -> Motor (comandos, solo la UI publica) ---
    async def send_command(self, command: str, payload: dict[str, Any] | None = None) -> None:
        msg = json.dumps({"command": command, "payload": payload or {}, "ts": time.time()})
        await self._redis.publish(COMMAND_CHANNEL, msg)

    async def command_listener(self):
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(COMMAND_CHANNEL)
        async for message in pubsub.listen():
            if message["type"] == "message":
                yield json.loads(message["data"])
