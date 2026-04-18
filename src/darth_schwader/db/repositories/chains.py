from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from darth_schwader.db.models import ChainSnapshot


class ChainRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def recent_implied_vols(self, underlying: str, limit: int = 252) -> Sequence[Decimal]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(ChainSnapshot.implied_volatility)
                .where(
                    ChainSnapshot.underlying == underlying.upper(),
                    ChainSnapshot.implied_volatility.is_not(None),
                )
                .order_by(ChainSnapshot.quote_time.desc())
                .limit(limit)
            )
            return tuple(value for value in rows if value is not None)


__all__ = ["ChainRepository"]
