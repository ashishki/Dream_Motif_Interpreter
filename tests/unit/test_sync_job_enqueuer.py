from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from app.api.dreams import LocalAsyncJobEnqueuer


class _Redis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.closed = False

    async def set(self, key: str, value: str, **_: object) -> bool:
        self.values[key] = value
        return True

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_shutdown_cancels_overdue_sync_tasks_and_closes_redis(monkeypatch) -> None:
    redis = _Redis()
    enqueuer = LocalAsyncJobEnqueuer(redis_client=redis, session_factory=object())  # type: ignore[arg-type]
    started = asyncio.Event()

    async def never_finishes(**_: object) -> None:
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(enqueuer, "_run_ingest_job", never_finishes)

    await enqueuer.enqueue_ingest(job_id=uuid.uuid4(), doc_id="doc-1")
    await started.wait()
    task = next(iter(enqueuer._tasks))

    await enqueuer.shutdown(timeout_seconds=0.0)

    assert task.cancelled()
    assert not enqueuer._tasks
    assert redis.closed is True
    states = [
        json.loads(value)["status"]
        for key, value in redis.values.items()
        if key.startswith("sync_job:")
    ]
    assert states == ["failed"]

    with pytest.raises(RuntimeError, match="shutting down"):
        await enqueuer.enqueue_ingest(job_id=uuid.uuid4(), doc_id="doc-2")
