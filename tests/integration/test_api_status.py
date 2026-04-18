from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_api_health_returns_ok(api_client) -> None:
    response = await api_client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
