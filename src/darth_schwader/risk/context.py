from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from darth_schwader.config import Settings
from darth_schwader.db.models import (
    Account,
    AccountSnapshot,
    CashLedger,
    Position,
)
from darth_schwader.domain.enums import CashLedgerReason
from darth_schwader.risk.models import RiskContext
from darth_schwader.risk.policies import EffectivePolicy


async def build_risk_context(
    session: AsyncSession,
    settings: Settings,
    *,
    bot_state: str,
    underlying: str | None = None,
    as_of: date | None = None,
    leg_quotes: dict[str, dict[str, Decimal]] | None = None,
) -> RiskContext:
    as_of = as_of or datetime.now(tz=UTC).date()
    policy = await EffectivePolicy.load(session, settings)

    account = await session.scalar(select(Account).limit(1))
    if account is None:
        raise RuntimeError("no account persisted — run account sync before building risk context")

    snapshot = await session.scalar(
        select(AccountSnapshot)
        .where(AccountSnapshot.account_id == account.id)
        .order_by(AccountSnapshot.as_of.desc())
        .limit(1)
    )
    nlv = snapshot.net_liquidation_value if snapshot else Decimal("0")
    day_pnl = snapshot.day_pnl if snapshot and snapshot.day_pnl is not None else Decimal("0")
    week_pnl = snapshot.week_pnl if snapshot and snapshot.week_pnl is not None else Decimal("0")
    day_pnl_pct = (day_pnl / nlv) if nlv > 0 else Decimal("0")
    week_pnl_pct = (week_pnl / nlv) if nlv > 0 else Decimal("0")

    open_positions_count = await session.scalar(
        select(func.count()).select_from(Position).where(Position.status == "OPEN")
    ) or 0

    existing_exposure = Decimal("0")
    if underlying is not None:
        existing_exposure = await session.scalar(
            select(func.coalesce(func.sum(Position.max_loss), 0))
            .where(Position.status == "OPEN", Position.underlying == underlying.upper())
        ) or Decimal("0")

    settled_cash = await session.scalar(
        select(func.coalesce(func.sum(CashLedger.delta_amount), 0))
        .where(
            CashLedger.account_id == account.id,
            CashLedger.settles_on <= as_of,
            CashLedger.reason != CashLedgerReason.COLLATERAL_LOCK,
        )
    ) or Decimal("0")

    return RiskContext(
        policy=policy,
        account_type=account.account_type,
        nlv=Decimal(nlv),
        day_pnl_pct=Decimal(day_pnl_pct),
        week_pnl_pct=Decimal(week_pnl_pct),
        existing_exposure=Decimal(existing_exposure),
        open_positions_count=int(open_positions_count),
        settled_cash=Decimal(settled_cash),
        state=bot_state,
        leg_quotes=leg_quotes or {},
        options_approval_tier=account.options_approval_tier,
    )


__all__ = ["build_risk_context"]
