from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.auto_sync import (
    AutoSyncState,
    read_auto_sync_state,
    run_auto_sync_once,
    write_auto_sync_state,
)
from app.services.gdocs_client import GoogleDocMetadata


class _FakeRedis:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._values.get(key)

    async def set(self, key: str, value: str) -> bool:
        self._values[key] = value
        return True


@pytest.mark.asyncio
async def test_run_auto_sync_once_skips_ingest_when_marker_is_unchanged() -> None:
    redis = _FakeRedis()
    await write_auto_sync_state(
        redis,
        "doc-123",
        AutoSyncState(
            last_seen_marker="rev-1",
            last_checked_at="2026-04-21T10:00:00+00:00",
            last_synced_at="2026-04-21T09:00:00+00:00",
            last_sync_job_id="job-1",
            last_sync_status="synced",
        ),
    )
    gdocs_client = SimpleNamespace(
        fetch_document_metadata=lambda: GoogleDocMetadata(
            document_id="doc-123",
            title="Dream Journal",
            updated_at=None,
            version="1",
            head_revision_id="rev-1",
        )
    )

    with (
        patch(
            "app.services.auto_sync.get_settings",
            return_value=SimpleNamespace(AUTO_SYNC_ENABLED=True),
        ),
        patch("app.services.auto_sync.ingest_document", new=AsyncMock()) as mock_ingest,
    ):
        result = await run_auto_sync_once(
            redis_client=redis,
            session_factory=object(),
            gdocs_client=gdocs_client,
        )

    assert result.action == "no_change"
    mock_ingest.assert_not_awaited()
    state = await read_auto_sync_state(redis, "doc-123")
    assert state.last_seen_marker == "rev-1"
    assert state.last_sync_status == "synced"


@pytest.mark.asyncio
async def test_run_auto_sync_once_runs_ingest_when_marker_changes() -> None:
    redis = _FakeRedis()
    await write_auto_sync_state(
        redis,
        "doc-123",
        AutoSyncState(last_seen_marker="rev-1", last_sync_status="synced"),
    )
    gdocs_client = SimpleNamespace(
        fetch_document_metadata=lambda: GoogleDocMetadata(
            document_id="doc-123",
            title="Dream Journal",
            updated_at=None,
            version="2",
            head_revision_id="rev-2",
        )
    )

    with (
        patch(
            "app.services.auto_sync.get_settings",
            return_value=SimpleNamespace(AUTO_SYNC_ENABLED=True),
        ),
        patch(
            "app.services.auto_sync.ingest_document", new=AsyncMock(return_value=1)
        ) as mock_ingest,
    ):
        result = await run_auto_sync_once(
            redis_client=redis,
            session_factory=object(),
            gdocs_client=gdocs_client,
        )

    assert result.action == "synced"
    mock_ingest.assert_awaited_once()
    state = await read_auto_sync_state(redis, "doc-123")
    assert state.last_seen_marker == "rev-2"
    assert state.last_sync_status == "synced"
    assert state.last_sync_job_id is not None


@pytest.mark.asyncio
async def test_run_auto_sync_once_returns_disabled_when_feature_flag_off() -> None:
    redis = _FakeRedis()

    with patch(
        "app.services.auto_sync.get_settings",
        return_value=SimpleNamespace(AUTO_SYNC_ENABLED=False),
    ):
        result = await run_auto_sync_once(
            redis_client=redis,
            session_factory=object(),
            gdocs_client=SimpleNamespace(fetch_document_metadata=lambda: None),
        )

    assert result.action == "disabled"
