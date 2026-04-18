from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from darth_schwader.config import Settings, get_settings
from darth_schwader.risk.engine import RiskEngine


def get_app_state(request: Request) -> object:
    return request.app.state


def get_runtime_settings() -> Settings:
    return get_settings()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        yield session
    finally:
        await session.close()


def get_broker(request: Request) -> object:
    return request.app.state.broker


def get_risk_engine(request: Request) -> RiskEngine:
    return request.app.state.risk_engine


def get_order_service(request: Request) -> object:
    return request.app.state.order_service


__all__ = [
    "get_app_state",
    "get_broker",
    "get_order_service",
    "get_risk_engine",
    "get_runtime_settings",
    "get_session",
]
