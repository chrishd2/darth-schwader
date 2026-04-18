from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from darth_schwader.config import Settings
from darth_schwader.db.repositories.tokens import TokenDecryptError, TokenRepository


@pytest.mark.asyncio
async def test_token_repository_round_trip_and_wrong_key_failure(settings: Settings, session_factory) -> None:
    repo = TokenRepository(session_factory, settings)
    now = datetime.now(tz=UTC)
    await repo.upsert_tokens(
        provider="schwab",
        access_token=SecretStr("access-token"),
        refresh_token=SecretStr("refresh-token"),
        access_token_expires_at=now + timedelta(minutes=30),
        refresh_token_expires_at=now + timedelta(days=7),
    )

    record = await repo.get_active("schwab")
    assert record is not None
    assert record.access_token.get_secret_value() == "access-token"

    wrong_settings = Settings(
        env="test",
        database_url="sqlite+aiosqlite:///:memory:",
        schwab_client_id="client-id",
        schwab_client_secret="client-secret",
        schwab_account_number="123456789",
        token_encryption_key=Fernet.generate_key().decode("utf-8"),
        watchlist=["AAPL"],
    )
    wrong_repo = TokenRepository(session_factory, wrong_settings)
    with pytest.raises(TokenDecryptError):
        await wrong_repo.get_active("schwab")
