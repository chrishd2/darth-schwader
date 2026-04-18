from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from darth_schwader.db.models import WatchlistEntry
from darth_schwader.domain.asset_types import AssetType


class WatchlistRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_all(self, *, active_only: bool = False) -> list[WatchlistEntry]:
        stmt = select(WatchlistEntry).order_by(WatchlistEntry.symbol, WatchlistEntry.asset_type)
        if active_only:
            stmt = stmt.where(WatchlistEntry.active.is_(True))
        async with self._session_factory() as session:
            return list((await session.scalars(stmt)).all())

    async def get(self, entry_id: int) -> WatchlistEntry | None:
        async with self._session_factory() as session:
            return await session.get(WatchlistEntry, entry_id)

    async def find(self, symbol: str, asset_type: AssetType) -> WatchlistEntry | None:
        stmt = select(WatchlistEntry).where(
            WatchlistEntry.symbol == symbol.upper(),
            WatchlistEntry.asset_type == asset_type,
        )
        async with self._session_factory() as session:
            result: WatchlistEntry | None = await session.scalar(stmt)
            return result

    async def create(
        self,
        *,
        symbol: str,
        asset_type: AssetType,
        strategies: Sequence[str],
        active: bool = True,
        notes: str | None = None,
    ) -> WatchlistEntry:
        async with self._session_factory() as session:
            entry = WatchlistEntry(
                symbol=symbol.upper(),
                asset_type=asset_type,
                strategies=list(strategies),
                active=active,
                notes=notes,
            )
            session.add(entry)
            await session.commit()
            await session.refresh(entry)
            return entry

    async def update(
        self,
        entry_id: int,
        *,
        strategies: Sequence[str] | None = None,
        active: bool | None = None,
        notes: str | None = None,
    ) -> WatchlistEntry | None:
        async with self._session_factory() as session:
            entry = await session.get(WatchlistEntry, entry_id)
            if entry is None:
                return None
            if strategies is not None:
                entry.strategies = list(strategies)
            if active is not None:
                entry.active = active
            if notes is not None:
                entry.notes = notes
            await session.commit()
            await session.refresh(entry)
            return entry

    async def delete(self, entry_id: int) -> bool:
        async with self._session_factory() as session:
            entry = await session.get(WatchlistEntry, entry_id)
            if entry is None:
                return False
            await session.delete(entry)
            await session.commit()
            return True


__all__ = ["WatchlistRepository"]
