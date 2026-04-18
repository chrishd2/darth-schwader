from __future__ import annotations

import pytest

from darth_schwader.services.order_service import _instruction_for


@pytest.mark.parametrize(
    ("asset_type", "side", "expected"),
    [
        ("OPTION", "LONG", "BUY_TO_OPEN"),
        ("OPTION", "SHORT", "SELL_TO_OPEN"),
        ("EQUITY", "LONG", "BUY"),
        ("EQUITY", "SHORT", "SELL_TO_OPEN"),
        ("FUTURE", "LONG", "BUY"),
        ("FUTURE", "SHORT", "SELL_TO_OPEN"),
    ],
)
def test_instruction_for_maps_every_asset_side_combination(
    asset_type: str, side: str, expected: str
) -> None:
    assert _instruction_for(asset_type, side) == expected


def test_instruction_for_rejects_unknown_asset_type() -> None:
    with pytest.raises(ValueError, match="unsupported asset_type/side combination"):
        _instruction_for("CRYPTO", "LONG")


def test_instruction_for_rejects_unknown_side() -> None:
    with pytest.raises(ValueError, match="unsupported asset_type/side combination"):
        _instruction_for("OPTION", "FLAT")
