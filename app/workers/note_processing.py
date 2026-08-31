from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.assistant.facade import AssistantFacade
from app.models.processing import NoteProcessingJob
from app.retrieval.query import RagQueryService
from app.shared.tracing import get_logger, get_tracer

logger = get_logger(__name__)

MAX_PROCESSING_ATTEMPTS = 5
STALE_JOB_AFTER = timedelta(minutes=10)
LEASE_HEARTBEAT_INTERVAL = timedelta(minutes=3)
PROCESSING_STAGE_TIMEOUT = timedelta(minutes=8)
MAX_RETRY_DELAY = timedelta(hours=1)


async def process_note_job(
    ctx: dict[str, Any],
    *,
    job_id: uuid.UUID,
) -> bool:
    """Claim and process one note outbox row. Safe to call repeatedly."""
    session_factory: async_sessionmaker[AsyncSession] = ctx["session_factory"]
    claimed = await _claim_jobs(session_factory, job_id=job_id, limit=1)
    if not claimed:
        return False
    return await _run_claimed_job(ctx, claimed[0])


async def process_pending_note_jobs(
    ctx: dict[str, Any],
    *,
    limit: int = 20,
) -> int:
    """Recover queued, retryable, and stale-running note work after startup."""
    session_factory: async_sessionmaker[AsyncSession] = ctx["session_factory"]
    completed = 0
    for _ in range(max(1, min(limit, 100))):
        # Claim immediately before execution so later leases cannot expire while
        # earlier stages in a batch are still running.
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
) -> list[NoteProcessingJob]:
    del limit  # Lease ownership is intentionally one-at-a-time.
    now = datetime.now(timezone.utc)
    stale_before = now - STALE_JOB_AFTER
    eligible = or_(
        and_(
            NoteProcessingJob.status.in_(("pending", "retryable")),
            NoteProcessingJob.available_at <= now,
            NoteProcessingJob.attempt_count < MAX_PROCESSING_ATTEMPTS,
        ),
        and_(
            NoteProcessingJob.status == "running",
            or_(
                NoteProcessingJob.locked_at.is_(None),
                NoteProcessingJob.locked_at < stale_before,
            ),
            NoteProcessingJob.attempt_count < MAX_PROCESSING_ATTEMPTS,
        ),
    )
    stmt = (
        select(NoteProcessingJob)
        .where(eligible)
        .order_by(NoteProcessingJob.available_at.asc(), NoteProcessingJob.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job_id is not None:
        stmt = stmt.where(NoteProcessingJob.id == job_id)

    async with session_factory() as session:
        with get_tracer(__name__).start_as_current_span("note_processing.claim"):
            terminal_stale_conditions = [
                NoteProcessingJob.status == "running",
                or_(
                    NoteProcessingJob.locked_at.is_(None),
                    NoteProcessingJob.locked_at < stale_before,
                ),
                NoteProcessingJob.attempt_count >= MAX_PROCESSING_ATTEMPTS,
            ]
            if job_id is not None:
                terminal_stale_conditions.append(NoteProcessingJob.id == job_id)
            await session.execute(
                update(NoteProcessingJob)
                .where(*terminal_stale_conditions)
                .values(
                    status="failed",
                    last_error="processing lease expired after final attempt",
                    locked_at=None,
                    lock_token=None,
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
                job.updated_at = now
                session.add(job)
            await session.commit()
    return jobs


async def _run_claimed_job(ctx: dict[str, Any], job: NoteProcessingJob) -> bool:
    session_factory: async_sessionmaker[AsyncSession] = ctx["session_factory"]
    if job.lock_token is None:
        logger.warning("note_processing.missing_claim_token", job_id=str(job.id))
        return False
    facade = _build_facade(ctx, session_factory=session_factory)
    tracer = get_tracer(__name__)
    with tracer.start_as_current_span("note_processing.run") as span:
        span.set_attribute("job_id", str(job.id))
        span.set_attribute("note_id", str(job.note_id))
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
        stage_error: Exception | None = None
        try:
            await asyncio.wait_for(
                facade.process_note_processing_job(job.id, lock_token=job.lock_token),
                timeout=PROCESSING_STAGE_TIMEOUT.total_seconds(),
            )
        except Exception as exc:
            stage_error = exc
        finally:
            heartbeat_stop.set()
            await heartbeat_task

        if lease_lost.is_set():
            logger.warning(
                "note_processing.job_lease_lost",
                job_id=str(job.id),
                note_id=str(job.note_id),
            )

        if stage_error is not None:
            updated = await _mark_failed_attempt(
                session_factory,
                job.id,
                lock_token=job.lock_token,
                attempt_count=job.attempt_count,
                exc=stage_error,
            )
            logger.warning(
                "note_processing.job_retry_scheduled",
                job_id=str(job.id),
                note_id=str(job.note_id),
                lease_owned=updated,
                exc_info=True,
            )
            return False

        return await _mark_succeeded(
            session_factory,
            job.id,
            lock_token=job.lock_token,
        )


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
            await asyncio.wait_for(stop.wait(), timeout=LEASE_HEARTBEAT_INTERVAL.total_seconds())
            return
        except TimeoutError:
            pass

        try:
            renewed = await _renew_lease(
                session_factory,
                job_id,
                lock_token=lock_token,
            )
        except Exception:
            logger.warning(
                "note_processing.lease_heartbeat_failed",
                job_id=str(job_id),
                exc_info=True,
            )
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
            update(NoteProcessingJob)
            .where(
                NoteProcessingJob.id == job_id,
                NoteProcessingJob.status == "running",
                NoteProcessingJob.lock_token == lock_token,
            )
            .values(locked_at=now, updated_at=now)
            .returning(NoteProcessingJob.id)
        )
        await session.commit()
        return result.scalar_one_or_none() is not None


def _build_facade(
    ctx: dict[str, Any],
    *,
    session_factory: async_sessionmaker[AsyncSession],
) -> AssistantFacade:
    injected = ctx.get("assistant_facade")
    if injected is not None:
        return injected
    return AssistantFacade(
        session_factory=session_factory,
        rag_query_service=ctx.get("rag_query_service")
        or RagQueryService(session_factory=session_factory),
        index_note_callable=ctx.get("index_note_callable"),
    )


async def _mark_succeeded(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    *,
    lock_token: uuid.UUID,
) -> bool:
    async with session_factory() as session:
        result = await session.execute(
            update(NoteProcessingJob)
            .where(
                NoteProcessingJob.id == job_id,
                NoteProcessingJob.status == "running",
                NoteProcessingJob.lock_token == lock_token,
            )
            .values(
                status="succeeded",
                last_error=None,
                locked_at=None,
                lock_token=None,
                updated_at=datetime.now(timezone.utc),
            )
            .returning(NoteProcessingJob.id)
        )
        await session.commit()
        return result.scalar_one_or_none() is not None


async def _mark_failed_attempt(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    *,
    lock_token: uuid.UUID,
    attempt_count: int,
    exc: Exception,
) -> bool:
    async with session_factory() as session:
        now = datetime.now(timezone.utc)
        terminal = attempt_count >= MAX_PROCESSING_ATTEMPTS
        result = await session.execute(
            update(NoteProcessingJob)
            .where(
                NoteProcessingJob.id == job_id,
                NoteProcessingJob.status == "running",
                NoteProcessingJob.lock_token == lock_token,
            )
            .values(
                status="failed" if terminal else "retryable",
                last_error=_sanitize_processing_error(str(exc)),
                locked_at=None,
                lock_token=None,
                available_at=now + _retry_delay(attempt_count),
                updated_at=now,
            )
            .returning(NoteProcessingJob.id)
        )
        await session.commit()
        return result.scalar_one_or_none() is not None


def _retry_delay(attempt_count: int) -> timedelta:
    seconds = min(
        60 * (2 ** max(0, attempt_count - 1)),
        int(MAX_RETRY_DELAY.total_seconds()),
    )
    return timedelta(seconds=seconds)


def _sanitize_processing_error(value: str) -> str:
    sanitized = re.sub(r"[\r\n\t]+", " ", value).strip()
    sanitized = re.sub(
        r"(token|secret|key)=\S+",
        r"\1=<redacted>",
        sanitized,
        flags=re.IGNORECASE,
    )
    return (sanitized or "note post-capture processing failed")[:300]


class WorkerSettings:
    functions = [process_note_job, process_pending_note_jobs]
