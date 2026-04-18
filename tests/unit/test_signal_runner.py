from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from darth_schwader.ai.contracts import AiRunContext, StrategySignal
from darth_schwader.db.models import Account, AccountSnapshot, Position
from darth_schwader.domain.enums import AccountType, CollateralKind, StrategyType
from darth_schwader.services.signal_runner import (
    SignalRunner,
    empty_feature_provider,
    sample_feature_payload,
)


class _RecordingGenerator:
    def __init__(self) -> None:
        self.calls: list[AiRunContext] = []

    async def run(self, context: AiRunContext) -> list[StrategySignal]:
        self.calls.append(context)
        return []


async def _seed_account(session: AsyncSession) -> Account:
    account = Account(
        broker_account_id="123456789",
        account_type=AccountType.MARGIN,
        options_approval_tier=2,
    )
    session.add(account)
    await session.flush()
    return account


@pytest.mark.asyncio
async def test_signal_runner_returns_zero_when_feature_provider_empty(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as setup_session:
        await _seed_account(setup_session)
        await setup_session.commit()

    generator = _RecordingGenerator()
    runner = SignalRunner(
        session_factory=session_factory,
        signal_generator=generator,
        feature_provider=empty_feature_provider,
        watchlist=("AAPL",),
    )

    count = await runner.run("MANUAL")

    assert count == 0
    assert generator.calls == []


@pytest.mark.asyncio
async def test_signal_runner_builds_context_with_features(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as setup_session:
        account = await _seed_account(setup_session)
        setup_session.add(
            AccountSnapshot(
                account_id=account.id,
                as_of=datetime(2026, 4, 18, 15, 0, tzinfo=UTC),
                net_liquidation_value=Decimal("100000"),
                cash_balance=Decimal("25000"),
                buying_power=Decimal("200000"),
                raw_payload={"source": "test"},
            )
        )
        setup_session.add(
            Position(
                account_id=account.id,
                underlying="AAPL",
                strategy_type=StrategyType.VERTICAL_SPREAD,
                status="OPEN",
                opened_at=datetime(2026, 4, 10, tzinfo=UTC),
                quantity=1,
                entry_cost=Decimal("-120"),
                current_mark=Decimal("-80"),
                max_loss=Decimal("380"),
                defined_risk=True,
                is_naked=False,
                collateral_amount=Decimal("500"),
                collateral_kind=CollateralKind.CASH,
                legs_json=[{"occ_symbol": "AAPL260620P00180000"}],
            )
        )
        await setup_session.commit()

    async def provider(
        watchlist: Sequence[str], session: AsyncSession
    ) -> dict[str, dict[str, Any]]:
        del session
        return {sym: sample_feature_payload(sym) for sym in watchlist}

    generator = _RecordingGenerator()
    runner = SignalRunner(
        session_factory=session_factory,
        signal_generator=generator,
        feature_provider=provider,
        watchlist=("AAPL",),
    )

    count = await runner.run("SCHEDULED_OPEN")

    assert count == 0
    assert len(generator.calls) == 1
    ctx = generator.calls[0]
    assert ctx.reason == "SCHEDULED_OPEN"
    assert ctx.features_by_underlying.keys() == {"AAPL"}
    assert ctx.account_snapshot["net_liquidation_value"] == "100000.0000"
    assert ctx.account_snapshot["cash_balance"] == "25000.0000"
    assert len(ctx.positions) == 1
    assert ctx.positions[0]["underlying"] == "AAPL"
    assert ctx.positions[0]["strategy_type"] == "VERTICAL_SPREAD"


@pytest.mark.asyncio
async def test_signal_runner_uses_zero_snapshot_when_db_empty(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def provider(
        watchlist: Sequence[str], session: AsyncSession
    ) -> dict[str, dict[str, Any]]:
        del session
        return {sym: sample_feature_payload(sym) for sym in watchlist}

    generator = _RecordingGenerator()
    runner = SignalRunner(
        session_factory=session_factory,
        signal_generator=generator,
        feature_provider=provider,
        watchlist=("AAPL",),
    )

    await runner.run("MANUAL")

    assert generator.calls[0].account_snapshot == {"net_liquidation_value": "0"}
    assert generator.calls[0].positions == []


def test_sample_feature_payload_returns_neutral_regime() -> None:
    payload = sample_feature_payload("AAPL", datetime(2026, 4, 18, tzinfo=UTC))
    assert payload["regime"] == "NEUTRAL"
    assert payload["iv_rank"] == Decimal("50")
    assert payload["momentum_5d"] == Decimal("0")
    assert payload["as_of"] == "2026-04-18T00:00:00+00:00"


@pytest.mark.asyncio
async def test_empty_feature_provider_returns_empty_dict(
    session: AsyncSession,
) -> None:
    result = await empty_feature_provider(("AAPL",), session)
    assert result == {}
