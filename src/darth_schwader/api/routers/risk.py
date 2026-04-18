from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from darth_schwader.api.deps import get_session
from darth_schwader.api.templating import is_htmx, render_partial
from darth_schwader.db.models import RiskEvent

router = APIRouter(tags=["risk"])


@router.get("/risk-events")
async def risk_events(
    request: Request,
    signal_id: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]] | HTMLResponse:
    stmt = select(RiskEvent).order_by(RiskEvent.created_at.desc()).limit(20)
    if signal_id is not None:
        stmt = stmt.where(RiskEvent.signal_id == signal_id)
    rows = await session.scalars(stmt)
    payload = [
        {
            "id": row.id,
            "decision": row.decision,
            "reason_code": row.reason_code,
            "reason_text": row.reason_text,
            "approved_quantity": row.approved_quantity,
            "warnings": row.warnings_json,
        }
        for row in rows
    ]
    if is_htmx(request):
        return render_partial(request, "_risk_log.html", {"risk_events": payload})
    return payload


@router.get("/risk-events/{risk_event_id}")
async def risk_event(risk_event_id: int, session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    row = await session.get(RiskEvent, risk_event_id)
    if row is None:
        raise ValueError("risk event not found")
    return {
        "id": row.id,
        "decision": row.decision,
        "rule_results": row.rule_results_json,
        "warnings": row.warnings_json,
    }


__all__ = ["router"]
