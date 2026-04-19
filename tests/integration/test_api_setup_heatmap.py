from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from darth_schwader.domain.asset_types import AssetType
from darth_schwader.market.indicator_engine import IndicatorSet
from darth_schwader.market.setup_detector import BULL_PULLBACK, SetupScore
from darth_schwader.services.setup_heatmap import HeatmapRow


def _indicator_set() -> IndicatorSet:
    d = Decimal
    return IndicatorSet(
        symbol="AAPL",
        as_of=datetime.now(tz=UTC),
        close=d("100"),
        rsi14=d("55"),
        ema8=d("101"),
        ema21=d("99"),
        atr14=d("2"),
        adx14=d("25"),
        bb_width=d("4"),
        bb_width_pct=d("0.6"),
        vwap=d("100"),
        vwap_distance=d("0"),
    )


class _FakeService:
    def __init__(self, rows: Sequence[HeatmapRow]) -> None:
        self._rows = list(rows)

    async def snapshot(self) -> list[HeatmapRow]:
        return list(self._rows)


@pytest.mark.asyncio
async def test_setup_heatmap_json_response(make_app) -> None:
    app = make_app()
    row = HeatmapRow(
        symbol="AAPL",
        asset_type=AssetType.EQUITY,
        indicators=_indicator_set(),
        setup=SetupScore(
            symbol="AAPL",
            scores={BULL_PULLBACK: Decimal("75")},
            best_setup=BULL_PULLBACK,
            best_score=Decimal("75"),
        ),
        error=None,
    )
    app.state.setup_heatmap_service = _FakeService([row])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/v1/setup-heatmap")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["symbol"] == "AAPL"
    assert payload[0]["asset_type"] == "EQUITY"
    assert payload[0]["best_setup"] == BULL_PULLBACK
    assert payload[0]["best_score"] == "75"
    assert "rsi14" in payload[0]["indicators"]


@pytest.mark.asyncio
async def test_setup_heatmap_htmx_returns_html_partial(make_app) -> None:
    app = make_app()
    row = HeatmapRow(
        symbol="SPY",
        asset_type=AssetType.ETF,
        indicators=None,
        setup=None,
        error="bar fetch failed: boom",
    )
    app.state.setup_heatmap_service = _FakeService([row])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/api/v1/setup-heatmap",
            headers={"HX-Request": "true"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    assert "SPY" in body
    assert "bar fetch failed" in body
