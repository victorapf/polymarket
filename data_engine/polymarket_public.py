"""
Cliente de datos PUBLICOS de Polymarket -- descubrimiento de mercados (Gamma
API) y precios/orderbook (CLOB API). Ninguno de estos endpoints requiere
wallet, API key ni firma: son de solo lectura y publicos por diseno. Esto es
lo que permite hacer paper-trading con datos reales sin tener capital ni
credenciales todavia.

Endpoints verificados contra la documentacion oficial (docs.polymarket.com,
Sep 2026):
  - Gamma API:  https://gamma-api.polymarket.com  (mercados, eventos, tags -- publico)
  - CLOB API:   https://clob.polymarket.com       (precio, orderbook -- lectura publica)

Los campos `outcomes`, `outcomePrices` y `clobTokenIds` que devuelve Gamma
vienen como strings JSON-encoded (doble-encoded), no como arrays reales --
hay que hacerles json.loads() antes de usarlos. Es un detalle documentado que
rompe integraciones si se pasa por alto.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"

# Patron de slug verificado para mercados recurrentes de BTC UP/DOWN de 15 min:
# "btc-updown-15m-{unix_timestamp}", donde el timestamp es el inicio de la
# ventana de 15 minutos (multiplo de 900 segundos, UTC). Confirmado por
# multiples integraciones independientes (bots de Polymarket en produccion) y
# por la estructura analoga documentada para el mercado gemelo de 5 minutos.
BTC_15M_SLUG_PREFIX = "btc-updown-15m"
WINDOW_SECONDS = 900


@dataclass
class PolymarketOutcome:
    label: str
    price: float
    token_id: str


@dataclass
class PolymarketMarket:
    market_id: str
    question: str
    slug: str
    condition_id: str
    active: bool
    closed: bool
    end_date: str | None
    outcomes: list[PolymarketOutcome]

    def token_id_for(self, label: str) -> str | None:
        for o in self.outcomes:
            if o.label.lower() == label.lower():
                return o.token_id
        return None


class PolymarketPublicClient:
    def __init__(self):
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, max=4))
    async def _get(self, base: str, path: str, params: dict | None = None) -> dict | list:
        session = await self._get_session()
        async with session.get(f"{base}{path}", params=params, timeout=10) as resp:
            resp.raise_for_status()
            return await resp.json()

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------
    def _parse_market(self, m: dict) -> PolymarketMarket | None:
        try:
            labels = json.loads(m.get("outcomes", "[]"))
            prices = json.loads(m.get("outcomePrices", "[]"))
            token_ids = json.loads(m.get("clobTokenIds", "[]"))
        except (json.JSONDecodeError, TypeError):
            return None
        if not (len(labels) == len(prices) == len(token_ids)):
            return None

        outcomes = [
            PolymarketOutcome(label=labels[i], price=float(prices[i]), token_id=token_ids[i])
            for i in range(len(labels))
        ]
        return PolymarketMarket(
            market_id=str(m.get("id", "")),
            question=m.get("question", ""),
            slug=m.get("slug", ""),
            condition_id=m.get("conditionId", ""),
            active=bool(m.get("active", False)),
            closed=bool(m.get("closed", False)),
            end_date=m.get("endDate"),
            outcomes=outcomes,
        )

    # ------------------------------------------------------------------
    # Descubrimiento: BTC 15 minutos
    # ------------------------------------------------------------------
    async def find_current_btc_15m_market(self) -> PolymarketMarket | None:
        """
        Genera candidatos de slug alrededor de la ventana de 15 min actual y
        consulta Gamma hasta encontrar el mercado activo real. El patron de
        slug (btc-updown-15m-<timestamp>) esta verificado contra multiples
        integraciones reales, no es una suposicion.
        """
        now = int(time.time())
        current_window_start = now - (now % WINDOW_SECONDS)

        # Probar la ventana actual primero, luego vecinas por si hay drift
        # de reloj o el mercado todavia no rota.
        candidate_starts = [
            current_window_start,
            current_window_start + WINDOW_SECONDS,
            current_window_start - WINDOW_SECONDS,
        ]

        for start_ts in candidate_starts:
            slug = f"{BTC_15M_SLUG_PREFIX}-{start_ts}"
            data = await self._get(
                GAMMA_BASE, "/markets", params={"slug": slug, "active": "true", "closed": "false"}
            )
            markets = data if isinstance(data, list) else data.get("data", [])
            for m in markets:
                parsed = self._parse_market(m)
                if parsed and parsed.active and not parsed.closed:
                    return parsed
        return None

    # ------------------------------------------------------------------
    # Descubrimiento: eventos de tenis activos
    # ------------------------------------------------------------------
    async def _find_tag_id(self, label_substring: str) -> str | None:
        tags = await self._get(GAMMA_BASE, "/tags")
        tags_list = tags if isinstance(tags, list) else tags.get("data", [])
        for tag in tags_list:
            if label_substring.lower() in str(tag.get("label", "")).lower():
                return str(tag.get("id"))
        return None

    async def find_active_tennis_events(self, limit: int = 20) -> list[dict]:
        """
        Devuelve eventos de tenis activos (con sus mercados anidados, ya
        parseados). Cada evento tipicamente tiene un solo mercado binario
        (Jugador A gana / no gana), con nombres reales tal como los escribe
        Polymarket -- por eso sigue haciendo falta el fuzzy matching de
        CAPA 1.1 para cruzarlos contra una fuente de estadisticas.
        """
        tag_id = await self._find_tag_id("tennis")
        params: dict = {"active": "true", "closed": "false", "limit": limit}
        if tag_id:
            params["tag_id"] = tag_id

        events = await self._get(GAMMA_BASE, "/events", params=params)
        events_list = events if isinstance(events, list) else events.get("data", [])

        results = []
        for event in events_list:
            parsed_markets = [
                pm for pm in (self._parse_market(m) for m in event.get("markets", [])) if pm
            ]
            if parsed_markets:
                results.append(
                    {
                        "event_title": event.get("title", ""),
                        "event_slug": event.get("slug", ""),
                        "markets": parsed_markets,
                    }
                )
        return results

    # ------------------------------------------------------------------
    # Precios / orderbook publicos (CLOB API)
    # ------------------------------------------------------------------
    async def get_orderbook(self, token_id: str) -> dict:
        """GET /book?token_id=... -- publico, sin autenticacion."""
        return await self._get(CLOB_BASE, "/book", params={"token_id": token_id})

    async def get_price(self, token_id: str, side: str = "BUY") -> dict:
        """GET /price?token_id=...&side=BUY|SELL -- publico, sin autenticacion."""
        return await self._get(CLOB_BASE, "/price", params={"token_id": token_id, "side": side})

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
