from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from darth_schwader.db.models import AuditLog, Order, Signal, SignalStatus


async def reconcile_end_of_day(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        await _expire_stale_pending_signals(session)
        await _release_cancelled_collateral_markers(session)
        await session.commit()


async def _expire_stale_pending_signals(session: AsyncSession) -> None:
    stale = await session.scalars(select(Signal).where(Signal.status == SignalStatus.PENDING))
    now = datetime.now(tz=UTC)
    for signal in stale:
        signal.status = SignalStatus.EXPIRED
        session.add(
            AuditLog(
                event_type="SIGNAL_EXPIRED",
                entity_type="signal",
                entity_id=str(signal.id),
                correlation_id=signal.signal_id,
                payload_json={"expired_at": now.isoformat()},
            )
        )


async def _release_cancelled_collateral_markers(session: AsyncSession) -> None:
    cancelled_orders = await session.scalars(
        select(Order).where(Order.order_status.in_(["CANCELLED", "REJECTED"]))  # type: ignore[arg-type]
    )
    for order in cancelled_orders:
        session.add(
            AuditLog(
                event_type="COLLATERAL_REVIEWED",
                entity_type="order",
                entity_id=str(order.id),
                correlation_id=order.client_order_id,
                payload_json={"status": order.order_status},
            )
        )


__all__ = ["reconcile_end_of_day"]
