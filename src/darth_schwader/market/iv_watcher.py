from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from darth_schwader.config import Settings
from darth_schwader.market.universe import WATCHLIST
from darth_schwader.quant.iv_metrics import iv_percentile


class ChainRepository(Protocol):
    async def recent_implied_vols(self, underlying: str) -> Sequence[Decimal]:
        ...


class IvEventsRepository(Protocol):
    async def exists_recent(self, underlying: str, threshold: Decimal) -> bool:
        ...

    async def insert(
        self,
        underlying: str,
        iv_percentile_value: Decimal,
        threshold: Decimal,
        triggered_at: datetime,
    ) -> None:
        ...


@dataclass(slots=True)
class IvWatcher:
    session_factory: object
    settings: Settings
    chain_repo: ChainRepository
    iv_events_repo: IvEventsRepository
    on_spike: Callable[[str, Decimal], Awaitable[None]] | None = None

    async def scan(self) -> list[str]:
        triggered: list[str] = []
        threshold = Decimal(self.settings.iv_spike_threshold_pct)
        for underlying in WATCHLIST:
            ivs = tuple(await self.chain_repo.recent_implied_vols(underlying))
            if not ivs:
                continue
            percentile = iv_percentile(ivs[-1], ivs)
            if percentile < threshold:
                continue
            if await self.iv_events_repo.exists_recent(underlying, threshold):
                continue
            await self.iv_events_repo.insert(
                underlying=underlying,
                iv_percentile_value=percentile,
                threshold=threshold,
                triggered_at=datetime.now(tz=UTC),
            )
            if self.on_spike is not None:
                await self.on_spike(underlying, percentile)
            triggered.append(underlying)
        return triggered


__all__ = ["IvWatcher"]
