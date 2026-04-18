from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from darth_schwader.api.deps import get_session
from darth_schwader.db.models import ConfigRef
from darth_schwader.services.reconciliation import reconcile_end_of_day

router = APIRouter(tags=["admin"])


@router.post("/admin/reconcile")
async def reconcile(request: Request) -> dict[str, str]:
    await reconcile_end_of_day(request.app.state.session_factory)
    request.app.state.last_scheduler_run = "reconcile"
    return {"status": "ok"}


@router.post("/admin/halt")
async def halt(request: Request, session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    row = await session.get(ConfigRef, "bot_state")
    if row is None:
        row = ConfigRef(key="bot_state", value="HALTED", description="runtime bot state")
        session.add(row)
    else:
        row.value = "HALTED"
    request.app.state.bot_state = "HALTED"
    await session.commit()
    return {"status": "HALTED"}


@router.post("/admin/resume")
async def resume(request: Request, session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    row = await session.get(ConfigRef, "bot_state")
    if row is None:
        row = ConfigRef(key="bot_state", value="ACTIVE", description="runtime bot state")
        session.add(row)
    else:
        row.value = "ACTIVE"
    request.app.state.bot_state = "ACTIVE"
    await session.commit()
    return {"status": "ACTIVE"}


__all__ = ["router"]
