from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR

from darth_schwader.risk.policies import EffectivePolicy


def compute_quantity_ceilings(
    per_contract_max_loss: Decimal,
    nlv: Decimal,
    policy: EffectivePolicy,
) -> tuple[int, int]:
    if per_contract_max_loss <= Decimal("0"):
        raise ValueError("per_contract_max_loss must be greater than zero")
    if nlv <= Decimal("0"):
        raise ValueError("nlv must be greater than zero")

    preferred_budget = policy.preferred_max_risk_per_trade_pct * nlv
    ceiling_budget = policy.max_risk_per_trade_pct * nlv
    preferred_qty = int((preferred_budget / per_contract_max_loss).to_integral_value(rounding=ROUND_FLOOR))
    ceiling_qty = int((ceiling_budget / per_contract_max_loss).to_integral_value(rounding=ROUND_FLOOR))
    return max(preferred_qty, 0), max(ceiling_qty, 0)


__all__ = ["compute_quantity_ceilings"]
