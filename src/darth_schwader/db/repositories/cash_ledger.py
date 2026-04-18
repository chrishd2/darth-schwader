from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from darth_schwader.db.models import CashLedger
from darth_schwader.domain.enums import CashLedgerReason

_ZERO = Decimal("0")


class CashLedgerRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def append_delta(
        self,
        account_id: int,
        delta: Decimal,
        reason: CashLedgerReason,
        settles_on: date,
        *,
        related_order_id: int | None = None,
        related_fill_id: int | None = None,
        notes: str | None = None,
        occurred_at: datetime | None = None,
    ) -> CashLedger:
        entry = CashLedger(
            account_id=account_id,
            occurred_at=occurred_at or datetime.now(tz=UTC),
            settles_on=settles_on,
            delta_amount=delta,
            reason=reason,
            related_order_id=related_order_id,
            related_fill_id=related_fill_id,
            notes=notes,
        )
        async with self._session_factory() as session:
            session.add(entry)
            await session.commit()
            await session.refresh(entry)
            return entry

    async def settled_cash_as_of(self, account_id: int, as_of_date: date) -> Decimal:
        async with self._session_factory() as session:
            stmt = select(func.coalesce(func.sum(CashLedger.delta_amount), 0)).where(
                CashLedger.account_id == account_id,
                CashLedger.settles_on <= as_of_date,
            )
            value = await session.scalar(stmt)
            return Decimal(str(value or 0))

    async def unsettled_cash_as_of(self, account_id: int, as_of_date: date) -> Decimal:
        async with self._session_factory() as session:
            stmt = select(func.coalesce(func.sum(CashLedger.delta_amount), 0)).where(
                CashLedger.account_id == account_id,
                CashLedger.settles_on > as_of_date,
            )
            value = await session.scalar(stmt)
            return Decimal(str(value or 0))

    async def lock_collateral(
        self,
        account_id: int,
        amount: Decimal,
        settles_on: date,
        *,
        related_order_id: int | None = None,
        notes: str | None = None,
    ) -> CashLedger:
        if amount < _ZERO:
            raise ValueError("collateral amount must be non-negative")
        return await self.append_delta(
            account_id=account_id,
            delta=-amount,
            reason=CashLedgerReason.COLLATERAL_LOCK,
            settles_on=settles_on,
            related_order_id=related_order_id,
            notes=notes,
        )

    async def release_collateral(
        self,
        account_id: int,
        amount: Decimal,
        settles_on: date,
        *,
        related_order_id: int | None = None,
        notes: str | None = None,
    ) -> CashLedger:
        if amount < _ZERO:
            raise ValueError("collateral amount must be non-negative")
        return await self.append_delta(
            account_id=account_id,
            delta=amount,
            reason=CashLedgerReason.COLLATERAL_RELEASE,
            settles_on=settles_on,
            related_order_id=related_order_id,
            notes=notes,
        )

    async def running_available_cash(self, account_id: int, as_of_date: date) -> Decimal:
        settled = await self.settled_cash_as_of(account_id, as_of_date)
        unsettled = await self.unsettled_cash_as_of(account_id, as_of_date)
        return settled + min(unsettled, _ZERO)


__all__ = ["CashLedgerRepository"]
