"""
CAPA 5.2 - Monitoreo activo (Pattern Heartbeat).

Envia un ping a un servicio externo tipo Better Uptime cada N segundos. Si el
proceso se cae o se cuelga, el servicio externo detecta la ausencia de
heartbeats (configurar la alerta del lado de Better Uptime a 3 minutos) y
dispara la alerta -- deliberadamente fuera del propio bot, porque un bot
colgado no puede alertar sobre si mismo.
"""
from __future__ import annotations

import asyncio

import aiohttp
import structlog

from config.settings import settings

logger = structlog.get_logger()


async def heartbeat_loop(stop_event: asyncio.Event) -> None:
    if not settings.betteruptime_heartbeat_url:
        logger.warning("heartbeat.disabled_no_url_configured")
        return

    async with aiohttp.ClientSession() as session:
        while not stop_event.is_set():
            try:
                async with session.get(settings.betteruptime_heartbeat_url, timeout=5) as resp:
                    logger.debug("heartbeat.sent", status=resp.status)
            except Exception as exc:
                logger.error("heartbeat.failed", error=str(exc))
            await asyncio.sleep(settings.heartbeat_interval_s)
