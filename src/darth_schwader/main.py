from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from darth_schwader.api.error_handlers import register_exception_handlers
from darth_schwader.api.routers import (
    admin_router,
    broker_router,
    cash_ledger_router,
    chains_router,
    health_router,
    orders_router,
    positions_router,
    risk_router,
    settings_router,
    setup_heatmap_router,
    signals_router,
    status_router,
    watchlist_router,
)
from darth_schwader.config import get_settings
from darth_schwader.lifespan import app_lifespan

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "ui" / "templates"
STATIC_DIR = BASE_DIR / "ui" / "static"


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Darth Schwader",
        version="0.1.0",
        lifespan=app_lifespan,
    )
    register_exception_handlers(app)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"request": request, "settings": settings},
        )

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(request: Request) -> HTMLResponse:
        started_at = getattr(request.app.state, "started_at", datetime.now(tz=UTC))
        uptime_seconds = (datetime.now(tz=UTC) - started_at).total_seconds()
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={
                "request": request,
                "settings": settings,
                "bot_state": getattr(request.app.state, "bot_state", "UNKNOWN"),
                "uptime_seconds": uptime_seconds,
                "last_scheduler_run": getattr(request.app.state, "last_scheduler_run", None),
            },
        )

    for router in (
        health_router,
        status_router,
        broker_router,
        cash_ledger_router,
        chains_router,
        positions_router,
        orders_router,
        signals_router,
        risk_router,
        settings_router,
        admin_router,
        watchlist_router,
        setup_heatmap_router,
    ):
        app.include_router(router, prefix="/api/v1")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR), check_dir=False), name="static")
    return app


def run() -> None:
    settings = get_settings()
    uvicorn.run(
        "darth_schwader.main:create_app",
        factory=True,
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.is_dev,
    )


__all__ = ["create_app", "run"]
