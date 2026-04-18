from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from darth_schwader.api.deps import get_session
from darth_schwader.db.models import Position

router = APIRouter(tags=["positions"])


@router.get("/positions")
async def positions(session: AsyncSession = Depends(get_session)) -> list[dict[str, object]]:
    rows = await session.scalars(select(Position).order_by(Position.updated_at.desc()))
    return [
        {
            "id": row.id,
            "underlying": row.underlying,
            "strategy_type": row.strategy_type,
            "status": row.status,
            "quantity": row.quantity,
            "max_loss": str(row.max_loss),
        }
        for row in rows
    ]


__all__ = ["router"]
