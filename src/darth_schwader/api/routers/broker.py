from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from darth_schwader.api.deps import get_broker, get_session
from darth_schwader.db.models import ConfigRef

router = APIRouter(tags=["broker"])


@router.get("/broker/accounts")
async def broker_accounts(broker: object = Depends(get_broker)) -> list[dict[str, object]]:
    accounts = await broker.get_accounts()
    return [account.model_dump(mode="json") for account in accounts]


@router.get("/broker/oauth/callback")
async def broker_oauth_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    del state
    oauth_client = request.app.state.oauth_client
    verifier = await session.get(ConfigRef, "schwab_pkce_code_verifier")
    if verifier is None or not verifier.value:
        raise ValueError("missing persisted PKCE code verifier")
    token = await oauth_client.exchange_code_for_tokens(code, verifier.value)
    verifier.value = ""
    await session.commit()
    return {"status": "ok", "provider": token.provider}


__all__ = ["router"]
