from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

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
    ) -> TokenRecord:
        now = datetime.now(tz=UTC)
        async with self._session_factory() as session:
            existing = await session.scalar(
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
                session.add(existing)
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
            await session.commit()
            await session.refresh(existing)
            return self._to_record(existing)

    async def get_active(self, provider: str) -> TokenRecord | None:
        async with self._session_factory() as session:
            token = await session.scalar(
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
    ) -> None:
        async with self._session_factory() as session:
            token = await session.scalar(
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
            await session.commit()

    async def delete(self, provider: str) -> None:
        async with self._session_factory() as session:
            await session.execute(delete(BrokerToken).where(BrokerToken.provider == provider))
            await session.commit()

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
