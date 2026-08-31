from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.api.dreams import SyncJobState
from app.services.auto_sync import read_auto_sync_state
from app.services.gdocs_client import GoogleDocMetadata
from app.workers.sync_jobs import (
    MAX_SYNC_ATTEMPTS,
    _claim_jobs,
    _mark_failed_attempt,
    _run_claimed_job,
    create_manual_sync_job,
    read_manual_sync_job_state,
)


class _Redis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, **_: object) -> bool:
        self.values[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def delete(self, key: str) -> int:
        return 1 if self.values.pop(key, None) is not None else 0


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _Result:
    def __init__(self, *, rows=None, scalar=None):
        self._rows = list(rows or [])
        self._scalar = scalar

    def scalars(self):
        return _Scalars(self._rows)

    def scalar_one_or_none(self):
        return self._scalar


class _Session:
    def __init__(self, *, results=None, get_result=None):
        self._results = list(results or [])
        self._get_result = get_result
        self.add = MagicMock()
        self.commit = AsyncMock()
        self.executed = []

    async def execute(self, statement):
        self.executed.append(statement)
        if self._results:
            return self._results.pop(0)
        return _Result()

    async def get(self, _model, _pk):
        return self._get_result


class _Context:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        del exc_type, exc, tb
        return False


class _Factory:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return _Context(self._session)


def _job(*, status: str = "pending", attempt_count: int = 0):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid4(),
        doc_id="doc-123",
        status=status,
        attempt_count=attempt_count,
        last_error=None,
        new_entries=None,
        notify_chat_id=12345,
        available_at=now - timedelta(minutes=1),
        locked_at=now - timedelta(minutes=20) if status == "running" else None,
        lock_token=uuid4() if status == "running" else None,
        started_at=None,
        finished_at=None,
        created_at=now - timedelta(hours=1),
        updated_at=now - timedelta(minutes=20),
    )


@pytest.mark.asyncio
async def test_create_manual_sync_job_commits_before_public_redis_status() -> None:
    redis = _Redis()
    session = _Session()
    job_id = uuid4()

    await create_manual_sync_job(
        session_factory=_Factory(session),
        redis_client=redis,
        job_id=job_id,
        doc_id="doc-123",
        chat_id=12345,
    )

    stored_job = session.add.call_args.args[0]
    assert stored_job.id == job_id
    assert stored_job.doc_id == "doc-123"
    assert stored_job.status == "pending"
    assert stored_job.notify_chat_id == 12345
    session.commit.assert_awaited_once()
    assert json.loads(redis.values[f"sync_job:{job_id}"]) == {
        "status": "queued",
        "new_entries": None,
    }


@pytest.mark.asyncio
async def test_read_manual_sync_job_state_maps_internal_statuses() -> None:
    job = _job(status="succeeded")
    job.new_entries = 2
    state = await read_manual_sync_job_state(_Factory(_Session(get_result=job)), job.id)

    assert state == SyncJobState(status="done", new_entries=2)


@pytest.mark.asyncio
async def test_claim_jobs_moves_pending_row_to_running() -> None:
    job = _job()
    session = _Session(results=[_Result(), _Result(rows=[job])])

    claimed = await _claim_jobs(_Factory(session), job_id=job.id, limit=1)

    assert claimed == [job]
    assert job.status == "running"
    assert job.attempt_count == 1
    assert job.locked_at is not None
    assert job.lock_token is not None
    assert job.started_at is not None
    assert "FOR UPDATE" in str(session.executed[1])
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_stale_final_sync_attempt_is_marked_terminal() -> None:
    job = _job(status="running", attempt_count=MAX_SYNC_ATTEMPTS)
    session = _Session(results=[_Result(), _Result(rows=[])])

    claimed = await _claim_jobs(_Factory(session), job_id=job.id, limit=1)

    assert claimed == []
    params = session.executed[0].compile().params.values()
    assert "failed" in params
    assert "manual sync lease expired after final attempt" in params


@pytest.mark.asyncio
async def test_failed_attempt_is_retryable_with_sanitized_error() -> None:
    job = _job(status="running", attempt_count=1)
    session = _Session(results=[_Result(scalar=job.id)])

    updated = await _mark_failed_attempt(
        _Factory(session),
        job.id,
        lock_token=job.lock_token,
        attempt_count=job.attempt_count,
        exc=RuntimeError("token=secret"),
    )

    assert updated is True
    params = session.executed[0].compile().params.values()
    assert "retryable" in params
    assert "token=<redacted>" in params
    assert "lock_token" in str(session.executed[0])


@pytest.mark.asyncio
async def test_run_claimed_job_marks_success_and_preserves_notification() -> None:
    redis = _Redis()
    job = _job(status="running", attempt_count=1)
    gdocs_client = SimpleNamespace(
        fetch_document_metadata=lambda document_id=None: GoogleDocMetadata(
            document_id=document_id or "doc-123",
            title="Dream Journal",
            updated_at=None,
            version="2",
            head_revision_id="rev-2",
        )
    )
    session_factory = object()

    with (
        patch("app.workers.sync_jobs.ingest_document", new=AsyncMock(return_value=3)) as ingest,
        patch("app.workers.sync_jobs._lease_heartbeat", new=AsyncMock()),
        patch("app.workers.sync_jobs._mark_succeeded", new=AsyncMock(return_value=True)) as mark,
    ):
        succeeded = await _run_claimed_job(
            {"redis": redis, "session_factory": session_factory, "gdocs_client": gdocs_client},
            job,
        )

    assert succeeded is True
    ingest.assert_awaited_once()
    mark.assert_awaited_once_with(
        session_factory,
        job.id,
        lock_token=job.lock_token,
        new_entries=3,
    )
    assert redis.values[f"sync_notify:{job.id}"] == "12345"
    assert json.loads(redis.values[f"sync_job:{job.id}"]) == {
        "status": "done",
        "new_entries": 3,
    }
    state = await read_auto_sync_state(redis, "doc-123")
    assert state.last_seen_marker == "rev-2"
    assert state.last_sync_status == "synced"
    assert state.last_added_count == 3


@pytest.mark.asyncio
async def test_run_claimed_job_treats_reported_ingest_failure_as_terminal() -> None:
    redis = _Redis()
    job = _job(status="running", attempt_count=1)
    redis.values[f"sync_job:{job.id}"] = json.dumps({"status": "failed", "new_entries": None})
    session_factory = object()

    with (
        patch("app.workers.sync_jobs.ingest_document", new=AsyncMock(return_value=0)),
        patch("app.workers.sync_jobs._lease_heartbeat", new=AsyncMock()),
        patch(
            "app.workers.sync_jobs._mark_failed_terminal",
            new=AsyncMock(return_value=True),
        ) as mark_failed,
        patch("app.workers.sync_jobs._mark_succeeded", new=AsyncMock()) as mark_succeeded,
    ):
        succeeded = await _run_claimed_job(
            {"redis": redis, "session_factory": session_factory, "gdocs_client": SimpleNamespace()},
            job,
        )

    assert succeeded is False
    mark_failed.assert_awaited_once_with(
        session_factory,
        job.id,
        lock_token=job.lock_token,
        error="manual sync worker reported failure",
    )
    mark_succeeded.assert_not_awaited()
    assert json.loads(redis.values[f"sync_job:{job.id}"]) == {
        "status": "failed",
        "new_entries": None,
    }
    state = await read_auto_sync_state(redis, "doc-123")
    assert state.last_sync_status == "failed"