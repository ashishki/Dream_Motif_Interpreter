import sys

import pytest
from httpx import ASGITransport, AsyncClient


def _load_app():
    sys.modules.pop("app.main", None)

    from app.main import app

    return app


@pytest.mark.anyio
async def test_health_endpoint_returns_200() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_load_app()), base_url="http://testserver"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "index_last_updated": None}


@pytest.mark.anyio
async def test_health_endpoint_no_auth_required() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_load_app()), base_url="http://testserver"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.anyio
async def test_health_endpoint_includes_index_timestamp() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_load_app()), base_url="http://testserver"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200

    payload = response.json()

    assert "index_last_updated" in payload
    assert payload["index_last_updated"] is None
