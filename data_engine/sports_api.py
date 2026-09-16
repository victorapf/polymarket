"""
CAPA 1.2 - Cliente de APIs deportivas estructuradas (Sportradar / Tennis-Data),
evitando scraping directo. Cachea en Redis los datos estaticos del atleta
(historial, edad, alcance, ranking) para minimizar llamadas repetidas.

Si en el futuro se necesita scraping complementario, este es el punto donde se
inyectaria un pool de proxies residenciales rotativos (ScrapingBee/BrightData)
detras de un rate limiter -- ver `_proxy_pool` mas abajo.
"""
from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings
from data_engine.cache import cache

SPORTRADAR_BASE = "https://api.sportradar.com"


class SportsDataClient:
    def __init__(self, proxy_pool: list[str] | None = None):
        self._session: aiohttp.ClientSession | None = None
        self._proxy_pool = proxy_pool or []  # opcional, para scraping complementario
        self._proxy_idx = 0

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def _next_proxy(self) -> str | None:
        if not self._proxy_pool:
            return None
        proxy = self._proxy_pool[self._proxy_idx % len(self._proxy_pool)]
        self._proxy_idx += 1
        return proxy

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, max=4))
    async def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        session = await self._get_session()
        proxy = self._next_proxy()
        async with session.get(url, params=params, proxy=proxy, timeout=10) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_player_profile(self, player_id: str, sport: str) -> dict[str, Any]:
        cache_key = f"athlete:{sport}:{player_id}"
        cached = await cache.get_json(cache_key)
        if cached is not None:
            return cached

        url = f"{SPORTRADAR_BASE}/{sport}/trial/v3/en/players/{player_id}/profile.json"
        data = await self._get(url, params={"api_key": settings.sportradar_api_key})
        await cache.set_json(cache_key, data)
        return data

    async def get_h2h(self, player_a_id: str, player_b_id: str, sport: str) -> dict[str, Any]:
        cache_key = f"h2h:{sport}:{min(player_a_id, player_b_id)}:{max(player_a_id, player_b_id)}"
        cached = await cache.get_json(cache_key)
        if cached is not None:
            return cached
        url = f"{SPORTRADAR_BASE}/{sport}/trial/v3/en/players/{player_a_id}/versus/{player_b_id}/summary.json"
        data = await self._get(url, params={"api_key": settings.sportradar_api_key})
        await cache.set_json(cache_key, data, ttl_s=24 * 3600)
        return data

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
