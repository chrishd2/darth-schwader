from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import httpx

from darth_schwader.config import Settings

BASE_URL = "https://api.polygon.io"


class PolygonClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)

    def _api_key(self) -> str:
        if self._settings.polygon_api_key is None:
            raise RuntimeError("polygon_api_key is not configured")
        return self._settings.polygon_api_key.get_secret_value()

    async def get_option_chain(
        self,
        underlying: str,
        expiration_from: date,
        expiration_to: date,
    ) -> list[dict[str, Any]]:
        payload = await self._request(
            "/v3/snapshot/options/{underlying}".format(underlying=underlying.upper()),
            params={
                "expiration_date.gte": expiration_from.isoformat(),
                "expiration_date.lte": expiration_to.isoformat(),
                "limit": 250,
                "apiKey": self._api_key(),
            },
        )
        return list(payload.get("results", []))

    async def get_daily_ohlc(
        self,
        underlying: str,
        date_from: date,
        date_to: date,
    ) -> list[dict[str, Any]]:
        payload = await self._request(
            "/v2/aggs/ticker/{underlying}/range/1/day/{date_from}/{date_to}".format(
                underlying=underlying.upper(),
                date_from=date_from.isoformat(),
                date_to=date_to.isoformat(),
            ),
            params={"adjusted": "true", "sort": "asc", "apiKey": self._api_key()},
        )
        return list(payload.get("results", []))

    async def _request(self, path: str, *, params: dict[str, str]) -> dict[str, Any]:
        attempt = 0
        while True:
            attempt += 1
            response = await self._client.get(path, params=params)
            if response.status_code == 429:
                if attempt >= 3:
                    response.raise_for_status()
                await asyncio.sleep(2 ** (attempt - 1))
                continue
            if response.status_code >= 500:
                if attempt >= 3:
                    response.raise_for_status()
                await asyncio.sleep(2 ** (attempt - 1))
                continue
            response.raise_for_status()
            return response.json()

    async def close(self) -> None:
        await self._client.aclose()


__all__ = ["PolygonClient"]
