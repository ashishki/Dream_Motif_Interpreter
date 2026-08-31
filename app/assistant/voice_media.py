"""Durable operational state for Telegram voice processing.

The database row is both an idempotent ingress receipt and a small outbox job.
Recoverable rows are claimed with a PostgreSQL lease before a worker performs
Whisper, assistant, or Telegram side effects. The lease makes overlapping bot
instances safe while ``next_attempt_at`` keeps transient failures from spinning.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.voice import VoiceMediaEvent
from app.shared.tracing import get_tracer

_VOICE_INGRESS_CONSTRAINT = "uq_voice_media_events_chat_message"
RECOVERABLE_VOICE_STATUSES = frozenset(
    {
        "received",
        "downloaded",
        "processing",
        "transcribed",
        "transcription_retryable",
        "transcription_failed",
        "reply_pending",
    }
)


class VoiceLeaseLost(RuntimeError):
    """Raised when a worker tries to mutate a row it no longer owns."""


@dataclass(frozen=True)
class VoiceMediaEventState:
    """Detached operational state safe to pass outside a DB session."""

    id: uuid.UUID
    chat_id: int
    telegram_message_id: int
    status: str
    local_path: str
    transcript_text: str | None
    reply_text: str | None
    telegram_file_id: str = ""
    duration_seconds: int = 0
    transcription_attempt_count: int = 0
    reply_chunks_delivered: int = 0
    delivery_attempt_count: int = 0
    next_attempt_at: datetime | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None


def _to_state(event: VoiceMediaEvent) -> VoiceMediaEventState:
    return VoiceMediaEventState(
        id=event.id,
        chat_id=event.chat_id,
        telegram_message_id=event.telegram_message_id,
        status=event.status,
        local_path=event.local_path,
        transcript_text=event.transcript_text,
        reply_text=event.reply_text,
        telegram_file_id=event.telegram_file_id,
        duration_seconds=event.duration_seconds,
        transcription_attempt_count=event.transcription_attempt_count,
        reply_chunks_delivered=event.reply_chunks_delivered,
        delivery_attempt_count=event.delivery_attempt_count,
        next_attempt_at=event.next_attempt_at,
        lease_owner=event.lease_owner,
        lease_expires_at=event.lease_expires_at,
    )


async def get_or_create_voice_media_event(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    chat_id: int,
    telegram_message_id: int,
    telegram_file_id: str,
    duration_seconds: int,
) -> tuple[VoiceMediaEventState, bool]:
    """Return one durable ingress event for a Telegram voice update."""
    now = datetime.now(tz=timezone.utc)
    statement = (
        insert(VoiceMediaEvent)
        .values(
            chat_id=chat_id,
            telegram_message_id=telegram_message_id,
            telegram_file_id=telegram_file_id,
            duration_seconds=duration_seconds,
            local_path="",
            status="received",
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(constraint=_VOICE_INGRESS_CONSTRAINT)
        .returning(VoiceMediaEvent.id)
    )
    async with session_factory() as session:
        with get_tracer(__name__).start_as_current_span("db.voice_media_event.get_or_create"):
            result = await session.execute(statement)
            event_id = result.scalar_one_or_none()
            created = event_id is not None
            if event_id is None:
                existing = await session.execute(
                    select(VoiceMediaEvent)
                    .where(VoiceMediaEvent.chat_id == chat_id)
                    .where(VoiceMediaEvent.telegram_message_id == telegram_message_id)
                    .limit(1)
                )
                event = existing.scalar_one()
            else:
                event = await session.get(VoiceMediaEvent, event_id)
                if event is None:  # pragma: no cover - defensive DB invariant
                    raise RuntimeError("Inserted voice media event could not be read")
            state = _to_state(event)
            await session.commit()
    return state, created


async def create_voice_media_event(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    chat_id: int,
    telegram_message_id: int,
    telegram_file_id: str,
    duration_seconds: int,
    local_path: str,
) -> uuid.UUID:
    """Compatibility wrapper returning the idempotent ingress event id."""
    state, _created = await get_or_create_voice_media_event(
        session_factory,
        chat_id=chat_id,
        telegram_message_id=telegram_message_id,
        telegram_file_id=telegram_file_id,
        duration_seconds=duration_seconds,
    )
    if local_path:
        await store_voice_media_path(session_factory, state.id, local_path)
    return state.id


async def get_voice_media_event(
    session_factory: async_sessionmaker[AsyncSession],
    event_id: uuid.UUID,
    *,
    lease_owner: str | None = None,
) -> VoiceMediaEventState | None:
    """Load current state, optionally only while ``lease_owner`` still owns it."""
    now = datetime.now(tz=timezone.utc)
    async with session_factory() as session:
        statement = select(VoiceMediaEvent).where(VoiceMediaEvent.id == event_id)
        if lease_owner is not None:
            statement = statement.where(
                VoiceMediaEvent.lease_owner == lease_owner,
                VoiceMediaEvent.lease_expires_at > now,
            )
        result = await session.execute(statement)
        event = result.scalar_one_or_none()
        return _to_state(event) if event is not None else None


async def list_recoverable_voice_media_events(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[VoiceMediaEventState]:
    """Compatibility read API; workers should claim instead of processing this list."""
    async with session_factory() as session:
        result = await session.execute(
            select(VoiceMediaEvent)
            .where(VoiceMediaEvent.status.in_(RECOVERABLE_VOICE_STATUSES))
            .order_by(VoiceMediaEvent.created_at.asc())
        )
        return [_to_state(event) for event in result.scalars().all()]


async def claim_recoverable_voice_media_events(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    lease_owner: str,
    lease_seconds: int,
    limit: int = 10,
    event_id: uuid.UUID | None = None,
) -> list[VoiceMediaEventState]:
    """Atomically lease due jobs with ``FOR UPDATE SKIP LOCKED``.

    ``event_id`` is used by live ingress; omitting it claims the oldest due batch
    for startup recovery or the periodic supervisor.
    """
    if not lease_owner.strip():
        raise ValueError("Voice lease owner must not be blank")
    if lease_seconds <= 0 or limit <= 0:
        raise ValueError("Voice lease duration and claim limit must be positive")
    now = datetime.now(tz=timezone.utc)
    statement = (
        select(VoiceMediaEvent)
        .where(
            VoiceMediaEvent.status.in_(RECOVERABLE_VOICE_STATUSES),
            or_(
                VoiceMediaEvent.next_attempt_at.is_(None),
                VoiceMediaEvent.next_attempt_at <= now,
            ),
            or_(
                VoiceMediaEvent.lease_owner.is_(None),
                VoiceMediaEvent.lease_expires_at.is_(None),
                VoiceMediaEvent.lease_expires_at <= now,
            ),
        )
        .order_by(VoiceMediaEvent.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(limit)
    )
    if event_id is not None:
        statement = statement.where(VoiceMediaEvent.id == event_id)

    async with session_factory() as session:
        result = await session.execute(statement)
        events = list(result.scalars().all())
        expires_at = now + timedelta(seconds=lease_seconds)
        for event in events:
            event.lease_owner = lease_owner
            event.lease_expires_at = expires_at
            event.next_attempt_at = None
            event.updated_at = now
        states = [_to_state(event) for event in events]
        await session.commit()
        return states


async def claim_voice_media_event(
    session_factory: async_sessionmaker[AsyncSession],
    event_id: uuid.UUID,
    *,
    lease_owner: str,
    lease_seconds: int,
) -> VoiceMediaEventState | None:
    """Claim one due event, returning ``None`` when another instance owns it."""
    claimed = await claim_recoverable_voice_media_events(
        session_factory,
        lease_owner=lease_owner,
        lease_seconds=lease_seconds,
        limit=1,
        event_id=event_id,
    )
    return claimed[0] if claimed else None


async def renew_voice_media_lease(
    session_factory: async_sessionmaker[AsyncSession],
    event_id: uuid.UUID,
    *,
    lease_owner: str,
    lease_seconds: int,
) -> bool:
    """Extend a live lease using compare-and-set ownership."""
    now = datetime.now(tz=timezone.utc)
    async with session_factory() as session:
        result = await session.execute(
            update(VoiceMediaEvent)
            .where(
                VoiceMediaEvent.id == event_id,
                VoiceMediaEvent.lease_owner == lease_owner,
                VoiceMediaEvent.lease_expires_at > now,
            )
            .values(
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                updated_at=now,
            )
            .returning(VoiceMediaEvent.id)
        )
        renewed = result.scalar_one_or_none() is not None
        await session.commit()
    return renewed


async def release_voice_media_lease(
    session_factory: async_sessionmaker[AsyncSession],
    event_id: uuid.UUID,
    *,
    lease_owner: str,
    retry_delay_seconds: float | None = None,
) -> bool:
    """Release an owned lease and optionally make the row eligible after a delay."""
    now = datetime.now(tz=timezone.utc)
    next_attempt = (
        now + timedelta(seconds=max(retry_delay_seconds, 0))
        if retry_delay_seconds is not None
        else None
    )
    async with session_factory() as session:
        result = await session.execute(
            update(VoiceMediaEvent)
            .where(
                VoiceMediaEvent.id == event_id,
                VoiceMediaEvent.lease_owner == lease_owner,
            )
            .values(
                lease_owner=None,
                lease_expires_at=None,
                next_attempt_at=next_attempt,
                updated_at=now,
            )
            .returning(VoiceMediaEvent.id)
        )
        released = result.scalar_one_or_none() is not None
        await session.commit()
    return released


async def _owned_event(
    session: AsyncSession,
    event_id: uuid.UUID,
    *,
    lease_owner: str | None,
) -> VoiceMediaEvent:
    now = datetime.now(tz=timezone.utc)
    statement = select(VoiceMediaEvent).where(VoiceMediaEvent.id == event_id).with_for_update()
    if lease_owner is not None:
        statement = statement.where(
            VoiceMediaEvent.lease_owner == lease_owner,
            VoiceMediaEvent.lease_expires_at > now,
        )
    result = await session.execute(statement)
    event = result.scalar_one_or_none()
    if event is None:
        if lease_owner is not None:
            raise VoiceLeaseLost(f"Voice lease lost for event {event_id}")
        raise LookupError(f"Voice media event not found: {event_id}")
    return event


async def store_voice_media_path(
    session_factory: async_sessionmaker[AsyncSession],
    event_id: uuid.UUID,
    local_path: str,
    *,
    lease_owner: str | None = None,
) -> None:
    """Persist the downloaded path before acknowledging work to Telegram."""
    if not local_path:
        raise ValueError("Voice media path must not be empty")
    now = datetime.now(tz=timezone.utc)
    async with session_factory() as session:
        event = await _owned_event(session, event_id, lease_owner=lease_owner)
        event.local_path = local_path
        event.status = "downloaded"
        event.next_attempt_at = None
        event.updated_at = now
        await session.commit()


async def store_voice_reply_pending(
    session_factory: async_sessionmaker[AsyncSession],
    event_id: uuid.UUID,
    reply_text: str,
    *,
    lease_owner: str | None = None,
) -> None:
    """Durably stage a Telegram reply before attempting network delivery."""
    if not reply_text:
        raise ValueError("Voice reply text must not be empty")
    now = datetime.now(tz=timezone.utc)
    async with session_factory() as session:
        event = await _owned_event(session, event_id, lease_owner=lease_owner)
        event.reply_text = reply_text
        event.reply_chunks_delivered = 0
        event.delivery_attempt_count = 0
        event.status = "reply_pending"
        event.next_attempt_at = None
        event.updated_at = now
        await session.commit()


async def record_voice_transcription_failure(
    session_factory: async_sessionmaker[AsyncSession],
    event_id: uuid.UUID,
    *,
    max_attempts: int,
    retry_delay_seconds: float = 0,
    lease_owner: str | None = None,
) -> int:
    """Record one failed Whisper attempt and durably schedule the next claim."""
    now = datetime.now(tz=timezone.utc)
    async with session_factory() as session:
        event = await _owned_event(session, event_id, lease_owner=lease_owner)
        event.transcription_attempt_count += 1
        terminal = event.transcription_attempt_count >= max_attempts
        event.status = "transcription_failed" if terminal else "transcription_retryable"
        if terminal:
            event.next_attempt_at = None
        else:
            event.next_attempt_at = now + timedelta(seconds=max(retry_delay_seconds, 0))
            event.lease_owner = None
            event.lease_expires_at = None
        event.updated_at = now
        attempts = event.transcription_attempt_count
        await session.commit()
    return attempts


async def record_voice_delivery_failure(
    session_factory: async_sessionmaker[AsyncSession],
    event_id: uuid.UUID,
    *,
    retry_delay_seconds: float,
    lease_owner: str | None = None,
) -> int:
    """Keep the reply outbox pending while applying durable delivery backoff."""
    now = datetime.now(tz=timezone.utc)
    async with session_factory() as session:
        event = await _owned_event(session, event_id, lease_owner=lease_owner)
        event.delivery_attempt_count += 1
        event.status = "reply_pending"
        event.next_attempt_at = now + timedelta(seconds=max(retry_delay_seconds, 0))
        event.lease_owner = None
        event.lease_expires_at = None
        event.updated_at = now
        attempts = event.delivery_attempt_count
        await session.commit()
    return attempts


async def store_voice_delivery_progress(
    session_factory: async_sessionmaker[AsyncSession],
    event_id: uuid.UUID,
    chunks_delivered: int,
    *,
    lease_owner: str | None = None,
) -> None:
    """Advance the chunk cursor without allowing stale workers to regress it."""
    now = datetime.now(tz=timezone.utc)
    async with session_factory() as session:
        event = await _owned_event(session, event_id, lease_owner=lease_owner)
        event.reply_chunks_delivered = max(event.reply_chunks_delivered, chunks_delivered)
        event.updated_at = now
        await session.commit()


async def mark_voice_reply_delivered(
    session_factory: async_sessionmaker[AsyncSession],
    event_id: uuid.UUID,
    *,
    lease_owner: str | None = None,
) -> None:
    """Finish delivery and discard the no-longer-needed reply payload."""
    now = datetime.now(tz=timezone.utc)
    async with session_factory() as session:
        event = await _owned_event(session, event_id, lease_owner=lease_owner)
        event.status = "delivered"
        event.reply_text = None
        event.reply_chunks_delivered = 0
        event.next_attempt_at = None
        event.lease_owner = None
        event.lease_expires_at = None
        event.updated_at = now
        await session.commit()


async def mark_voice_reply_failed(
    session_factory: async_sessionmaker[AsyncSession],
    event_id: uuid.UUID,
    *,
    lease_owner: str | None = None,
) -> None:
    """Move a non-deliverable reply out of the recovery loop."""
    now = datetime.now(tz=timezone.utc)
    async with session_factory() as session:
        event = await _owned_event(session, event_id, lease_owner=lease_owner)
        event.status = "failed"
        event.reply_text = None
        event.reply_chunks_delivered = 0
        event.next_attempt_at = None
        event.lease_owner = None
        event.lease_expires_at = None
        event.updated_at = now
        await session.commit()


async def update_voice_media_event_status(
    session_factory: async_sessionmaker[AsyncSession],
    event_id: uuid.UUID,
    status: str,
    *,
    lease_owner: str | None = None,
) -> None:
    """Update lifecycle state, rejecting mutation from a stale worker."""
    now = datetime.now(tz=timezone.utc)
    async with session_factory() as session:
        with get_tracer(__name__).start_as_current_span("db.voice_media_event.update"):
            event = await _owned_event(session, event_id, lease_owner=lease_owner)
            event.status = status
            event.next_attempt_at = None
            event.updated_at = now
            await session.commit()


async def store_voice_transcript(
    session_factory: async_sessionmaker[AsyncSession],
    event_id: uuid.UUID,
    transcript: str,
    *,
    lease_owner: str | None = None,
) -> None:
    """Persist transcript text for recovery and explicit reply-to-voice actions."""
    now = datetime.now(tz=timezone.utc)
    async with session_factory() as session:
        with get_tracer(__name__).start_as_current_span("db.voice_transcript.store"):
            event = await _owned_event(session, event_id, lease_owner=lease_owner)
            event.transcript_text = transcript
            event.status = "transcribed"
            event.next_attempt_at = None
            event.updated_at = now
            await session.commit()


async def get_voice_transcript_for_message(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    chat_id: int,
    telegram_message_id: int,
) -> tuple[str | None, str | None]:
    """Return ``(status, transcript_text)`` for a Telegram voice message."""
    async with session_factory() as session:
        with get_tracer(__name__).start_as_current_span("db.voice_transcript.lookup"):
            result = await session.execute(
                select(VoiceMediaEvent)
                .where(VoiceMediaEvent.chat_id == chat_id)
                .where(VoiceMediaEvent.telegram_message_id == telegram_message_id)
                .order_by(VoiceMediaEvent.updated_at.desc())
                .limit(1)
            )
            event = result.scalar_one_or_none()
            if event is None:
                return None, None
            return event.status, event.transcript_text
