from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from darth_schwader.db.models import IvSpikeEvent


class IvEventsRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def exists_recent(
        self,
        underlying: str,
        threshold: Decimal,
        window: timedelta = timedelta(hours=4),
    ) -> bool:
        cutoff = datetime.now(tz=UTC) - window
        async with self._session_factory() as session:
            row = await session.scalar(
                select(IvSpikeEvent.id)
                .where(
                    IvSpikeEvent.underlying == underlying.upper(),
                    IvSpikeEvent.triggered_at >= cutoff,
                )
                .limit(1)
            )
            return row is not None

    async def insert(
        self,
        underlying: str,
        iv_percentile_value: Decimal,
        threshold: Decimal,
        triggered_at: datetime,
    ) -> None:
        async with self._session_factory() as session:
            session.add(
                IvSpikeEvent(
                    underlying=underlying.upper(),
                    iv_percentile=iv_percentile_value,
                    triggered_at=triggered_at,
                    threshold_used=threshold,
                )
            )
            await session.commit()


__all__ = ["IvEventsRepository"]
