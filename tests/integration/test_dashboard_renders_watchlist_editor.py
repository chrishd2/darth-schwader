from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_dashboard_includes_heatmap_and_watchlist(make_app) -> None:
    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/dashboard")

    assert response.status_code == 200
    body = response.text
    assert 'id="heatmap-heading"' in body
    assert 'id="heatmap-body"' in body
    assert 'hx-get="/api/v1/setup-heatmap"' in body
    assert 'id="watchlist-heading"' in body
    assert 'hx-post="/api/v1/watchlist"' in body
