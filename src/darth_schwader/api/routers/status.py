from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from darth_schwader.api.templating import is_htmx, render_partial

router = APIRouter(tags=["status"])


@router.get("/status")
async def status(request: Request) -> dict[str, object] | HTMLResponse:
    started_at = request.app.state.started_at
    uptime = (datetime.now(tz=UTC) - started_at).total_seconds()
    payload = {
        "bot_state": request.app.state.bot_state,
        "paper_trading": request.app.state.settings.paper_trading,
        "hitl_required": request.app.state.settings.hitl_required,
        "uptime_seconds": uptime,
        "last_scheduler_run": request.app.state.last_scheduler_run,
    }
    if is_htmx(request):
        return render_partial(
            request,
            "_status_header.html",
            {"settings": request.app.state.settings, **payload},
        )
    return payload


__all__ = ["router"]
