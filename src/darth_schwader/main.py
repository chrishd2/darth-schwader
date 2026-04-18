from __future__ import annotations

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
    chains_router,
    health_router,
    orders_router,
    positions_router,
    risk_router,
    settings_router,
    signals_router,
    status_router,
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
        template_name = "index.html"
        if (TEMPLATES_DIR / template_name).exists():
            return templates.TemplateResponse(
                request=request,
                name=template_name,
                context={"request": request, "settings": settings},
            )
        return HTMLResponse("<html><body><h1>Darth Schwader</h1><p>Phase 1 scaffold.</p></body></html>")

    for router in (
        health_router,
        status_router,
        broker_router,
        chains_router,
        positions_router,
        orders_router,
        signals_router,
        risk_router,
        settings_router,
        admin_router,
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
