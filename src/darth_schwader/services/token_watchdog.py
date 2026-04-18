from __future__ import annotations

from datetime import UTC, datetime, timedelta

from darth_schwader.broker.schwab.oauth import SchwabOAuthClient
from darth_schwader.db.repositories.tokens import TokenRepository


async def token_watchdog(token_repo: TokenRepository, oauth_client: SchwabOAuthClient) -> bool:
    token = await token_repo.get_active("schwab")
    if token is None:
        return False
    if token.access_token_expires_at <= datetime.now(tz=UTC) + timedelta(minutes=10):
        await oauth_client.refresh_access_token(token.refresh_token)
        return True
    return False


__all__ = ["token_watchdog"]
