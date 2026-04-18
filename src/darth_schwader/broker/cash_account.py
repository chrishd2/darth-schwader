from __future__ import annotations

from datetime import date
from decimal import Decimal

from darth_schwader.db.repositories.cash_ledger import CashLedgerRepository


class CashAccountGuard:
    def __init__(self, ledger_repo: CashLedgerRepository) -> None:
        self._ledger_repo = ledger_repo

    async def available_settled(self, account_id: int, as_of_date: date) -> Decimal:
        return await self._ledger_repo.settled_cash_as_of(account_id, as_of_date)

    async def can_lock(self, account_id: int, amount: Decimal, as_of_date: date) -> bool:
        if amount < Decimal("0"):
            raise ValueError("amount must be non-negative")
        available = await self.available_settled(account_id, as_of_date)
        return available >= amount

    async def lock_for_order(
        self,
        account_id: int,
        amount: Decimal,
        settles_on: date,
        *,
        related_order_id: int | None = None,
        notes: str | None = None,
    ) -> Decimal:
        if not await self.can_lock(account_id, amount, settles_on):
            raise ValueError("insufficient settled cash to lock collateral")
        await self._ledger_repo.lock_collateral(
            account_id,
            amount,
            settles_on,
            related_order_id=related_order_id,
            notes=notes,
        )
        return await self.available_settled(account_id, settles_on)

    async def release_for_cancel(
        self,
        account_id: int,
        amount: Decimal,
        settles_on: date,
        *,
        related_order_id: int | None = None,
        notes: str | None = None,
    ) -> Decimal:
        await self._ledger_repo.release_collateral(
            account_id,
            amount,
            settles_on,
            related_order_id=related_order_id,
            notes=notes,
        )
        return await self.available_settled(account_id, settles_on)


__all__ = ["CashAccountGuard"]
