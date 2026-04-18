from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request

router = APIRouter(tags=["status"])


@router.get("/status")
async def status(request: Request) -> dict[str, object]:
    started_at = request.app.state.started_at
    uptime = (datetime.now(tz=UTC) - started_at).total_seconds()
    return {
        "bot_state": request.app.state.bot_state,
        "paper_trading": request.app.state.settings.paper_trading,
        "hitl_required": request.app.state.settings.hitl_required,
        "uptime_seconds": uptime,
        "last_scheduler_run": request.app.state.last_scheduler_run,
    }


__all__ = ["router"]
