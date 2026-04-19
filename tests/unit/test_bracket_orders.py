from __future__ import annotations

from decimal import Decimal

import pytest

from darth_schwader.domain.enums import BracketRole, StrategyType
from darth_schwader.services.bracket_orders import (
    DEFAULT_ATR_STOP_MULT,
    DEFAULT_RISK_REWARD,
    BracketOrderBuilder,
)


def test_long_bracket_computes_atr_stop_and_risk_reward_target() -> None:
    bracket = BracketOrderBuilder().build(
        strategy_type=StrategyType.LONG_EQUITY,
        direction="LONG",
        entry_price=Decimal("100"),
        atr=Decimal("2"),
        equity=Decimal("100000"),
        max_risk_per_trade_pct=Decimal("0.01"),
    )

    assert bracket.entry.role is BracketRole.ENTRY
    assert bracket.stop.role is BracketRole.STOP
    assert bracket.target.role is BracketRole.TARGET
    assert bracket.entry.price == Decimal("100")
    assert bracket.stop.price == Decimal("97.00")
    assert bracket.target.price == Decimal("106.00")
    assert bracket.risk_per_unit == Decimal("3.00")
    assert bracket.reward_per_unit == Decimal("6.00")


def test_short_bracket_reflects_stop_above_and_target_below_entry() -> None:
    bracket = BracketOrderBuilder().build(
        strategy_type=StrategyType.SHORT_FUTURE,
        direction="SHORT",
        entry_price=Decimal("4500"),
        atr=Decimal("20"),
        equity=Decimal("100000"),
        max_risk_per_trade_pct=Decimal("0.01"),
    )

    assert bracket.stop.price == Decimal("4530.00")
    assert bracket.target.price == Decimal("4440.00")


def test_quantity_is_floor_of_risk_budget_divided_by_stop_distance() -> None:
    bracket = BracketOrderBuilder().build(
        strategy_type=StrategyType.LONG_EQUITY,
        direction="LONG",
        entry_price=Decimal("100"),
        atr=Decimal("2"),
        equity=Decimal("10000"),
        max_risk_per_trade_pct=Decimal("0.01"),
    )

    assert bracket.quantity == 33
    assert bracket.total_risk <= Decimal("10000") * Decimal("0.01")


def test_custom_atr_and_risk_reward_multipliers_override_defaults() -> None:
    builder = BracketOrderBuilder(atr_stop_mult=Decimal("2.0"), risk_reward=Decimal("3.0"))
    assert builder.atr_stop_mult != DEFAULT_ATR_STOP_MULT
    assert builder.risk_reward != DEFAULT_RISK_REWARD

    bracket = builder.build(
        strategy_type=StrategyType.LONG_EQUITY,
        direction="LONG",
        entry_price=Decimal("50"),
        atr=Decimal("1"),
        equity=Decimal("20000"),
        max_risk_per_trade_pct=Decimal("0.02"),
    )

    assert bracket.stop.price == Decimal("48.00")
    assert bracket.target.price == Decimal("56.00")


@pytest.mark.parametrize(
    ("entry", "atr", "equity", "pct"),
    [
        (Decimal("0"), Decimal("1"), Decimal("1000"), Decimal("0.01")),
        (Decimal("100"), Decimal("0"), Decimal("1000"), Decimal("0.01")),
        (Decimal("100"), Decimal("1"), Decimal("0"), Decimal("0.01")),
        (Decimal("100"), Decimal("1"), Decimal("1000"), Decimal("0")),
    ],
)
def test_non_positive_inputs_are_rejected(
    entry: Decimal, atr: Decimal, equity: Decimal, pct: Decimal
) -> None:
    with pytest.raises(ValueError):
        BracketOrderBuilder().build(
            strategy_type=StrategyType.LONG_EQUITY,
            direction="LONG",
            entry_price=entry,
            atr=atr,
            equity=equity,
            max_risk_per_trade_pct=pct,
        )


def test_risk_budget_too_small_for_stop_distance_raises() -> None:
    with pytest.raises(ValueError, match="risk budget too small"):
        BracketOrderBuilder().build(
            strategy_type=StrategyType.LONG_EQUITY,
            direction="LONG",
            entry_price=Decimal("100"),
            atr=Decimal("5"),
            equity=Decimal("100"),
            max_risk_per_trade_pct=Decimal("0.01"),
        )


def test_long_bracket_entry_below_stop_offset_rejects_negative_stop() -> None:
    with pytest.raises(ValueError, match="stop/target price is not positive"):
        BracketOrderBuilder().build(
            strategy_type=StrategyType.LONG_EQUITY,
            direction="LONG",
            entry_price=Decimal("1"),
            atr=Decimal("2"),
            equity=Decimal("100000"),
            max_risk_per_trade_pct=Decimal("0.01"),
        )
