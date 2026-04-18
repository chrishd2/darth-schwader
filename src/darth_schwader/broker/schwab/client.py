from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx

from darth_schwader.broker.base import BrokerClient
from darth_schwader.broker.exceptions import (
    AuthExpiredError,
    BrokerError,
    OrderRejectedError,
    RateLimitError,
    TransientBrokerError,
)
from darth_schwader.broker.models import Account, OptionChain, OrderRequest, OrderResponse, Position
from darth_schwader.config import Settings
from darth_schwader.db.repositories.tokens import TokenRepository
from darth_schwader.logging import get_logger

from .endpoints import ACCOUNTS_URL, ORDER_URL, ORDERS_URL, OPTION_CHAINS_URL, POSITIONS_URL
from .mappers import (
    map_account,
    map_option_chain,
    map_order_request,
    map_order_response,
    map_position,
)
from .oauth import SchwabOAuthClient


class SchwabApiClient(BrokerClient):
    def __init__(
        self,
        settings: Settings,
        token_repo: TokenRepository,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._token_repo = token_repo
        self._oauth_client = SchwabOAuthClient(settings, token_repo)
        self._client = client or httpx.AsyncClient(timeout=30.0)
        self._refresh_lock = asyncio.Lock()
        self._logger = get_logger(__name__)

    async def get_accounts(self) -> list[Account]:
        payload = await self._request("GET", ACCOUNTS_URL, params={"fields": "positions"})
        return [map_account(item) for item in payload]

    async def get_positions(self, account_id: str) -> list[Position]:
        payload = await self._request(
            "GET",
            POSITIONS_URL.format(account_id=account_id),
            params={"fields": "positions"},
        )
        positions = payload.get("securitiesAccount", {}).get("positions", [])
        return [map_position(item) for item in positions]

    async def get_chain(self, symbol: str) -> OptionChain:
        payload = await self._request(
            "GET",
            OPTION_CHAINS_URL,
            params={
                "symbol": symbol,
                "contractType": "ALL",
                "strategy": "SINGLE",
                "includeUnderlyingQuote": "true",
            },
        )
        return map_option_chain(payload)

    async def submit_order(self, account_id: str, request: OrderRequest) -> OrderResponse:
        payload = await self._request(
            "POST",
            ORDERS_URL.format(account_id=account_id),
            json=map_order_request(request),
        )
        return map_order_response(payload, status_hint="SUBMITTED")

    async def get_order_status(self, account_id: str, broker_order_id: str) -> OrderResponse:
        payload = await self._request(
            "GET",
            ORDER_URL.format(account_id=account_id, order_id=broker_order_id),
        )
        return map_order_response(payload)

    async def cancel_order(self, account_id: str, broker_order_id: str) -> None:
        await self._request(
            "DELETE",
            ORDER_URL.format(account_id=account_id, order_id=broker_order_id),
        )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        retry_on_401: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        token = await self._token_repo.get_active("schwab")
        if token is None:
            raise AuthExpiredError("no active Schwab token record")

        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token.access_token.get_secret_value()}"
        headers["Accept"] = "application/json"

        attempt = 0
        max_attempts = 3
        while True:
            attempt += 1
            response = await self._client.request(method, url, headers=headers, **kwargs)

            if response.status_code == 401:
                if not retry_on_401:
                    raise AuthExpiredError("Schwab access token rejected after refresh retry")
                await self._refresh_tokens(force=True)
                fresh = await self._token_repo.get_active("schwab")
                if fresh is None:
                    raise AuthExpiredError("token refresh did not persist a valid token")
                headers["Authorization"] = f"Bearer {fresh.access_token.get_secret_value()}"
                retry_on_401 = False
                continue

            if response.status_code == 429:
                if attempt >= max_attempts:
                    raise RateLimitError("Schwab rate limit exceeded")
                await asyncio.sleep(2 ** (attempt - 1))
                continue

            if response.status_code >= 500:
                if attempt >= max_attempts:
                    raise TransientBrokerError(f"Schwab server error: {response.status_code}")
                await asyncio.sleep(2 ** (attempt - 1))
                continue

            if response.status_code == 400:
                raise BrokerError(f"Schwab rejected request: {response.text[:200]}")

            if response.status_code == 403:
                raise OrderRejectedError("Schwab rejected request with 403")

            response.raise_for_status()
            self._logger.info(
                "schwab_request_ok",
                method=method,
                url=url,
                status_code=response.status_code,
                attempted_refresh=not retry_on_401,
            )
            if response.content:
                return response.json()
            return {}

    async def _refresh_tokens(self, *, force: bool = False) -> None:
        async with self._refresh_lock:
            current = await self._token_repo.get_active("schwab")
            if current is None:
                raise AuthExpiredError("cannot refresh missing token record")
            if not force and current.access_token_expires_at > datetime.now(tz=UTC):
                return
            self._logger.warning("schwab_refresh_token_start")
            await self._oauth_client.refresh_access_token(current.refresh_token)
            self._logger.info("schwab_refresh_token_ok")

    async def close(self) -> None:
        await self._oauth_client.close()
        await self._client.aclose()


__all__ = ["SchwabApiClient"]
