from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from darth_schwader.db.models import AuditLog, Signal
from darth_schwader.domain.enums import SignalStatus, StrategyType
from darth_schwader.services.reconciliation import reconcile_end_of_day


@pytest.mark.asyncio
async def test_reconciliation_expires_stale_pending_signal(session, session_factory) -> None:
    signal = Signal(
        signal_id="sig-stale",
        source="AI",
        strategy_type=StrategyType.VERTICAL_SPREAD,
        underlying="AAPL",
        expiration_date=(datetime.now(tz=UTC) + timedelta(days=30)).date(),
        direction="bullish",
        thesis="stale",
        confidence=Decimal("0.4"),
        proposed_payload={"legs": [], "features_snapshot": {}},
        suggested_quantity=1,
        suggested_max_loss=Decimal("100"),
        preferred_quantity=1,
        ceiling_quantity=2,
        status=SignalStatus.PENDING,
    )
    session.add(signal)
    await session.commit()
    await session.refresh(signal)

    await reconcile_end_of_day(session_factory)

    async with session_factory() as verify:
        refreshed = await verify.get(Signal, signal.id)
        audit = await verify.scalar(select(AuditLog).where(AuditLog.entity_id == str(signal.id)))

    assert refreshed is not None
    assert refreshed.status == SignalStatus.EXPIRED
    assert audit is not None
    assert audit.event_type == "SIGNAL_EXPIRED"
