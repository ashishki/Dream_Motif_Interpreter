"""Voice media cleanup worker.

Deletes raw voice files after successful staging or when their retention window
expires. Every deletion is constrained to the configured media root.

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

from sqlalchemy import delete, literal, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.session import BotSession
from app.models.voice import VoiceMediaEvent

LOGGER = logging.getLogger(__name__)

_RAW_MEDIA_CLEANUP_STATUSES = frozenset(
    {
        "received",
        "downloaded",
        "processing",
        "transcribed",
        "transcription_retryable",
        "transcription_failed",
        "reply_pending",
        "delivered",
        "done",
        "failed",
    }
)
_TRANSCRIPT_CLEANUP_STATUSES = frozenset(
    {"transcription_failed", "reply_pending", "delivered", "done", "failed"}
)
_DEFAULT_MEDIA_DIR = "/tmp/dream_voice"


async def cleanup_voice_media(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    retention_seconds: int = 3600,
    media_dir: str = _DEFAULT_MEDIA_DIR,
) -> int:
    """Delete tracked raw voice files older than retention_seconds.

    Returns the count of files deleted.

    Rules:
    - Every known voice lifecycle status is eligible after the retention deadline.
    - Event must be older than retention_seconds (measured from updated_at).
    - A live worker lease prevents cleanup.
    - local_path must resolve inside media_dir and use the .ogg suffix.
    - The file at local_path is deleted; if already gone, the deletion is skipped.
    - On deletion error the event is skipped and logged (not raised).

    Each candidate is compared with its observed path and timestamp and locked
    immediately before unlinking. The narrow row lock prevents a worker or a
    concurrent cleanup pass from claiming the deterministic event path while it
    is being removed. Clearing ``local_path`` in the same transaction fences
    workers that claim the event after deletion.
    """
    if retention_seconds < 0:
        raise ValueError("retention_seconds must be non-negative")

    cutoff = datetime.now(tz=timezone.utc) - timedelta(seconds=retention_seconds)
    deleted_count = 0

    async with session_factory() as session:
        result = await session.execute(
            select(VoiceMediaEvent).where(
                VoiceMediaEvent.status.in_(_RAW_MEDIA_CLEANUP_STATUSES),
                VoiceMediaEvent.updated_at < cutoff,
                VoiceMediaEvent.local_path != "",
            )
        )
        events = list(result.scalars().all())

    for event in events:
        file_path = resolve_voice_media_path(event.local_path, media_dir=media_dir)
        if file_path is None:
            LOGGER.error(
                "Refusing voice cleanup outside media root event_id=%s",
                event.id,
            )
            continue
        claim_time = datetime.now(tz=timezone.utc)
        async with session_factory() as session:
            result = await session.execute(
                select(VoiceMediaEvent)
                .where(
                    VoiceMediaEvent.id == event.id,
                    VoiceMediaEvent.status.in_(_RAW_MEDIA_CLEANUP_STATUSES),
                    VoiceMediaEvent.updated_at == event.updated_at,
                    VoiceMediaEvent.updated_at < cutoff,
                    VoiceMediaEvent.local_path == event.local_path,
                    or_(
                        VoiceMediaEvent.lease_owner.is_(None),
                        VoiceMediaEvent.lease_expires_at.is_(None),
                        VoiceMediaEvent.lease_expires_at <= claim_time,
                    ),
                )
                .with_for_update(skip_locked=True)
            )
            claimed_event = result.scalar_one_or_none()
            if claimed_event is None:
                continue

            if not file_path.exists():
                claimed_event.local_path = ""
                await session.commit()
                LOGGER.info(
                    "Cleared missing voice media path event_id=%s path=%s",
                    event.id,
                    file_path.name,
                )
                continue

            try:
                os.unlink(file_path)
            except FileNotFoundError:
                claimed_event.local_path = ""
                await session.commit()
                LOGGER.debug(
                    "Cleared concurrently missing voice media path event_id=%s path=%s",
                    event.id,
                    file_path.name,
                )
            except OSError:
                LOGGER.warning(
                    "Failed to delete voice media event_id=%s path=%s",
                    event.id,
                    file_path.name,
                    exc_info=True,
                )
            else:
                claimed_event.local_path = ""
                await session.commit()
                LOGGER.info("Deleted voice media event_id=%s path=%s", event.id, file_path.name)
                deleted_count += 1

    return deleted_count


async def cleanup_orphan_voice_files(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    retention_seconds: int = 3600,
    media_dir: str = _DEFAULT_MEDIA_DIR,
) -> int:
    """Delete aged ``.ogg``/``.ogg.part`` files not referenced by any event.

    This closes the small crash window after Telegram writes a file but before
    its path is committed. Young files are never touched, so an in-flight
    download has the full retention window to finish and become tracked.
    """
    root = Path(media_dir)
    if not root.is_absolute() or not root.exists() or not root.is_dir():
        return 0
    try:
        resolved_root = root.resolve(strict=True)
    except OSError:
        return 0

    async with session_factory() as session:
        result = await session.execute(
            select(VoiceMediaEvent.local_path).where(VoiceMediaEvent.local_path != "")
        )
        tracked_paths = {
            str(resolved)
            for raw_path in result.scalars().all()
            if (resolved := resolve_voice_media_path(raw_path, media_dir=str(resolved_root)))
            is not None
        }

    cutoff_timestamp = datetime.now(tz=timezone.utc).timestamp() - retention_seconds
    deleted_count = 0
    for candidate in resolved_root.iterdir():
        if not (candidate.name.endswith(".ogg") or candidate.name.endswith(".ogg.part")):
            continue
        try:
            if candidate.is_symlink() or not candidate.is_file():
                continue
            resolved = candidate.resolve(strict=True)
            if resolved_root not in resolved.parents:
                continue
            if str(resolved) in tracked_paths or resolved.stat().st_mtime >= cutoff_timestamp:
                continue
            resolved.unlink()
            deleted_count += 1
            LOGGER.info("Deleted orphan voice file path=%s", resolved.name)
        except OSError:
            LOGGER.warning(
                "Failed to inspect or delete orphan voice file path=%s",
                candidate.name,
                exc_info=True,
            )
    return deleted_count


def delete_local_voice_file(
    local_path: str,
    *,
    media_dir: str = _DEFAULT_MEDIA_DIR,
) -> None:
    """Best-effort synchronous deletion of a local voice file.

    Called after a reply is durably staged to clean up without waiting for the
    scheduled sweep. Failure is logged, not raised.
    """
    path = resolve_voice_media_path(local_path, media_dir=media_dir)
    if path is None:
        if local_path:
            LOGGER.error("Refusing immediate voice cleanup outside media root")
        return
    try:
        if path.exists():
            os.unlink(path)
            LOGGER.info("Deleted local voice file after transcription path=%s", path.name)
    except OSError:
        LOGGER.warning(
            "Failed to delete local voice file path=%s — will be caught by cleanup job",
            path.name,
            exc_info=True,
        )


def resolve_voice_media_path(local_path: str, *, media_dir: str) -> Path | None:
    """Resolve an audio path only when it is an absolute .ogg child of media_dir."""
    if not local_path or not media_dir:
        return None
    candidate = Path(local_path)
    root = Path(media_dir)
    if not candidate.is_absolute() or not root.is_absolute() or candidate.suffix.lower() != ".ogg":
        return None
    try:
        resolved_candidate = candidate.resolve(strict=False)
        resolved_root = root.resolve(strict=False)
    except OSError:
        return None
    if resolved_candidate == resolved_root or resolved_root not in resolved_candidate.parents:
        return None
    return resolved_candidate


async def purge_expired_voice_transcripts(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    retention_seconds: int,
) -> int:
    """Clear operational transcripts after the explicit retention window."""
    if retention_seconds < 0:
        raise ValueError("retention_seconds must be non-negative")

    cutoff = datetime.now(tz=timezone.utc) - timedelta(seconds=retention_seconds)
    async with session_factory() as session:
        result = await session.execute(
            update(VoiceMediaEvent)
            .where(
                VoiceMediaEvent.status.in_(_TRANSCRIPT_CLEANUP_STATUSES),
                VoiceMediaEvent.updated_at < cutoff,
                VoiceMediaEvent.transcript_text.is_not(None),
            )
            .values(transcript_text=None)
            .returning(VoiceMediaEvent.id)
        )
        purged = len(result.scalars().all())
        await session.commit()
    if purged:
        LOGGER.info("Purged expired operational voice transcripts count=%s", purged)
    return purged


async def purge_expired_bot_sessions(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    retention_seconds: int,
) -> int:
    """Physically delete expired conversational histories.

    The age predicate is part of the ``DELETE`` itself, so a session refreshed
    concurrently by an incoming message is retained.  Only aggregate counts are
    logged; neither chat identifiers nor conversation content leave PostgreSQL.
    """
    if retention_seconds < 0:
        raise ValueError("retention_seconds must be non-negative")

    cutoff = datetime.now(tz=timezone.utc) - timedelta(seconds=retention_seconds)
    async with session_factory() as session:
        result = await session.execute(
            delete(BotSession).where(BotSession.updated_at < cutoff).returning(literal(1))
        )
        purged = len(result.scalars().all())
        await session.commit()
    if purged:
        LOGGER.info("Purged expired bot sessions count=%s", purged)
    return purged
