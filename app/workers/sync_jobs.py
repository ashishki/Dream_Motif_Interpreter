from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.dreams import (
    SyncJobState,
    read_sync_job_state,
    set_sync_notify,
    write_sync_job_state,
)
from app.models.processing import ManualSyncJob
from app.services.gdocs_client import GDocsClient
from app.shared.tracing import get_logger, get_tracer
from app.workers.ingest import ingest_document

logger = get_logger(__name__)

MAX_SYNC_ATTEMPTS = 5
STALE_SYNC_JOB_AFTER = timedelta(minutes=10)
SYNC_LEASE_HEARTBEAT_INTERVAL = timedelta(minutes=3)
SYNC_JOB_TIMEOUT = timedelta(minutes=20)
MAX_RETRY_DELAY = timedelta(hours=1)


async def create_manual_sync_job(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Any,
    job_id: uuid.UUID,
    doc_id: str,
    chat_id: int | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        session.add(
            ManualSyncJob(
                id=job_id,
                doc_id=doc_id,
                status="pending",
                attempt_count=0,
                last_error=None,
                new_entries=None,
                notify_chat_id=chat_id,
                available_at=now,
                locked_at=None,
                lock_token=None,
                started_at=None,
                finished_at=None,
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()

    await _write_public_job_state(redis_client, job_id, SyncJobState(status="queued"))


async def read_manual_sync_job_state(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
) -> SyncJobState | None:
    async with session_factory() as session:
        job = await session.get(ManualSyncJob, job_id)
    if job is None:
        return None
    return SyncJobState(status=_public_status(job.status), new_entries=job.new_entries)


async def process_manual_sync_job(
    ctx: dict[str, Any],
    *,
    job_id: uuid.UUID,
) -> bool:
    session_factory: async_sessionmaker[AsyncSession] = ctx["session_factory"]
    claimed = await _claim_jobs(session_factory, job_id=job_id, limit=1)
    if not claimed:
        return False
    return await _run_claimed_job(ctx, claimed[0])


async def process_pending_manual_sync_jobs(
    ctx: dict[str, Any],
    *,
    limit: int = 20,
) -> int:
    session_factory: async_sessionmaker[AsyncSession] = ctx["session_factory"]
    completed = 0
    for _ in range(max(1, min(limit, 100))):
        claimed = await _claim_jobs(session_factory, job_id=None, limit=1)
        if not claimed:
            break
        if await _run_claimed_job(ctx, claimed[0]):
            completed += 1
    return completed


async def _claim_jobs(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    job_id: uuid.UUID | None,
    limit: int,
) -> list[ManualSyncJob]:
    del limit
    now = datetime.now(timezone.utc)
    stale_before = now - STALE_SYNC_JOB_AFTER
    eligible = or_(
        and_(
            ManualSyncJob.status.in_(("pending", "retryable")),
            ManualSyncJob.available_at <= now,
            ManualSyncJob.attempt_count < MAX_SYNC_ATTEMPTS,
        ),
        and_(
            ManualSyncJob.status == "running",
            or_(
                ManualSyncJob.locked_at.is_(None),
                ManualSyncJob.locked_at < stale_before,
            ),
            ManualSyncJob.attempt_count < MAX_SYNC_ATTEMPTS,
        ),
    )
    stmt = (
        select(ManualSyncJob)
        .where(eligible)
        .order_by(ManualSyncJob.available_at.asc(), ManualSyncJob.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job_id is not None:
        stmt = stmt.where(ManualSyncJob.id == job_id)

    async with session_factory() as session:
        with get_tracer(__name__).start_as_current_span("manual_sync.claim"):
            terminal_stale_conditions = [
                ManualSyncJob.status == "running",
                or_(
                    ManualSyncJob.locked_at.is_(None),
                    ManualSyncJob.locked_at < stale_before,
                ),
                ManualSyncJob.attempt_count >= MAX_SYNC_ATTEMPTS,
            ]
            if job_id is not None:
                terminal_stale_conditions.append(ManualSyncJob.id == job_id)
            await session.execute(
                update(ManualSyncJob)
                .where(*terminal_stale_conditions)
                .values(
                    status="failed",
                    last_error="manual sync lease expired after final attempt",
                    locked_at=None,
                    lock_token=None,
                    finished_at=now,
                    updated_at=now,
                )
            )
            result = await session.execute(stmt)
            jobs = list(result.scalars().all())
            for job in jobs:
                job.lock_token = uuid.uuid4()
                job.status = "running"
                job.attempt_count = (job.attempt_count or 0) + 1
                job.last_error = None
                job.locked_at = now
                job.started_at = job.started_at or now
                job.finished_at = None
                job.updated_at = now
                session.add(job)
            await session.commit()
    return jobs


async def _run_claimed_job(ctx: dict[str, Any], job: ManualSyncJob) -> bool:
    session_factory: async_sessionmaker[AsyncSession] = ctx["session_factory"]
    redis_client = ctx["redis"]
    if job.lock_token is None:
        logger.warning("manual_sync.missing_claim_token", job_id=str(job.id))
        return False

    gdocs_client = ctx.get("gdocs_client") or GDocsClient()
    previous_state = await _read_auto_sync_state(redis_client, job.doc_id)
    if job.notify_chat_id is not None:
        await _set_sync_notify_best_effort(redis_client, job.id, job.notify_chat_id)
    await _write_auto_sync_running(redis_client, job=job, previous_state=previous_state)

    tracer = get_tracer(__name__)
    with tracer.start_as_current_span("manual_sync.run") as span:
        span.set_attribute("job_id", str(job.id))
        span.set_attribute("doc_id", job.doc_id)
        span.set_attribute("attempt_count", job.attempt_count)
        heartbeat_stop = asyncio.Event()
        lease_lost = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            _lease_heartbeat(
                session_factory,
                job.id,
                lock_token=job.lock_token,
                stop=heartbeat_stop,
                lease_lost=lease_lost,
            )
        )
        stage_error: BaseException | None = None
        added_count = 0
        reported_failed = False
        try:
            added_count = await asyncio.wait_for(
                ingest_document(
                    {
                        "redis": redis_client,
                        "session_factory": session_factory,
                        "gdocs_client": gdocs_client,
                        "analysis_service": ctx.get("analysis_service"),
                        "embedding_client": ctx.get("embedding_client"),
                        "motif_service": ctx.get("motif_service"),
                    },
                    job_id=job.id,
                    doc_id=job.doc_id,
                ),
                timeout=SYNC_JOB_TIMEOUT.total_seconds(),
            )
            reported_state = await _read_public_job_state(redis_client, job.id)
            reported_failed = reported_state is not None and reported_state.status == "failed"
        except asyncio.CancelledError as exc:
            stage_error = exc
        except Exception as exc:
            stage_error = exc
        finally:
            heartbeat_stop.set()
            await heartbeat_task

        if lease_lost.is_set():
            logger.warning("manual_sync.job_lease_lost", job_id=str(job.id), doc_id=job.doc_id)

        if stage_error is not None:
            await _write_auto_sync_failed(
                redis_client,
                job=job,
                previous_state=previous_state,
                error="Внутренняя ошибка синхронизации",
            )
            updated = await _mark_failed_attempt(
                session_factory,
                job.id,
                lock_token=job.lock_token,
                attempt_count=job.attempt_count,
                exc=stage_error,
            )
            if updated:
                await _write_public_job_state(
                    redis_client,
                    job.id,
                    SyncJobState(
                        status="failed" if job.attempt_count >= MAX_SYNC_ATTEMPTS else "queued"
                    ),
                )
            if isinstance(stage_error, asyncio.CancelledError):
                return False
            logger.warning(
                "manual_sync.job_retry_scheduled",
                job_id=str(job.id),
                doc_id=job.doc_id,
                lease_owned=updated,
                exc_info=(type(stage_error), stage_error, stage_error.__traceback__),
            )
            return False

        if reported_failed:
            await _write_auto_sync_failed(
                redis_client,
                job=job,
                previous_state=previous_state,
                error="Синхронизация не удалась",
            )
            failed = await _mark_failed_terminal(
                session_factory,
                job.id,
                lock_token=job.lock_token,
                error="manual sync worker reported failure",
            )
            if failed:
                await _write_public_job_state(
                    redis_client,
                    job.id,
                    SyncJobState(status="failed"),
                )
            return False

        try:
            metadata = await asyncio.to_thread(gdocs_client.fetch_document_metadata, job.doc_id)
            last_seen_marker = metadata.change_marker
        except Exception:
            logger.warning("manual_sync.metadata_refresh_failed", doc_id=job.doc_id, exc_info=True)
            last_seen_marker = previous_state.last_seen_marker
        await _write_auto_sync_succeeded(
            redis_client,
            job=job,
            last_seen_marker=last_seen_marker,
            added_count=added_count,
        )
        succeeded = await _mark_succeeded(
            session_factory,
            job.id,
            lock_token=job.lock_token,
            new_entries=added_count,
        )
        if succeeded:
            await _write_public_job_state(
                redis_client,
                job.id,
                SyncJobState(status="done", new_entries=added_count),
            )
        return succeeded


async def _lease_heartbeat(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    *,
    lock_token: uuid.UUID,
    stop: asyncio.Event,
    lease_lost: asyncio.Event,
) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(
                stop.wait(), timeout=SYNC_LEASE_HEARTBEAT_INTERVAL.total_seconds()
            )
            return
        except TimeoutError:
            pass

        try:
            renewed = await _renew_lease(session_factory, job_id, lock_token=lock_token)
        except Exception:
            logger.warning("manual_sync.lease_heartbeat_failed", job_id=str(job_id), exc_info=True)
            lease_lost.set()
            return
        if not renewed:
            lease_lost.set()
            return


async def _renew_lease(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    *,
    lock_token: uuid.UUID,
) -> bool:
    async with session_factory() as session:
        now = datetime.now(timezone.utc)
        result = await session.execute(
            update(ManualSyncJob)
            .where(
                ManualSyncJob.id == job_id,
                ManualSyncJob.status == "running",
                ManualSyncJob.lock_token == lock_token,
            )
            .values(locked_at=now, updated_at=now)
            .returning(ManualSyncJob.id)
        )
        await session.commit()
        return result.scalar_one_or_none() is not None


async def _mark_succeeded(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    *,
    lock_token: uuid.UUID,
    new_entries: int,
) -> bool:
    async with session_factory() as session:
        result = await session.execute(
            update(ManualSyncJob)
            .where(
                ManualSyncJob.id == job_id,
                ManualSyncJob.status == "running",
                ManualSyncJob.lock_token == lock_token,
            )
            .values(
                status="succeeded",
                last_error=None,
                new_entries=new_entries,
                locked_at=None,
                lock_token=None,
                finished_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            .returning(ManualSyncJob.id)
        )
        await session.commit()
        return result.scalar_one_or_none() is not None


async def _mark_failed_attempt(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    *,
    lock_token: uuid.UUID,
    attempt_count: int,
    exc: BaseException,
) -> bool:
    async with session_factory() as session:
        now = datetime.now(timezone.utc)
        terminal = attempt_count >= MAX_SYNC_ATTEMPTS
        result = await session.execute(
            update(ManualSyncJob)
            .where(
                ManualSyncJob.id == job_id,
                ManualSyncJob.status == "running",
                ManualSyncJob.lock_token == lock_token,
            )
            .values(
                status="failed" if terminal else "retryable",
                last_error=_sanitize_sync_error(str(exc)),
                locked_at=None,
                lock_token=None,
                available_at=now + _retry_delay(attempt_count),
                finished_at=now if terminal else None,
                updated_at=now,
            )
            .returning(ManualSyncJob.id)
        )
        await session.commit()
        return result.scalar_one_or_none() is not None


async def _mark_failed_terminal(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    *,
    lock_token: uuid.UUID,
    error: str,
) -> bool:
    async with session_factory() as session:
        now = datetime.now(timezone.utc)
        result = await session.execute(
            update(ManualSyncJob)
            .where(
                ManualSyncJob.id == job_id,
                ManualSyncJob.status == "running",
                ManualSyncJob.lock_token == lock_token,
            )
            .values(
                status="failed",
                last_error=_sanitize_sync_error(error),
                locked_at=None,
                lock_token=None,
                finished_at=now,
                updated_at=now,
            )
            .returning(ManualSyncJob.id)
        )
        await session.commit()
        return result.scalar_one_or_none() is not None


async def _read_auto_sync_state(redis_client: Any, doc_id: str):
    from app.services.auto_sync import AutoSyncState, read_auto_sync_state

    try:
        return await read_auto_sync_state(redis_client, doc_id)
    except Exception:
        logger.warning("manual_sync.auto_sync_state_read_failed", doc_id=doc_id, exc_info=True)
        return AutoSyncState()


async def _write_auto_sync_running(
    redis_client: Any,
    *,
    job: ManualSyncJob,
    previous_state,
) -> None:
    from app.services.auto_sync import AutoSyncState, write_auto_sync_state

    started_at = _utcnow_iso()
    await _write_auto_sync_state_best_effort(
        redis_client,
        job.doc_id,
        AutoSyncState(
            last_seen_marker=previous_state.last_seen_marker,
            last_checked_at=started_at,
            last_sync_started_at=started_at,
            last_synced_at=previous_state.last_synced_at,
            last_sync_job_id=str(job.id),
            last_sync_status="running",
            last_sync_error=None,
            last_added_count=None,
            last_sync_stage="store",
        ),
        write_auto_sync_state,
    )


async def _write_auto_sync_succeeded(
    redis_client: Any,
    *,
    job: ManualSyncJob,
    last_seen_marker: str | None,
    added_count: int,
) -> None:
    from app.services.auto_sync import AutoSyncState, write_auto_sync_state

    synced_at = _utcnow_iso()
    await _write_auto_sync_state_best_effort(
        redis_client,
        job.doc_id,
        AutoSyncState(
            last_seen_marker=last_seen_marker,
            last_checked_at=synced_at,
            last_sync_started_at=None,
            last_synced_at=synced_at,
            last_sync_job_id=str(job.id),
            last_sync_status="synced",
            last_sync_error=None,
            last_added_count=added_count,
            last_sync_stage="done",
        ),
        write_auto_sync_state,
    )


async def _write_auto_sync_failed(
    redis_client: Any,
    *,
    job: ManualSyncJob,
    previous_state,
    error: str,
) -> None:
    from app.services.auto_sync import AutoSyncState, write_auto_sync_state

    failed_at = _utcnow_iso()
    await _write_auto_sync_state_best_effort(
        redis_client,
        job.doc_id,
        AutoSyncState(
            last_seen_marker=previous_state.last_seen_marker,
            last_checked_at=failed_at,
            last_sync_started_at=None,
            last_synced_at=previous_state.last_synced_at,
            last_sync_job_id=str(job.id),
            last_sync_status="failed",
            last_sync_error=error,
            last_added_count=None,
            last_sync_stage="failed",
        ),
        write_auto_sync_state,
    )


async def _write_auto_sync_state_best_effort(
    redis_client: Any,
    doc_id: str,
    state: Any,
    writer,
) -> None:
    try:
        await writer(redis_client, doc_id, state)
    except Exception:
        logger.warning("manual_sync.auto_sync_state_write_failed", doc_id=doc_id, exc_info=True)


async def _set_sync_notify_best_effort(
    redis_client: Any,
    job_id: uuid.UUID,
    chat_id: int,
) -> None:
    try:
        await set_sync_notify(redis_client, job_id, chat_id)
    except Exception:
        logger.warning("manual_sync.notify_write_failed", job_id=str(job_id), exc_info=True)


async def _read_public_job_state(redis_client: Any, job_id: uuid.UUID) -> SyncJobState | None:
    try:
        return await read_sync_job_state(redis_client, job_id)
    except Exception:
        logger.warning("manual_sync.public_status_read_failed", job_id=str(job_id), exc_info=True)
        return None


async def _write_public_job_state(
    redis_client: Any,
    job_id: uuid.UUID,
    state: SyncJobState,
) -> None:
    try:
        await write_sync_job_state(redis_client, job_id, state)
    except Exception:
        logger.warning("manual_sync.public_status_write_failed", job_id=str(job_id), exc_info=True)


def _public_status(status: str) -> str:
    return {
        "pending": "queued",
        "retryable": "queued",
        "succeeded": "done",
    }.get(status, status)


def _retry_delay(attempt_count: int) -> timedelta:
    seconds = min(60 * (2 ** max(0, attempt_count - 1)), int(MAX_RETRY_DELAY.total_seconds()))
    return timedelta(seconds=seconds)


def _sanitize_sync_error(value: str) -> str:
    sanitized = re.sub(r"[\r\n\t]+", " ", value).strip()
    sanitized = re.sub(
        r"(token|secret|key)=\S+",
        r"\1=<redacted>",
        sanitized,
        flags=re.IGNORECASE,
    )
    return (sanitized or "manual sync failed")[:300]


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkerSettings:
    functions = [process_manual_sync_job, process_pending_manual_sync_jobs]
