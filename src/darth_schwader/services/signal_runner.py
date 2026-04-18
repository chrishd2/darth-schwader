from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from darth_schwader.ai.contracts import AiRunContext
from darth_schwader.ai.service import SignalGenerator
from darth_schwader.db.models import AccountSnapshot, Position
from darth_schwader.logging import get_logger

_logger = get_logger(__name__)

RunReason = Literal["SCHEDULED_OPEN", "SCHEDULED_PRECLOSE", "IV_SPIKE", "MANUAL"]

FeatureProvider = Callable[
    [Sequence[str], AsyncSession], Awaitable[dict[str, dict[str, Any]]]
]


class SignalRunner:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        signal_generator: SignalGenerator,
        feature_provider: FeatureProvider,
        watchlist: Sequence[str],
    ) -> None:
        self._session_factory = session_factory
        self._signal_generator = signal_generator
        self._feature_provider = feature_provider
        self._watchlist = tuple(watchlist)

    async def run(self, reason: RunReason) -> int:
        async with self._session_factory() as session:
            account_snapshot = await self._load_latest_account_snapshot(session)
            positions = await self._load_open_positions(session)
            features_by_underlying = await self._feature_provider(
                self._watchlist, session
            )

        if not features_by_underlying:
            _logger.info("signal_runner_no_features", reason=reason)
            return 0

        context = AiRunContext(
            as_of=datetime.now(tz=UTC),
            account_snapshot=account_snapshot,
            positions=positions,
            features_by_underlying=features_by_underlying,
            reason=reason,
        )
        signals = await self._signal_generator.run(context)
        _logger.info(
            "signal_runner_complete",
            reason=reason,
            underlyings=len(features_by_underlying),
            signals=len(signals),
        )
        return len(signals)

    async def _load_latest_account_snapshot(
        self, session: AsyncSession
    ) -> dict[str, Any]:
        row = await session.scalar(
            select(AccountSnapshot).order_by(AccountSnapshot.as_of.desc()).limit(1)
        )
        if row is None:
            return {"net_liquidation_value": "0"}
        return {
            "net_liquidation_value": str(row.net_liquidation_value),
            "cash_balance": str(row.cash_balance),
            "buying_power": (
                str(row.buying_power) if row.buying_power is not None else None
            ),
        }

    async def _load_open_positions(
        self, session: AsyncSession
    ) -> list[dict[str, Any]]:
        rows = await session.scalars(
            select(Position).where(Position.status == "OPEN")
        )
        return [
            {
                "id": row.id,
                "underlying": row.underlying,
                "strategy_type": str(row.strategy_type),
                "quantity": row.quantity,
                "entry_cost": (
                    str(row.entry_cost) if row.entry_cost is not None else None
                ),
                "current_mark": (
                    str(row.current_mark) if row.current_mark is not None else None
                ),
            }
            for row in rows
        ]


async def empty_feature_provider(
    watchlist: Sequence[str],
    session: AsyncSession,
) -> dict[str, dict[str, Any]]:
    del watchlist, session
    return {}


def sample_feature_payload(underlying: str, as_of: datetime | None = None) -> dict[str, Any]:
    moment = as_of or datetime.now(tz=UTC)
    return {
        "underlying": underlying,
        "iv_rank": Decimal("50"),
        "iv_percentile": Decimal("50"),
        "term_slope": Decimal("0"),
        "skew": Decimal("0"),
        "rv_iv_spread": Decimal("0"),
        "regime": "NEUTRAL",
        "momentum_5d": Decimal("0"),
        "momentum_20d": Decimal("0"),
        "as_of": moment.isoformat(),
    }


__all__ = [
    "FeatureProvider",
    "RunReason",
    "SignalRunner",
    "empty_feature_provider",
    "sample_feature_payload",
]
