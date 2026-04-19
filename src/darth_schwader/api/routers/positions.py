from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from darth_schwader.api.deps import get_session
from darth_schwader.api.templating import is_htmx, render_partial
from darth_schwader.db.models import Position
from darth_schwader.domain.enums import StrategyType

router = APIRouter(tags=["positions"])

_EQUITY_STRATEGIES: frozenset[StrategyType] = frozenset(
    {StrategyType.LONG_EQUITY, StrategyType.SHORT_EQUITY}
)
_FUTURES_STRATEGIES: frozenset[StrategyType] = frozenset(
    {StrategyType.LONG_FUTURE, StrategyType.SHORT_FUTURE}
)


def _asset_badge(strategy_type: StrategyType) -> str:
    if strategy_type in _FUTURES_STRATEGIES:
        return "F"
    if strategy_type in _EQUITY_STRATEGIES:
        return "E"
    return "O"


@router.get("/positions", response_model=None)
async def positions(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]] | HTMLResponse:
    rows = await session.scalars(select(Position).order_by(Position.updated_at.desc()))
    payload: list[dict[str, object]] = [
        {
            "id": row.id,
            "underlying": row.underlying,
            "strategy_type": row.strategy_type,
            "asset_badge": _asset_badge(row.strategy_type),
            "status": row.status,
            "quantity": row.quantity,
            "entry_cost": str(row.entry_cost) if row.entry_cost is not None else None,
            "current_mark": str(row.current_mark) if row.current_mark is not None else None,
            "max_loss": str(row.max_loss),
            "defined_risk": row.defined_risk,
            "is_naked": row.is_naked,
        }
        for row in rows
    ]
    if is_htmx(request):
        return render_partial(
            request,
            "_positions_table.html",
            {"positions": payload, "settings": request.app.state.settings},
        )
    return payload


__all__ = ["router"]
