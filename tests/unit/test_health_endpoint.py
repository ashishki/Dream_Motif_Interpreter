from __future__ import annotations

import pytest
from fastapi import Response

import app.api.health as health_module


@pytest.mark.asyncio
async def test_health_returns_503_when_storage_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _raise_storage_error() -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(health_module, "_fetch_index_last_updated", _raise_storage_error)
    response = Response()

    payload = await health_module.health(response)

    assert response.status_code == 503
    assert payload.status == "degraded"
    assert payload.index_last_updated is None


@pytest.mark.asyncio
async def test_health_allows_an_empty_but_available_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _empty_index() -> None:
        return None

    monkeypatch.setattr(health_module, "_fetch_index_last_updated", _empty_index)
    response = Response()

    payload = await health_module.health(response)

    assert response.status_code == 200
    assert payload.status == "ok"
    assert payload.index_last_updated is None
