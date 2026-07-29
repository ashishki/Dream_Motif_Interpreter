from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.health import IndexHealthSnapshot


def _load_app():
    sys.modules.pop("app.main", None)
    from app.shared.database import get_session_factory

    get_session_factory.cache_clear()

    from app.main import app

    return app


@pytest.mark.anyio
async def test_health_returns_ok_with_fresh_index(monkeypatch: pytest.MonkeyPatch) -> None:
    fresh_timestamp = datetime.now(timezone.utc) - timedelta(hours=1)

    async def _fake_fetch() -> IndexHealthSnapshot:
        return IndexHealthSnapshot(
            index_last_updated=fresh_timestamp,
            unindexed_dreams=0,
            unindexed_notes=0,
        )

    monkeypatch.setattr(
        "app.api.health._fetch_index_health_snapshot",
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
        "unindexed_dreams": 0,
        "unindexed_notes": 0,
    }


@pytest.mark.anyio
async def test_health_returns_ok_with_old_complete_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale_timestamp = datetime.now(timezone.utc) - timedelta(hours=30)

    async def _fake_fetch() -> IndexHealthSnapshot:
        return IndexHealthSnapshot(
            index_last_updated=stale_timestamp,
            unindexed_dreams=0,
            unindexed_notes=0,
        )

    monkeypatch.setattr(
        "app.api.health._fetch_index_health_snapshot",
        _fake_fetch,
    )

    async with AsyncClient(
        transport=ASGITransport(app=_load_app()), base_url="http://testserver"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "index_last_updated": stale_timestamp.isoformat(),
        "unindexed_dreams": 0,
        "unindexed_notes": 0,
    }


@pytest.mark.anyio
async def test_health_returns_503_on_index_backlog(monkeypatch: pytest.MonkeyPatch) -> None:
    index_timestamp = datetime.now(timezone.utc) - timedelta(minutes=5)

    async def _fake_fetch() -> IndexHealthSnapshot:
        return IndexHealthSnapshot(
            index_last_updated=index_timestamp,
            unindexed_dreams=2,
            unindexed_notes=1,
        )

    monkeypatch.setattr(
        "app.api.health._fetch_index_health_snapshot",
        _fake_fetch,
    )

    async with AsyncClient(
        transport=ASGITransport(app=_load_app()), base_url="http://testserver"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "index_last_updated": index_timestamp.isoformat(),
        "unindexed_dreams": 2,
        "unindexed_notes": 1,
    }


@pytest.mark.anyio
async def test_health_endpoint_no_auth_required(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_fetch() -> IndexHealthSnapshot:
        return IndexHealthSnapshot(
            index_last_updated=None,
            unindexed_dreams=0,
            unindexed_notes=0,
        )

    monkeypatch.setattr(
        "app.api.health._fetch_index_health_snapshot",
        _fake_fetch,
    )

    async with AsyncClient(
        transport=ASGITransport(app=_load_app()), base_url="http://testserver"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.anyio
async def test_health_returns_503_when_index_status_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_fetch() -> None:
        return None

    monkeypatch.setattr(
        "app.api.health._fetch_index_health_snapshot",
        _fake_fetch,
    )

    async with AsyncClient(
        transport=ASGITransport(app=_load_app()), base_url="http://testserver"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
