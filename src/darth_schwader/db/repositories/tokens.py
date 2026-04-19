from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import AsyncIterator

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from darth_schwader.config import Settings
from darth_schwader.db.models import BrokerToken


class TokenDecryptError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class TokenRecord:
    provider: str
    access_token: SecretStr
    refresh_token: SecretStr
    access_token_expires_at: datetime
    refresh_token_expires_at: datetime
    token_type: str
    scope: str | None
    version: int


class TokenRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._fernet = Fernet(settings.token_encryption_key.get_secret_value().encode("utf-8"))

    @asynccontextmanager
    async def _maybe_session(
        self, session: AsyncSession | None
    ) -> AsyncIterator[tuple[AsyncSession, bool]]:
        if session is not None:
            yield session, False
            return
        async with self._session_factory() as owned:
            yield owned, True

    def _encrypt(self, value: SecretStr) -> str:
        return self._fernet.encrypt(value.get_secret_value().encode("utf-8")).decode("utf-8")

    def _decrypt(self, value: str) -> SecretStr:
        try:
            decrypted = self._fernet.decrypt(value.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise TokenDecryptError("failed to decrypt broker token") from exc
        return SecretStr(decrypted)

    async def upsert_tokens(
        self,
        *,
        provider: str,
        access_token: SecretStr,
        refresh_token: SecretStr,
        access_token_expires_at: datetime,
        refresh_token_expires_at: datetime,
        token_type: str = "Bearer",
        scope: str | None = None,
        session: AsyncSession | None = None,
    ) -> TokenRecord:
        now = datetime.now(tz=UTC)
        async with self._maybe_session(session) as (scope_session, owns):
            existing = await scope_session.scalar(
                select(BrokerToken).where(BrokerToken.provider == provider).limit(1)
            )
            if existing is None:
                existing = BrokerToken(
                    provider=provider,
                    access_token_ciphertext=self._encrypt(access_token),
                    refresh_token_ciphertext=self._encrypt(refresh_token),
                    access_token_expires_at=access_token_expires_at,
                    refresh_token_expires_at=refresh_token_expires_at,
                    token_type=token_type,
                    scope=scope,
                    rotated_at=now,
                    last_refresh_attempt_at=now,
                    last_refresh_success_at=now,
                    version=1,
                )
                scope_session.add(existing)
            else:
                existing.access_token_ciphertext = self._encrypt(access_token)
                existing.refresh_token_ciphertext = self._encrypt(refresh_token)
                existing.access_token_expires_at = access_token_expires_at
                existing.refresh_token_expires_at = refresh_token_expires_at
                existing.token_type = token_type
                existing.scope = scope
                existing.rotated_at = now
                existing.last_refresh_attempt_at = now
                existing.last_refresh_success_at = now
                existing.version += 1
            if owns:
                await scope_session.commit()
                await scope_session.refresh(existing)
            else:
                await scope_session.flush()
            return self._to_record(existing)

    async def get_active(
        self,
        provider: str,
        *,
        session: AsyncSession | None = None,
    ) -> TokenRecord | None:
        async with self._maybe_session(session) as (scope_session, _):
            token = await scope_session.scalar(
                select(BrokerToken).where(BrokerToken.provider == provider).limit(1)
            )
            if token is None:
                return None
            return self._to_record(token)

    async def mark_refreshed(
        self,
        provider: str,
        *,
        access_token_expires_at: datetime,
        refresh_token_expires_at: datetime,
        session: AsyncSession | None = None,
    ) -> None:
        async with self._maybe_session(session) as (scope_session, owns):
            token = await scope_session.scalar(
                select(BrokerToken).where(BrokerToken.provider == provider).limit(1)
            )
            if token is None:
                return
            now = datetime.now(tz=UTC)
            token.access_token_expires_at = access_token_expires_at
            token.refresh_token_expires_at = refresh_token_expires_at
            token.last_refresh_attempt_at = now
            token.last_refresh_success_at = now
            token.rotated_at = now
            if owns:
                await scope_session.commit()
            else:
                await scope_session.flush()

    async def delete(
        self,
        provider: str,
        *,
        session: AsyncSession | None = None,
    ) -> None:
        async with self._maybe_session(session) as (scope_session, owns):
            await scope_session.execute(
                delete(BrokerToken).where(BrokerToken.provider == provider)
            )
            if owns:
                await scope_session.commit()
            else:
                await scope_session.flush()

    def _to_record(self, row: BrokerToken) -> TokenRecord:
        return TokenRecord(
            provider=row.provider,
            access_token=self._decrypt(row.access_token_ciphertext),
            refresh_token=self._decrypt(row.refresh_token_ciphertext),
            access_token_expires_at=row.access_token_expires_at,
            refresh_token_expires_at=row.refresh_token_expires_at,
            token_type=row.token_type,
            scope=row.scope,
            version=row.version,
        )


__all__ = ["TokenDecryptError", "TokenRecord", "TokenRepository"]
