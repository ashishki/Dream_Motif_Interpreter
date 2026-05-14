from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

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
        fetch_document_metadata=lambda document_id=None: GoogleDocMetadata(
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
        fetch_document_metadata=lambda document_id=None: GoogleDocMetadata(
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
            "app.services.auto_sync.ingest_document",
            new=AsyncMock(return_value=1),
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
    assert state.last_added_count == 1
    assert state.last_sync_stage == "done"
    assert state.last_sync_error is None


@pytest.mark.asyncio
async def test_run_auto_sync_once_fetches_metadata_for_requested_doc_id() -> None:
    redis = _FakeRedis()
    fetch_metadata = Mock(
        return_value=GoogleDocMetadata(
            document_id="doc-extra",
            title="Extra Journal",
            updated_at=None,
            version="2",
            head_revision_id="rev-extra",
        )
    )
    gdocs_client = SimpleNamespace(fetch_document_metadata=fetch_metadata)

    with (
        patch(
            "app.services.auto_sync.get_settings",
            return_value=SimpleNamespace(AUTO_SYNC_ENABLED=True),
        ),
        patch("app.services.auto_sync.ingest_document", new=AsyncMock(return_value=0)),
    ):
        await run_auto_sync_once(
            redis_client=redis,
            session_factory=object(),
            gdocs_client=gdocs_client,
            doc_id="doc-extra",
        )

    fetch_metadata.assert_called_once_with("doc-extra")
    state = await read_auto_sync_state(redis, "doc-extra")
    assert state.last_seen_marker == "rev-extra"


@pytest.mark.asyncio
async def test_run_auto_sync_once_self_heals_stale_running_state() -> None:
    redis = _FakeRedis()
    old_started_at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    await write_auto_sync_state(
        redis,
        "doc-123",
        AutoSyncState(
            last_seen_marker="rev-2",
            last_sync_started_at=old_started_at,
            last_sync_status="running",
        ),
    )
    gdocs_client = SimpleNamespace(
        fetch_document_metadata=lambda document_id=None: GoogleDocMetadata(
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
            return_value=SimpleNamespace(
                AUTO_SYNC_ENABLED=True,
                AUTO_SYNC_INTERVAL_SECONDS=300,
            ),
        ),
        patch(
            "app.services.auto_sync.ingest_document",
            new=AsyncMock(return_value=1),
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
    assert state.last_sync_started_at is None
    assert state.last_sync_status == "synced"


@pytest.mark.asyncio
async def test_run_auto_sync_once_treats_five_minute_running_state_as_stale() -> None:
    redis = _FakeRedis()
    old_started_at = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
    await write_auto_sync_state(
        redis,
        "doc-123",
        AutoSyncState(
            last_seen_marker="rev-2",
            last_sync_started_at=old_started_at,
            last_sync_status="running",
        ),
    )
    gdocs_client = SimpleNamespace(
        fetch_document_metadata=lambda document_id=None: GoogleDocMetadata(
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
            return_value=SimpleNamespace(
                AUTO_SYNC_ENABLED=True,
                AUTO_SYNC_INTERVAL_SECONDS=60,
            ),
        ),
        patch(
            "app.services.auto_sync.ingest_document",
            new=AsyncMock(return_value=0),
        ) as mock_ingest,
    ):
        result = await run_auto_sync_once(
            redis_client=redis,
            session_factory=object(),
            gdocs_client=gdocs_client,
        )

    assert result.action == "synced"
    mock_ingest.assert_awaited_once()


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
            gdocs_client=SimpleNamespace(fetch_document_metadata=lambda document_id=None: None),
        )

    assert result.action == "disabled"
