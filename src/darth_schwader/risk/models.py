from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from darth_schwader.risk.policies import EffectivePolicy


@dataclass(frozen=True, slots=True)
class RuleResult:
    passed: bool
    reason_code: str
    reason_text: str
    evidence: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RiskDecision:
    decision: Literal["APPROVE", "REJECT"]
    reason_code: str
    reason_text: str
    rule_results: tuple[RuleResult, ...]
    warnings: tuple[RuleResult, ...]
    max_loss: Decimal
    position_size_limit: Decimal
    approved_quantity: int
    correlation_bucket: str | None
    preferred_quantity: int
    ceiling_quantity: int


@dataclass(frozen=True, slots=True)
class RiskContext:
    policy: EffectivePolicy
    account_type: str
    nlv: Decimal
    day_pnl_pct: Decimal
    week_pnl_pct: Decimal
    existing_exposure: Decimal
    open_positions_count: int
    settled_cash: Decimal
    state: str
    leg_quotes: dict[str, dict[str, Decimal]]
    options_approval_tier: int


__all__ = ["RiskContext", "RiskDecision", "RuleResult"]
