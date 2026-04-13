from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient


def _load_app():
    sys.modules.pop("app.main", None)

    from app.main import app

    return app


@pytest.mark.anyio
async def test_health_returns_ok_with_fresh_index(monkeypatch: pytest.MonkeyPatch) -> None:
    fresh_timestamp = datetime.now(timezone.utc) - timedelta(hours=1)

    async def _fake_fetch() -> datetime:
        return fresh_timestamp

    monkeypatch.setattr(
        "app.api.health._fetch_index_last_updated",
        _fake_fetch,
    )

    async with AsyncClient(
        transport=ASGITransport(app=_load_app()), base_url="http://testserver"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "index_last_updated": fresh_timestamp.isoformat(),
    }


@pytest.mark.anyio
async def test_health_returns_503_on_stale_index(monkeypatch: pytest.MonkeyPatch) -> None:
    stale_timestamp = datetime.now(timezone.utc) - timedelta(hours=30)

    async def _fake_fetch() -> datetime:
        return stale_timestamp

    monkeypatch.setattr(
        "app.api.health._fetch_index_last_updated",
        _fake_fetch,
    )

    async with AsyncClient(
        transport=ASGITransport(app=_load_app()), base_url="http://testserver"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "index_last_updated": stale_timestamp.isoformat(),
    }


@pytest.mark.anyio
async def test_health_endpoint_no_auth_required(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_fetch() -> None:
        return None

    monkeypatch.setattr(
        "app.api.health._fetch_index_last_updated",
        _fake_fetch,
    )

    async with AsyncClient(
        transport=ASGITransport(app=_load_app()), base_url="http://testserver"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
