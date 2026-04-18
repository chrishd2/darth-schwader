from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from darth_schwader.data_sources.polygon.client import PolygonClient
from darth_schwader.data_sources.polygon.mappers import map_option_chain_rows
from darth_schwader.db.models import ChainSnapshot


class PolygonIngestion:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: PolygonClient,
        watchlist: Sequence[str] | None = None,
        default_days: int = 365,
    ) -> None:
        self._session_factory = session_factory
        self._client = client
        self._watchlist = tuple(symbol.upper() for symbol in (watchlist or ()))
        self._default_days = default_days

    async def backfill(self, underlying: str, days: int) -> int:
        inserted = 0
        end_date = datetime.now(tz=UTC).date()
        start_date = end_date - timedelta(days=max(days - 1, 0))
        cursor = start_date

        while cursor <= end_date:
            contracts = await self._client.get_option_chain(
                underlying.upper(),
                expiration_from=cursor,
                expiration_to=cursor + timedelta(days=90),
            )
            rows = map_option_chain_rows(underlying.upper(), contracts, as_of=cursor)
            async with self._session_factory() as session:
                inserted += await self._persist_rows(session, rows)
                await session.commit()
            cursor += timedelta(days=1)
        return inserted

    async def backfill_watchlist(self, days: int | None = None) -> dict[str, int]:
        span = days or self._default_days
        counts: dict[str, int] = {}
        for underlying in self._watchlist:
            counts[underlying] = await self.backfill(underlying, span)
        return counts

    async def _persist_rows(
        self,
        session: AsyncSession,
        rows: list[dict[str, object]],
    ) -> int:
        inserted = 0
        for row in rows:
            existing = await session.scalar(
                select(ChainSnapshot.id)
                .where(
                    ChainSnapshot.underlying == row["underlying"],
                    ChainSnapshot.quote_time == row["quote_time"],
                    ChainSnapshot.expiration_date == row["expiration_date"],
                    ChainSnapshot.option_type == row["option_type"],
                    ChainSnapshot.strike == row["strike"],
                    ChainSnapshot.data_source == row["data_source"],
                )
                .limit(1)
            )
            if existing is not None:
                continue
            session.add(ChainSnapshot(**row))
            inserted += 1
        return inserted


__all__ = ["PolygonIngestion"]
