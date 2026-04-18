from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from darth_schwader.api.deps import get_session
from darth_schwader.api.templating import is_htmx, render_partial
from darth_schwader.db.models import Account, CashLedger
from darth_schwader.domain.enums import CashLedgerReason

router = APIRouter(tags=["cash-ledger"])


@router.get("/cash-ledger", response_model=None)
async def cash_ledger(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str] | HTMLResponse:
    account = await session.scalar(select(Account).limit(1))
    if account is None:
        payload = {"settled": "0", "unsettled": "0", "locked": "0", "available": "0"}
        if is_htmx(request):
            return render_partial(request, "_cash_ledger.html", payload)
        return payload

    today = datetime.now(tz=UTC).date()

    settled = await session.scalar(
        select(func.coalesce(func.sum(CashLedger.delta_amount), 0))
        .where(
            CashLedger.account_id == account.id,
            CashLedger.settles_on <= today,
            CashLedger.reason != CashLedgerReason.COLLATERAL_LOCK,
        )
    ) or Decimal("0")

    unsettled = await session.scalar(
        select(func.coalesce(func.sum(CashLedger.delta_amount), 0))
        .where(
            CashLedger.account_id == account.id,
            CashLedger.settles_on > today,
            CashLedger.reason != CashLedgerReason.COLLATERAL_LOCK,
        )
    ) or Decimal("0")

    lock_sum = await session.scalar(
        select(func.coalesce(func.sum(CashLedger.delta_amount), 0))
        .where(
            CashLedger.account_id == account.id,
            CashLedger.reason.in_(
                [CashLedgerReason.COLLATERAL_LOCK, CashLedgerReason.COLLATERAL_RELEASE]
            ),
        )
    ) or Decimal("0")
    locked = max(Decimal("0"), -Decimal(lock_sum))

    available = Decimal(settled) - locked
    payload = {
        "settled": str(Decimal(settled)),
        "unsettled": str(Decimal(unsettled)),
        "locked": str(locked),
        "available": str(available),
    }
    if is_htmx(request):
        return render_partial(request, "_cash_ledger.html", payload)
    return payload


__all__ = ["router"]
