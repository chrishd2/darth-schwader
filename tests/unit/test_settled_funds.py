from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from darth_schwader.db.models import Account
from darth_schwader.db.repositories.cash_ledger import CashLedgerRepository
from darth_schwader.domain.enums import AccountType, CashLedgerReason
from darth_schwader.services.settled_funds import update_settlement


@pytest.mark.asyncio
async def test_update_settlement_excludes_unsettled_cash(session, session_factory) -> None:
    account = Account(
        broker_account_id="acct-1",
        account_type=AccountType.CASH,
        options_approval_tier=2,
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)

    repo = CashLedgerRepository(session_factory)
    today = datetime.now(tz=UTC).date()
    tomorrow = today + timedelta(days=1)
    await repo.append_delta(account.id, Decimal("1000"), CashLedgerReason.MANUAL_ADJUSTMENT, today)
    await repo.append_delta(account.id, Decimal("250"), CashLedgerReason.MANUAL_ADJUSTMENT, tomorrow)

    async with session_factory() as verify:
        settled = await update_settlement(verify, account.id, today)
    assert settled == Decimal("1000")


@pytest.mark.asyncio
async def test_collateral_lock_and_release_balance_to_zero(session, session_factory) -> None:
    account = Account(
        broker_account_id="acct-2",
        account_type=AccountType.CASH,
        options_approval_tier=2,
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)

    repo = CashLedgerRepository(session_factory)
    today = datetime.now(tz=UTC).date()
    await repo.append_delta(account.id, Decimal("5000"), CashLedgerReason.MANUAL_ADJUSTMENT, today)
    await repo.lock_collateral(account.id, Decimal("750"), today)
    await repo.release_collateral(account.id, Decimal("750"), today)

    assert await repo.settled_cash_as_of(account.id, today) == Decimal("5000")
