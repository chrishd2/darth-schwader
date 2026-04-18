from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from darth_schwader.db.models import CashLedger


async def update_settlement(session: AsyncSession, account_id: int, as_of: date | None = None) -> Decimal:
    settlement_date = as_of or datetime.now(tz=UTC).date()
    stmt = select(func.coalesce(func.sum(CashLedger.delta_amount), 0)).where(
        CashLedger.account_id == account_id,
        CashLedger.settles_on <= settlement_date,
    )
    value = await session.scalar(stmt)
    return Decimal(str(value or 0))


__all__ = ["update_settlement"]
