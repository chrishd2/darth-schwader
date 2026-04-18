from __future__ import annotations

from decimal import Decimal

import pytest

from darth_schwader.risk.policies import EffectivePolicy
from darth_schwader.risk.sizing import compute_quantity_ceilings


def _policy() -> EffectivePolicy:
    return EffectivePolicy(
        max_risk_per_trade_pct=Decimal("0.25"),
        preferred_max_risk_per_trade_pct=Decimal("0.05"),
        max_daily_drawdown_pct=Decimal("0.05"),
        max_weekly_drawdown_pct=Decimal("0.10"),
        max_positions=5,
        max_underlying_allocation_pct=Decimal("0.20"),
        min_dte_days=14,
        max_dte_days=60,
        allow_naked=False,
        iv_spike_threshold_pct=Decimal("90"),
        options_approval_tier=2,
    )


def test_compute_quantity_ceilings_rejects_zero_or_negative_loss() -> None:
    with pytest.raises(ValueError):
        compute_quantity_ceilings(Decimal("0"), Decimal("10000"), _policy())


def test_compute_quantity_ceilings_returns_zero_preferred_when_contract_is_too_large() -> None:
    preferred, ceiling = compute_quantity_ceilings(Decimal("800"), Decimal("10000"), _policy())
    assert preferred == 0
    assert ceiling == 3


def test_compute_quantity_ceilings_floors_budgets() -> None:
    preferred, ceiling = compute_quantity_ceilings(Decimal("375"), Decimal("10000"), _policy())
    assert preferred == 1
    assert ceiling == 6
