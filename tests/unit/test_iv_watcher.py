from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from darth_schwader.market.iv_watcher import IvWatcher


class FakeChainRepository:
    def __init__(self, values: list[Decimal]) -> None:
        self._values = values

    async def recent_implied_vols(self, underlying: str) -> list[Decimal]:
        if underlying == "AAPL":
            return self._values
        return []


class FakeIvEventsRepository:
    def __init__(self) -> None:
        self.rows: list[tuple[str, Decimal]] = []

    async def exists_recent(self, underlying: str, threshold: Decimal) -> bool:
        return False

    async def insert(
        self,
        underlying: str,
        iv_percentile_value: Decimal,
        threshold: Decimal,
        triggered_at: datetime,
    ) -> None:
        self.rows.append((underlying, iv_percentile_value))


@pytest.mark.asyncio
async def test_iv_watcher_inserts_and_emits_when_threshold_crossed(settings) -> None:
    calls: list[tuple[str, Decimal]] = []

    async def _on_spike(symbol: str, percentile: Decimal) -> None:
        calls.append((symbol, percentile))

    repo = FakeIvEventsRepository()
    watcher = IvWatcher(
        session_factory=object(),
        settings=settings,
        chain_repo=FakeChainRepository([Decimal("0.10"), Decimal("0.20"), Decimal("0.30")]),
        iv_events_repo=repo,
        on_spike=_on_spike,
    )
    triggered = await watcher.scan()
    assert triggered == ["AAPL"]
    assert repo.rows[0][0] == "AAPL"
    assert calls[0][0] == "AAPL"


@pytest.mark.asyncio
async def test_iv_watcher_is_noop_when_threshold_not_crossed(settings) -> None:
    settings.iv_spike_threshold_pct = Decimal("99")
    repo = FakeIvEventsRepository()
    watcher = IvWatcher(
        session_factory=object(),
        settings=settings,
        chain_repo=FakeChainRepository([Decimal("0.10"), Decimal("0.11"), Decimal("0.12")]),
        iv_events_repo=repo,
        on_spike=None,
    )
    triggered = await watcher.scan()
    assert triggered == []
    assert repo.rows == []
