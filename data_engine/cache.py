"""Wrapper delgado sobre redis-py para cachear datos estaticos de atletas (1.2)."""
from __future__ import annotations

import json
from typing import Any

import redis.asyncio as redis

from config.settings import settings

_DEFAULT_TTL_S = 6 * 3600  # datos de atleta cambian poco intradia


class RedisCache:
    def __init__(self, url: str | None = None):
        self._redis = redis.from_url(url or settings.redis_url, decode_responses=True)

    async def get_json(self, key: str) -> Any | None:
        raw = await self._redis.get(key)
        return json.loads(raw) if raw else None

    async def set_json(self, key: str, value: Any, ttl_s: int = _DEFAULT_TTL_S) -> None:
        await self._redis.set(key, json.dumps(value), ex=ttl_s)

    async def close(self) -> None:
        await self._redis.aclose()


cache = RedisCache()
