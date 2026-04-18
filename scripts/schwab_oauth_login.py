from __future__ import annotations

import asyncio
import webbrowser
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from darth_schwader.broker.schwab.oauth import SchwabOAuthClient, generate_pkce_pair
from darth_schwader.config import get_settings
from darth_schwader.db.repositories.tokens import TokenRepository
from darth_schwader.db.session import build_engine, build_session_factory, dispose_engine
from darth_schwader.logging import configure_logging, get_logger


@dataclass(slots=True)
class OAuthState:
    code: str | None = None
    error: str | None = None
    ready: asyncio.Event = field(default_factory=asyncio.Event)


def build_callback_app(state: OAuthState, expected_state: str, callback_path: str) -> FastAPI:
    app = FastAPI(title="Darth Schwader OAuth Callback")

    async def callback(
        code: str | None = Query(default=None),
        incoming_state: str | None = Query(default=None, alias="state"),
        error: str | None = Query(default=None),
    ) -> HTMLResponse:
        if error:
            state.error = error
            state.ready.set()
            raise HTTPException(status_code=400, detail=error)
        if not code or incoming_state != expected_state:
            state.error = "invalid oauth callback state"
            state.ready.set()
            raise HTTPException(status_code=400, detail="invalid oauth callback")
        state.code = code
        state.ready.set()
        return HTMLResponse("<html><body><h1>OAuth complete.</h1><p>You may close this tab.</p></body></html>")

    app.add_api_route(callback_path, callback, methods=["GET"], response_class=HTMLResponse)
    return app


async def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    logger = get_logger(__name__)

    cert_dir = Path("certs")
    cert_file = cert_dir / "localhost.pem"
    key_file = cert_dir / "localhost-key.pem"
    if not cert_file.exists() or not key_file.exists():
        raise FileNotFoundError("missing local TLS certificates; run scripts/bootstrap_local.sh first")

    redirect_uri = urlparse(str(settings.schwab_redirect_uri))
    if redirect_uri.scheme != "https":
        raise ValueError("schwab_redirect_uri must use https")
    if not redirect_uri.hostname or not redirect_uri.path:
        raise ValueError("schwab_redirect_uri must include a host and callback path")

    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)
    token_repo = TokenRepository(session_factory, settings)
    oauth_client = SchwabOAuthClient(settings, token_repo)
    pkce = generate_pkce_pair()

    state = OAuthState()
    app = build_callback_app(state, pkce.state, redirect_uri.path)
    config = uvicorn.Config(
        app=app,
        host=redirect_uri.hostname,
        port=redirect_uri.port or 443,
        log_level=settings.log_level.lower(),
        ssl_certfile=str(cert_file),
        ssl_keyfile=str(key_file),
    )
    server = uvicorn.Server(config)

    authorize_url = oauth_client.build_authorize_url(pkce.state, pkce.code_challenge)
    print("Authorize URL:")
    print(authorize_url)

    server_task = asyncio.create_task(server.serve())
    await asyncio.sleep(0.5)
    with suppress(Exception):
        webbrowser.open(authorize_url)

    await state.ready.wait()
    server.should_exit = True
    await server_task

    if state.error:
        raise RuntimeError(state.error)
    if not state.code:
        raise RuntimeError("oauth callback completed without an authorization code")

    token = await oauth_client.exchange_code_for_tokens(state.code, pkce.code_verifier)
    logger.info(
        "schwab_oauth_bootstrap_complete",
        provider=token.provider,
        access_token_expires_at=token.access_token_expires_at.isoformat(),
        refresh_token_expires_at=token.refresh_token_expires_at.isoformat(),
    )

    await oauth_client.close()
    await dispose_engine(engine)


if __name__ == "__main__":
    asyncio.run(main())
