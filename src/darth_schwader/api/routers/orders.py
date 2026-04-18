from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from darth_schwader.api.deps import get_session
from darth_schwader.db.models import Order

router = APIRouter(tags=["orders"])


@router.get("/orders")
async def orders(session: AsyncSession = Depends(get_session)) -> list[dict[str, object]]:
    rows = await session.scalars(select(Order).order_by(Order.created_at.desc()))
    return [
        {
            "id": row.id,
            "client_order_id": row.client_order_id,
            "status": row.order_status,
            "underlying": row.underlying,
            "quantity": row.quantity,
        }
        for row in rows
    ]


@router.get("/orders/{order_id}")
async def order(order_id: int, session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    row = await session.get(Order, order_id)
    if row is None:
        raise ValueError("order not found")
    return {
        "id": row.id,
        "client_order_id": row.client_order_id,
        "broker_order_id": row.broker_order_id,
        "status": row.order_status,
        "payload": row.order_payload,
    }


__all__ = ["router"]
