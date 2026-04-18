from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from darth_schwader.domain.enums import StrategyType


class StrategyLeg(BaseModel):
    model_config = ConfigDict(frozen=True)

    occ_symbol: str
    side: Literal["LONG", "SHORT"]
    quantity: int
    strike: Decimal
    expiration: str
    option_type: Literal["CALL", "PUT"]


class StrategySignal(BaseModel):
    model_config = ConfigDict(frozen=True)

    signal_id: str
    strategy_type: StrategyType
    underlying: str
    direction: str
    legs: list[StrategyLeg]
    thesis: str
    confidence: Decimal
    expiration_date: date
    suggested_quantity: int
    suggested_max_loss: Decimal | None = None
    features_snapshot: dict[str, Any] = Field(default_factory=dict)


class AiRunContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    as_of: datetime
    account_snapshot: dict[str, Any]
    positions: list[dict[str, Any]]
    features_by_underlying: dict[str, dict[str, Any]] = Field(default_factory=dict)
    reason: Literal["SCHEDULED_OPEN", "SCHEDULED_PRECLOSE", "IV_SPIKE"]


__all__ = ["AiRunContext", "StrategyLeg", "StrategySignal"]
