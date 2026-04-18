from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from darth_schwader.config import get_settings
from darth_schwader.db.session import build_engine, build_session_factory, dispose_engine
from darth_schwader.logging import configure_logging


@asynccontextmanager
async def app_lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings)

    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)
    scheduler = AsyncIOScheduler(timezone="America/Chicago")

    app.state.settings = settings
    app.state.db_engine = engine
    app.state.session_factory = session_factory
    app.state.scheduler = scheduler

    scheduler.start(paused=False)
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        await dispose_engine(engine)


__all__ = ["app_lifespan"]
