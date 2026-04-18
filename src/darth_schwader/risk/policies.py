from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from darth_schwader.config import Settings
from darth_schwader.db.models import RiskPolicyOverride


@dataclass(frozen=True, slots=True)
class EffectivePolicy:
    max_risk_per_trade_pct: Decimal
    preferred_max_risk_per_trade_pct: Decimal
    max_daily_drawdown_pct: Decimal
    max_weekly_drawdown_pct: Decimal
    max_positions: int
    max_underlying_allocation_pct: Decimal
    min_dte_days: int
    max_dte_days: int
    allow_naked: bool
    iv_spike_threshold_pct: Decimal
    options_approval_tier: int

    @classmethod
    def from_settings(cls, settings: Settings) -> EffectivePolicy:
        return cls(
            max_risk_per_trade_pct=Decimal(settings.max_risk_per_trade_pct),
            preferred_max_risk_per_trade_pct=Decimal(settings.preferred_max_risk_per_trade_pct),
            max_daily_drawdown_pct=Decimal(settings.max_daily_drawdown_pct),
            max_weekly_drawdown_pct=Decimal(settings.max_weekly_drawdown_pct),
            max_positions=settings.max_positions,
            max_underlying_allocation_pct=Decimal(settings.max_underlying_allocation_pct),
            min_dte_days=settings.min_dte_days,
            max_dte_days=settings.max_dte_days,
            allow_naked=settings.allow_naked,
            iv_spike_threshold_pct=Decimal(settings.iv_spike_threshold_pct),
            options_approval_tier=settings.options_approval_tier,
        )

    @classmethod
    async def load(cls, session: AsyncSession, settings: Settings) -> EffectivePolicy:
        policy = cls.from_settings(settings)
        rows = await session.scalars(select(RiskPolicyOverride))
        overrides = {row.key: row.value for row in rows}

        def _bool(key: str, default: bool) -> bool:
            return str(overrides.get(key, default)).lower() in {"1", "true", "yes", "on"}

        def _int(key: str, default: int) -> int:
            return int(overrides.get(key, default))

        def _dec(key: str, default: Decimal) -> Decimal:
            return Decimal(str(overrides.get(key, default)))

        return cls(
            max_risk_per_trade_pct=_dec("max_risk_per_trade_pct", policy.max_risk_per_trade_pct),
            preferred_max_risk_per_trade_pct=_dec(
                "preferred_max_risk_per_trade_pct",
                policy.preferred_max_risk_per_trade_pct,
            ),
            max_daily_drawdown_pct=_dec("max_daily_drawdown_pct", policy.max_daily_drawdown_pct),
            max_weekly_drawdown_pct=_dec("max_weekly_drawdown_pct", policy.max_weekly_drawdown_pct),
            max_positions=_int("max_positions", policy.max_positions),
            max_underlying_allocation_pct=_dec(
                "max_underlying_allocation_pct",
                policy.max_underlying_allocation_pct,
            ),
            min_dte_days=_int("min_dte_days", policy.min_dte_days),
            max_dte_days=_int("max_dte_days", policy.max_dte_days),
            allow_naked=_bool("allow_naked", policy.allow_naked),
            iv_spike_threshold_pct=_dec("iv_spike_threshold_pct", policy.iv_spike_threshold_pct),
            options_approval_tier=_int("options_approval_tier", policy.options_approval_tier),
        )


__all__ = ["EffectivePolicy"]
