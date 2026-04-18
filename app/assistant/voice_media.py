"""Voice media event persistence.

Creates and updates VoiceMediaEvent records so media metadata is durable
before and during transcription. Operational state only — not archive truth.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.voice import VoiceMediaEvent


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
        event = await session.get(VoiceMediaEvent, event_id)
        if event is not None:
            event.status = status
            event.updated_at = now
            await session.commit()
