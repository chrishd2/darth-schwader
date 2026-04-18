from __future__ import annotations

from decimal import Decimal

import pytest

from darth_schwader.quant.iv_metrics import (
    iv_percentile,
    iv_rank,
    realized_vs_implied,
    skew_25_delta,
    term_structure_slope,
)


def test_iv_rank_and_percentile_handle_extremes() -> None:
    series = [Decimal("0.10"), Decimal("0.20"), Decimal("0.30")]
    assert iv_rank(Decimal("0.30"), series) == Decimal("100")
    assert iv_percentile(Decimal("0.20"), series) == Decimal("66.66666666666666666666666667")


def test_iv_metrics_reject_empty_or_degenerate_inputs() -> None:
    with pytest.raises(ValueError):
        iv_rank(Decimal("0.20"), [])
    with pytest.raises(ValueError):
        iv_rank(Decimal("0.20"), [Decimal("0.20")])
    with pytest.raises(ValueError):
        term_structure_slope(Decimal("0"), Decimal("0.2"))
    with pytest.raises(ValueError):
        skew_25_delta(Decimal("0"), Decimal("0.2"))
    with pytest.raises(ValueError):
        realized_vs_implied(Decimal("0"), Decimal("0.2"))
