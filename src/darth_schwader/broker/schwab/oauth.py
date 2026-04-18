from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from pydantic import SecretStr

from darth_schwader.config import Settings
from darth_schwader.db.repositories.tokens import TokenRecord, TokenRepository

from .endpoints import OAUTH_AUTHORIZE_URL, OAUTH_TOKEN_URL


@dataclass(slots=True, frozen=True)
class PkceChallenge:
    code_verifier: str
    code_challenge: str
    state: str


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("utf-8").rstrip("=")


def generate_pkce_pair() -> PkceChallenge:
    code_verifier = _b64url(secrets.token_bytes(48))
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    return PkceChallenge(
        code_verifier=code_verifier,
        code_challenge=_b64url(digest),
        state=secrets.token_urlsafe(24),
    )


class SchwabOAuthClient:
    def __init__(
        self,
        settings: Settings,
        token_repo: TokenRepository,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._token_repo = token_repo
        self._client = client or httpx.AsyncClient(timeout=30.0)

    def build_authorize_url(self, state: str, code_challenge: str) -> str:
        params = urlencode(
            {
                "response_type": "code",
                "client_id": self._settings.schwab_client_id,
                "redirect_uri": str(self._settings.schwab_redirect_uri),
                "scope": "readonly trading",
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{OAUTH_AUTHORIZE_URL}?{params}"

    async def exchange_code_for_tokens(self, code: str, code_verifier: str) -> TokenRecord:
        response = await self._client.post(
            OAUTH_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": str(self._settings.schwab_redirect_uri),
                "client_id": self._settings.schwab_client_id,
                "code_verifier": code_verifier,
            },
            auth=(
                self._settings.schwab_client_id,
                self._settings.schwab_client_secret.get_secret_value(),
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        payload = response.json()
        return await self._persist_payload(payload)

    async def refresh_access_token(self, refresh_token: SecretStr) -> TokenRecord:
        response = await self._client.post(
            OAUTH_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token.get_secret_value(),
                "client_id": self._settings.schwab_client_id,
            },
            auth=(
                self._settings.schwab_client_id,
                self._settings.schwab_client_secret.get_secret_value(),
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        payload = response.json()
        if "refresh_token" not in payload:
            payload["refresh_token"] = refresh_token.get_secret_value()
        return await self._persist_payload(payload)

    async def _persist_payload(self, payload: dict[str, object]) -> TokenRecord:
        now = datetime.now(tz=UTC)
        access_expires_in = int(payload.get("expires_in", 1800))
        refresh_expires_in = int(payload.get("refresh_token_expires_in", 604800))
        return await self._token_repo.upsert_tokens(
            provider="schwab",
            access_token=SecretStr(str(payload["access_token"])),
            refresh_token=SecretStr(str(payload["refresh_token"])),
            access_token_expires_at=now + timedelta(seconds=access_expires_in),
            refresh_token_expires_at=now + timedelta(seconds=refresh_expires_in),
            token_type=str(payload.get("token_type", "Bearer")),
            scope=str(payload.get("scope")) if payload.get("scope") else None,
        )

    async def close(self) -> None:
        await self._client.aclose()


__all__ = ["PkceChallenge", "SchwabOAuthClient", "generate_pkce_pair"]
