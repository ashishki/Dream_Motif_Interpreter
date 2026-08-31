from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock

import pytest

from app.api.dreams import LocalAsyncJobEnqueuer, RedisSyncBackend, SyncJobState


class _Redis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.closed = False

    async def set(self, key: str, value: str, **_: object) -> bool:
        self.values[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_enqueue_persists_manual_sync_job_and_wakes_supervisor(monkeypatch) -> None:
    redis = _Redis()
    enqueuer = LocalAsyncJobEnqueuer(redis_client=redis, session_factory=object())  # type: ignore[arg-type]
    job_id = uuid.uuid4()
    persisted: list[dict[str, object]] = []
    wake_events: list[asyncio.Event] = []

    async def create_manual_sync_job(**kwargs) -> None:
        persisted.append(kwargs)

    def start(**_: object):
        wake = asyncio.Event()
        wake_events.append(wake)
        enqueuer._wake = wake

    monkeypatch.setattr(
        "app.workers.sync_jobs.create_manual_sync_job",
        create_manual_sync_job,
    )
    monkeypatch.setattr(enqueuer, "start", start)

    await enqueuer.enqueue_ingest(job_id=job_id, doc_id="doc-1", chat_id=12345)

    assert persisted == [
        {
            "session_factory": enqueuer._session_factory,
            "redis_client": redis,
            "job_id": job_id,
            "doc_id": "doc-1",
            "chat_id": 12345,
        }
    ]
    assert wake_events[0].is_set()


@pytest.mark.asyncio
async def test_shutdown_cancels_supervisor_and_closes_redis(monkeypatch) -> None:
    redis = _Redis()
    enqueuer = LocalAsyncJobEnqueuer(redis_client=redis, session_factory=object())  # type: ignore[arg-type]
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def never_finishes(**_: object) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(enqueuer, "_run_supervisor", never_finishes)

    enqueuer.start()
    task = enqueuer._task
    assert task is not None
    await started.wait()

    await enqueuer.shutdown(timeout_seconds=0.0)

    assert task.cancelled()
    assert cancelled.is_set()
    assert enqueuer._task is None
    assert redis.closed is True

    with pytest.raises(RuntimeError, match="shutting down"):
        await enqueuer.enqueue_ingest(job_id=uuid.uuid4(), doc_id="doc-2")


@pytest.mark.asyncio
async def test_get_ingest_status_reads_durable_job_state(monkeypatch) -> None:
    redis = _Redis()
    enqueuer = LocalAsyncJobEnqueuer(redis_client=redis, session_factory=object())  # type: ignore[arg-type]
    job_id = uuid.uuid4()
    reader = AsyncMock(return_value=SyncJobState(status="done", new_entries=2))
    monkeypatch.setattr("app.workers.sync_jobs.read_manual_sync_job_state", reader)

    state = await enqueuer.get_ingest_status(job_id)

    assert state == SyncJobState(status="done", new_entries=2)
    reader.assert_awaited_once_with(enqueuer._session_factory, job_id)


@pytest.mark.asyncio
async def test_sync_backend_falls_back_to_durable_status_when_redis_ttl_is_missing() -> None:
    job_id = uuid.uuid4()
    enqueuer = AsyncMock()
    enqueuer.get_ingest_status.return_value = SyncJobState(status="done", new_entries=2)
    backend = RedisSyncBackend(redis_client=_Redis(), job_enqueuer=enqueuer, doc_id="doc-1")

    state = await backend.get_status(job_id)

    assert state == SyncJobState(status="done", new_entries=2)
    enqueuer.get_ingest_status.assert_awaited_once_with(job_id)


@pytest.mark.asyncio
async def test_sync_backend_prefers_durable_status_over_stale_redis_value() -> None:
    job_id = uuid.uuid4()
    redis = _Redis()
    redis.values[f"sync_job:{job_id}"] = json.dumps({"status": "failed", "new_entries": None})
    enqueuer = AsyncMock()
    enqueuer.get_ingest_status.return_value = SyncJobState(status="queued", new_entries=None)
    backend = RedisSyncBackend(redis_client=redis, job_enqueuer=enqueuer, doc_id="doc-1")

    state = await backend.get_status(job_id)

    assert state == SyncJobState(status="queued", new_entries=None)
    enqueuer.get_ingest_status.assert_awaited_once_with(job_id)