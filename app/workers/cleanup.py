"""Voice media cleanup worker.

Deletes raw voice files (.ogg) once their associated VoiceMediaEvent is in a
terminal state (done or failed) and older than the configured retention window.

This prevents unbounded disk growth from raw audio that has already been
transcribed or permanently failed.

Raw audio is not canonical dream data. Transcripts are not either by default.
Only content that passes explicit domain flows becomes archive truth.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.voice import VoiceMediaEvent

LOGGER = logging.getLogger(__name__)

_TERMINAL_STATUSES = frozenset({"done", "failed"})


async def cleanup_voice_media(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    retention_seconds: int = 3600,
    media_dir: str | None = None,
) -> int:
    """Delete raw voice files for terminal-state events older than retention_seconds.

    Returns the count of files deleted.

    Rules:
    - Only events with status in {done, failed} are eligible.
    - Event must be older than retention_seconds (measured from updated_at).
    - The file at local_path is deleted; if already gone, the deletion is skipped.
    - On deletion error the event is skipped and logged (not raised).
    """
    cutoff = datetime.now(tz=timezone.utc) - timedelta(seconds=retention_seconds)
    deleted_count = 0

    async with session_factory() as session:
        result = await session.execute(
            select(VoiceMediaEvent).where(
                VoiceMediaEvent.status.in_(_TERMINAL_STATUSES),
                VoiceMediaEvent.updated_at < cutoff,
                VoiceMediaEvent.local_path != "",
            )
        )
        events = list(result.scalars().all())

    for event in events:
        file_path = Path(event.local_path)
        if not file_path.exists():
            LOGGER.debug("Voice media already absent event_id=%s path=%s", event.id, event.local_path)
            continue
        try:
            os.unlink(file_path)
            LOGGER.info("Deleted voice media event_id=%s path=%s", event.id, file_path.name)
            deleted_count += 1
        except OSError:
            LOGGER.warning(
                "Failed to delete voice media event_id=%s path=%s",
                event.id,
                event.local_path,
                exc_info=True,
            )

    return deleted_count


def delete_local_voice_file(local_path: str) -> None:
    """Best-effort synchronous deletion of a local voice file.

    Called immediately after successful transcription to clean up without
    waiting for the scheduled cleanup run. Failure is logged, not raised.
    """
    if not local_path:
        return
    path = Path(local_path)
    try:
        if path.exists():
            os.unlink(path)
            LOGGER.info("Deleted local voice file after transcription path=%s", path.name)
    except OSError:
        LOGGER.warning(
            "Failed to delete local voice file path=%s — will be caught by cleanup job",
            local_path,
            exc_info=True,
        )
