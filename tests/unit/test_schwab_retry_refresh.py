from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import SecretStr

from darth_schwader.broker.exceptions import AuthExpiredError
from darth_schwader.broker.schwab.client import SchwabApiClient
from darth_schwader.broker.schwab.endpoints import ACCOUNTS_URL, OAUTH_TOKEN_URL, OPTION_CHAINS_URL
from darth_schwader.config import Settings
from darth_schwader.db.repositories.tokens import TokenRepository


async def _seed_token(token_repo: TokenRepository) -> None:
    now = datetime.now(tz=UTC)
    await token_repo.upsert_tokens(
        provider="schwab",
        access_token=SecretStr("stale-token"),
        refresh_token=SecretStr("refresh-token"),
        access_token_expires_at=now + timedelta(minutes=30),
        refresh_token_expires_at=now + timedelta(days=7),
    )


@pytest.mark.asyncio
async def test_retry_refreshes_once_after_401(
    settings: Settings,
    session_factory,
    respx_mock,
) -> None:
    token_repo = TokenRepository(session_factory, settings)
    await _seed_token(token_repo)

    respx_mock.get(ACCOUNTS_URL).mock(
        side_effect=[
            httpx.Response(401, json={"error": "expired"}),
            httpx.Response(200, json=[]),
        ]
    )
    respx_mock.post(OAUTH_TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "fresh-token",
                "refresh_token": "fresh-refresh",
                "expires_in": 1800,
                "refresh_token_expires_in": 604800,
                "token_type": "Bearer",
            },
        )
    )

    client = SchwabApiClient(settings, token_repo, client=httpx.AsyncClient())
    try:
        accounts = await client.get_accounts()
        assert accounts == []
        token = await token_repo.get_active("schwab")
        assert token is not None
        assert token.access_token.get_secret_value() == "fresh-token"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_second_401_raises_auth_expired(
    settings: Settings,
    session_factory,
    respx_mock,
) -> None:
    token_repo = TokenRepository(session_factory, settings)
    await _seed_token(token_repo)

    respx_mock.get(ACCOUNTS_URL).mock(
        side_effect=[
            httpx.Response(401, json={"error": "expired"}),
            httpx.Response(401, json={"error": "still expired"}),
        ]
    )
    respx_mock.post(OAUTH_TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "fresh-token",
                "refresh_token": "fresh-refresh",
                "expires_in": 1800,
                "refresh_token_expires_in": 604800,
            },
        )
    )

    client = SchwabApiClient(settings, token_repo, client=httpx.AsyncClient())
    try:
        with pytest.raises(AuthExpiredError):
            await client.get_accounts()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_429_and_5xx_paths_retry_with_backoff(
    settings: Settings,
    session_factory,
    respx_mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_repo = TokenRepository(session_factory, settings)
    await _seed_token(token_repo)

    sleeps: list[int] = []

    async def _sleep(seconds: int) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("darth_schwader.broker.schwab.client.asyncio.sleep", _sleep)

    respx_mock.get(OPTION_CHAINS_URL).mock(
        side_effect=[
            httpx.Response(429, json={"error": "slow down"}),
            httpx.Response(
                200,
                json={
                    "symbol": "AAPL",
                    "quoteTimeInLong": 1713389400000,
                    "underlyingPrice": 195.25,
                    "callExpDateMap": {},
                    "putExpDateMap": {},
                },
            ),
            httpx.Response(500, json={"error": "server"}),
            httpx.Response(
                200,
                json={
                    "symbol": "AAPL",
                    "quoteTimeInLong": 1713389400000,
                    "underlyingPrice": 195.25,
                    "callExpDateMap": {},
                    "putExpDateMap": {},
                },
            ),
        ]
    )

    client = SchwabApiClient(settings, token_repo, client=httpx.AsyncClient())
    try:
        first = await client.get_chain("AAPL")
        second = await client.get_chain("AAPL")
        assert first.underlying == "AAPL"
        assert second.underlying == "AAPL"
        assert sleeps == [1, 1]
    finally:
        await client.close()
