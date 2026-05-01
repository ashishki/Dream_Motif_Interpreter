"""Voice media event persistence.

Creates and updates VoiceMediaEvent records so media metadata is durable
before and during transcription. Operational state only — not archive truth.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.voice import VoiceMediaEvent
from app.shared.tracing import get_tracer


async def create_voice_media_event(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    chat_id: int,
    telegram_message_id: int,
    telegram_file_id: str,
    duration_seconds: int,
    local_path: str,
) -> uuid.UUID:
    """Persist a VoiceMediaEvent and return its generated UUID.

    Status is set to 'received' (initial state).
    """
    now = datetime.now(tz=timezone.utc)
    event = VoiceMediaEvent(
        chat_id=chat_id,
        telegram_message_id=telegram_message_id,
        telegram_file_id=telegram_file_id,
        duration_seconds=duration_seconds,
        local_path=local_path,
        status="received",
        created_at=now,
        updated_at=now,
    )
    async with session_factory() as session:
        with get_tracer(__name__).start_as_current_span("db.voice_media_event.create"):
            session.add(event)
            await session.flush()
            event_id = event.id
            await session.commit()
    return event_id


async def update_voice_media_event_status(
    session_factory: async_sessionmaker[AsyncSession],
    event_id: uuid.UUID,
    status: str,
) -> None:
    """Update the status of an existing VoiceMediaEvent."""
    now = datetime.now(tz=timezone.utc)
    async with session_factory() as session:
        with get_tracer(__name__).start_as_current_span("db.voice_media_event.update"):
            event = await session.get(VoiceMediaEvent, event_id)
            if event is not None:
                event.status = status
                event.updated_at = now
                await session.commit()


async def store_voice_transcript(
    session_factory: async_sessionmaker[AsyncSession],
    event_id: uuid.UUID,
    transcript: str,
) -> None:
    """Persist the transcript text for later reply-to-voice actions."""
    now = datetime.now(tz=timezone.utc)
    async with session_factory() as session:
        with get_tracer(__name__).start_as_current_span("db.voice_transcript.store"):
            event = await session.get(VoiceMediaEvent, event_id)
            if event is not None:
                event.transcript_text = transcript
                event.status = "transcribed"
                event.updated_at = now
                await session.commit()


async def get_voice_transcript_for_message(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    chat_id: int,
    telegram_message_id: int,
) -> tuple[str | None, str | None]:
    """Return (status, transcript_text) for a Telegram voice message."""
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
