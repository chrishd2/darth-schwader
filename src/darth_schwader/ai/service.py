from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from darth_schwader.ai.contracts import AiRunContext, StrategySignal
from darth_schwader.ai.llm.selector import LLMStrategySelector
from darth_schwader.ai.strategies import STRATEGY_VALIDATORS
from darth_schwader.config import Settings
from darth_schwader.db.models import Signal
from darth_schwader.quant.features import Features
from darth_schwader.risk.policies import EffectivePolicy
from darth_schwader.risk.sizing import compute_quantity_ceilings


class QuantModule(Protocol):
    def compute(
        self,
        underlying: str,
        chain_snapshot_rows: Sequence[Mapping[str, object]],
        underlying_ohlcv_rows: Sequence[Mapping[str, object]],
    ) -> Features:
        ...


class SignalGenerator:
    def __init__(
        self,
        quant: QuantModule,
        selector: LLMStrategySelector,
        repos: object,
        settings: Settings,
    ) -> None:
        self._quant = quant
        self._selector = selector
        self._repos = repos
        self._settings = settings

    async def run(self, context: AiRunContext) -> list[StrategySignal]:
        features_by_underlying = {
            symbol: self._coerce_features(payload)
            for symbol, payload in context.features_by_underlying.items()
        }
        generated: list[StrategySignal] = []
        for underlying, features in features_by_underlying.items():
            generated.extend(await self._selector.select(features, context))

        policy = EffectivePolicy.from_settings(self._settings)
        valid_signals: list[StrategySignal] = []
        session_factory = self._session_factory()
        async with session_factory() as session:
            for signal in generated:
                validator = STRATEGY_VALIDATORS[signal.strategy_type]
                errors = validator.validate(signal)
                if errors:
                    continue
                max_loss = signal.suggested_max_loss or Decimal(
                    str(signal.features_snapshot.get("per_contract_max_loss", "0"))
                )
                preferred_qty, ceiling_qty = compute_quantity_ceilings(
                    max_loss if max_loss > Decimal("0") else Decimal("1"),
                    Decimal(str(context.account_snapshot["net_liquidation_value"])),
                    policy,
                )
                suggested_qty = max(1, preferred_qty)
                valid_signal = signal.model_copy(
                    update={
                        "suggested_quantity": suggested_qty,
                        "suggested_max_loss": max_loss * Decimal(suggested_qty) if max_loss else None,
                        "features_snapshot": {
                            **signal.features_snapshot,
                            "preferred_quantity": preferred_qty,
                            "ceiling_quantity": ceiling_qty,
                        },
                    }
                )
                session.add(
                    Signal(
                        signal_id=valid_signal.signal_id or f"sig-{uuid4().hex}",
                        source="AI",
                        strategy_type=valid_signal.strategy_type,
                        underlying=valid_signal.underlying,
                        expiration_date=valid_signal.expiration_date,
                        direction=valid_signal.direction,
                        thesis=valid_signal.thesis,
                        confidence=valid_signal.confidence,
                        proposed_payload={
                            "legs": [leg.model_dump(mode="json") for leg in valid_signal.legs],
                            "features_snapshot": valid_signal.features_snapshot,
                        },
                        suggested_quantity=valid_signal.suggested_quantity,
                        suggested_max_loss=valid_signal.suggested_max_loss,
                        preferred_quantity=preferred_qty,
                        ceiling_quantity=ceiling_qty,
                        # Phase 1: strategy validator + v3 sizing gates are the pre-HITL check;
                        # full deterministic risk evaluation runs at submit time in OrderService.
                        status="APPROVED_AWAITING_HITL",
                    )
                )
                valid_signals.append(valid_signal)
            await session.commit()
        return valid_signals

    def _session_factory(self) -> async_sessionmaker[AsyncSession]:
        if isinstance(self._repos, dict):
            return self._repos["session_factory"]
        return self._repos.session_factory

    def _coerce_features(self, payload: dict[str, Any]) -> Features:
        return Features(
            underlying=payload["underlying"],
            iv_rank=Decimal(str(payload["iv_rank"])),
            iv_percentile=Decimal(str(payload["iv_percentile"])),
            term_slope=Decimal(str(payload["term_slope"])),
            skew=Decimal(str(payload["skew"])),
            rv_iv_spread=Decimal(str(payload["rv_iv_spread"])),
            regime=payload["regime"],
            momentum_5d=Decimal(str(payload["momentum_5d"])),
            momentum_20d=Decimal(str(payload["momentum_20d"])),
            as_of=datetime.fromisoformat(str(payload["as_of"]).replace("Z", "+00:00")).astimezone(UTC),
        )


__all__ = ["SignalGenerator"]
