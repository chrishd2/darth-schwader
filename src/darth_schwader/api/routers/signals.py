from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from darth_schwader.api.deps import get_broker, get_order_service, get_session
from darth_schwader.api.templating import is_htmx, render_partial
from darth_schwader.config import Settings, get_settings
from darth_schwader.db.models import AuditLog, ChainSnapshot, Signal
from darth_schwader.domain.enums import SignalStatus
from darth_schwader.risk.context import build_risk_context

router = APIRouter(tags=["signals"])


@router.get("/signals")
async def signals(
    request: Request,
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]] | HTMLResponse:
    stmt = select(Signal).order_by(Signal.created_at.desc())
    if status:
        stmt = stmt.where(Signal.status == status)
    rows = await session.scalars(stmt)
    payload = [
        {
            "id": row.id,
            "signal_id": row.signal_id,
            "underlying": row.underlying,
            "strategy_type": row.strategy_type,
            "status": row.status,
            "suggested_quantity": row.suggested_quantity,
            "preferred_quantity": row.preferred_quantity,
            "ceiling_quantity": row.ceiling_quantity,
            "suggested_max_loss": str(row.suggested_max_loss) if row.suggested_max_loss is not None else None,
            "thesis": row.thesis,
        }
        for row in rows
    ]
    if is_htmx(request):
        return render_partial(
            request,
            "_signals_queue.html",
            {"signals": payload, "settings": request.app.state.settings},
        )
    return payload


@router.post("/signals/{signal_id}/submit")
async def submit_signal(
    signal_id: int,
    request: Request,
    body: dict[str, object] = Body(default_factory=dict),
    session: AsyncSession = Depends(get_session),
    broker: object = Depends(get_broker),
    order_service: object = Depends(get_order_service),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    override_quantity = int(body["override_quantity"]) if "override_quantity" in body else None
    signal = await session.get(Signal, signal_id)
    if signal is None:
        raise ValueError("signal not found")

    leg_quotes = await _load_leg_quotes(session, signal)
    context = await build_risk_context(
        session,
        settings,
        bot_state=request.app.state.bot_state,
        underlying=signal.underlying,
        leg_quotes=leg_quotes,
    )
    order = await order_service.submit_signal(session, signal_id, override_quantity, broker, context)
    await session.commit()
    return {"order_id": order.id, "status": order.order_status}


@router.post("/signals/{signal_id}/reject")
async def reject_signal(
    signal_id: int,
    body: dict[str, str] = Body(...),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    signal = await session.get(Signal, signal_id)
    if signal is None:
        raise ValueError("signal not found")
    signal.status = SignalStatus.REJECTED
    session.add(
        AuditLog(
            event_type="SIGNAL_REJECTED",
            entity_type="signal",
            entity_id=str(signal.id),
            correlation_id=signal.signal_id,
            payload_json={"reason": body["reason"]},
        )
    )
    await session.commit()
    return {"status": "rejected"}


async def _load_leg_quotes(
    session: AsyncSession,
    signal: Signal,
) -> dict[str, dict[str, Decimal]]:
    quotes: dict[str, dict[str, Decimal]] = {}
    for leg in signal.proposed_payload["legs"]:
        row = await session.scalar(
            select(ChainSnapshot)
            .where(
                ChainSnapshot.underlying == signal.underlying,
                ChainSnapshot.expiration_date == leg["expiration"],
                ChainSnapshot.option_type == leg["option_type"],
                ChainSnapshot.strike == Decimal(str(leg["strike"])),
            )
            .order_by(ChainSnapshot.quote_time.desc())
            .limit(1)
        )
        if row is None:
            continue
        quotes[leg["occ_symbol"]] = {
            "bid": Decimal(str(row.bid or "0")),
            "ask": Decimal(str(row.ask or "0")),
            "open_interest": Decimal(str(row.open_interest or "0")),
        }
    return quotes


__all__ = ["router"]
