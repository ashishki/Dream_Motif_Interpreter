from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.workers.dream_processing import (
    MAX_PROCESSING_ATTEMPTS,
    _claim_jobs,
    _mark_failed_attempt,
    _mark_succeeded,
    _renew_lease,
    _retry_delay,
    _run_claimed_job,
    process_pending_dream_jobs,
)


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
    def __init__(self, *, results=None):
        self._results = list(results or [])
        self.add = MagicMock()
        self.commit = AsyncMock()
        self.executed = []

    async def execute(self, statement):
        self.executed.append(statement)
        if self._results:
            return self._results.pop(0)
        return _Result()


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
        dream_id=uuid4(),
        status=status,
        stage="index",
        attempt_count=attempt_count,
        last_error=None,
        available_at=now - timedelta(minutes=1),
        locked_at=now - timedelta(minutes=20) if status == "running" else None,
        lock_token=uuid4() if status == "running" else None,
        created_at=now - timedelta(hours=1),
        updated_at=now - timedelta(minutes=20),
    )


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
    session.commit.assert_awaited_once()
    assert "FOR UPDATE" in str(session.executed[1])


@pytest.mark.asyncio
async def test_claim_jobs_recovers_stale_running_row() -> None:
    job = _job(status="running", attempt_count=2)
    previous_lock = job.locked_at
    session = _Session(results=[_Result(), _Result(rows=[job])])

    claimed = await _claim_jobs(_Factory(session), job_id=None, limit=10)

    assert claimed == [job]
    assert job.status == "running"
    assert job.attempt_count == 3
    assert job.locked_at > previous_lock
    assert "locked_at" in str(session.executed[1])


@pytest.mark.asyncio
async def test_stale_final_attempt_is_atomically_marked_failed() -> None:
    job = _job(status="running", attempt_count=MAX_PROCESSING_ATTEMPTS)
    session = _Session(results=[_Result(), _Result(rows=[])])

    claimed = await _claim_jobs(_Factory(session), job_id=job.id, limit=1)

    assert claimed == []
    terminal_update = session.executed[0]
    assert "attempt_count" in str(terminal_update)
    params = terminal_update.compile().params.values()
    assert "failed" in params
    assert "processing lease expired after final attempt" in params


@pytest.mark.asyncio
async def test_failed_attempt_is_retryable_with_backoff() -> None:
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
    assert _retry_delay(1) == timedelta(seconds=60)
    assert "lock_token" in str(session.executed[0])


@pytest.mark.asyncio
async def test_final_failed_attempt_becomes_terminal() -> None:
    job = _job(status="running", attempt_count=MAX_PROCESSING_ATTEMPTS)
    session = _Session(results=[_Result(scalar=job.id)])

    updated = await _mark_failed_attempt(
        _Factory(session),
        job.id,
        lock_token=job.lock_token,
        attempt_count=job.attempt_count,
        exc=RuntimeError("provider down"),
    )

    assert updated is True
    params = session.executed[0].compile().params.values()
    assert "failed" in params
    assert "provider down" in params


@pytest.mark.asyncio
async def test_stale_owner_cannot_finalize_reclaimed_job() -> None:
    job = _job(status="running", attempt_count=1)
    session = _Session(results=[_Result(scalar=None)])

    updated = await _mark_succeeded(_Factory(session), job.id, lock_token=job.lock_token)

    assert updated is False
    assert "lock_token" in str(session.executed[0])


@pytest.mark.asyncio
async def test_heartbeat_renews_only_owned_lease() -> None:
    job = _job(status="running", attempt_count=1)
    session = _Session(results=[_Result(scalar=job.id)])

    renewed = await _renew_lease(_Factory(session), job.id, lock_token=job.lock_token)

    assert renewed is True
    assert "lock_token" in str(session.executed[0])


@pytest.mark.asyncio
async def test_run_claimed_job_marks_success_after_facade_pipeline() -> None:
    job = _job(status="running", attempt_count=1)
    facade = SimpleNamespace(process_dream_processing_job=AsyncMock())
    session_factory = _Factory(_Session())

    with (
        patch(
            "app.workers.dream_processing._build_facade",
            return_value=facade,
        ),
        patch(
            "app.workers.dream_processing._mark_succeeded",
            AsyncMock(return_value=True),
        ) as mark_succeeded,
        patch(
            "app.workers.dream_processing._lease_heartbeat",
            AsyncMock(),
        ),
    ):
        succeeded = await _run_claimed_job(
            {"session_factory": session_factory},
            job,
        )

    assert succeeded is True
    facade.process_dream_processing_job.assert_awaited_once_with(job.id, lock_token=job.lock_token)
    mark_succeeded.assert_awaited_once_with(session_factory, job.id, lock_token=job.lock_token)


@pytest.mark.asyncio
async def test_transient_heartbeat_failure_still_attempts_token_cas_finalize() -> None:
    job = _job(status="running", attempt_count=1)
    facade = SimpleNamespace(process_dream_processing_job=AsyncMock())
    session_factory = _Factory(_Session())

    async def _lose_heartbeat(
        _factory,
        _job_id,
        *,
        lock_token,
        stop,
        lease_lost,
    ) -> None:
        del lock_token, stop
        lease_lost.set()

    with (
        patch("app.workers.dream_processing._build_facade", return_value=facade),
        patch(
            "app.workers.dream_processing._mark_succeeded",
            AsyncMock(return_value=True),
        ) as mark_succeeded,
        patch(
            "app.workers.dream_processing._lease_heartbeat",
            new=_lose_heartbeat,
        ),
    ):
        succeeded = await _run_claimed_job(
            {"session_factory": session_factory},
            job,
        )

    assert succeeded is True
    mark_succeeded.assert_awaited_once_with(session_factory, job.id, lock_token=job.lock_token)


@pytest.mark.asyncio
async def test_pending_sweep_continues_after_one_stage_fails() -> None:
    failed_stage = _job()
    successful_stage = _job()
    session_factory = _Factory(_Session())

    with (
        patch(
            "app.workers.dream_processing._claim_jobs",
            AsyncMock(side_effect=[[failed_stage], [successful_stage], []]),
        ) as claim,
        patch(
            "app.workers.dream_processing._run_claimed_job",
            AsyncMock(side_effect=[False, True]),
        ) as run,
    ):
        completed = await process_pending_dream_jobs({"session_factory": session_factory}, limit=4)

    assert completed == 1
    assert claim.await_count == 3
    assert run.await_count == 2


@pytest.mark.asyncio
async def test_hung_stage_times_out_and_releases_for_retry() -> None:
    job = _job(status="running", attempt_count=1)

    async def hang(*_args, **_kwargs) -> None:
        await asyncio.Event().wait()

    facade = SimpleNamespace(process_dream_processing_job=hang)
    session_factory = _Factory(_Session())

    with (
        patch("app.workers.dream_processing._build_facade", return_value=facade),
        patch("app.workers.dream_processing._lease_heartbeat", AsyncMock()),
        patch(
            "app.workers.dream_processing._mark_failed_attempt",
            AsyncMock(return_value=True),
        ) as mark_failed,
        patch(
            "app.workers.dream_processing.PROCESSING_STAGE_TIMEOUT",
            timedelta(milliseconds=1),
        ),
    ):
        succeeded = await _run_claimed_job(
            {"session_factory": session_factory},
            job,
        )

    assert succeeded is False
    assert isinstance(mark_failed.await_args.kwargs["exc"], TimeoutError)
