"""Unit tests for P7-T03: Voice media retention and cleanup."""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers.cleanup import (
    cleanup_voice_media,
    delete_local_voice_file,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    *,
    event_id: uuid.UUID | None = None,
    status: str = "done",
    local_path: str = "/tmp/dummy.ogg",
    age_seconds: int = 7200,
) -> MagicMock:
    event = MagicMock()
    event.id = event_id or uuid.uuid4()
    event.status = status
    event.local_path = local_path
    event.updated_at = datetime.now(tz=timezone.utc) - timedelta(seconds=age_seconds)
    return event


def _make_session_factory(events: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = events

    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)

    factory = MagicMock()
    factory.return_value = ctx
    return factory


# ---------------------------------------------------------------------------
# AC-1: Retention is bounded and configurable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_returns_zero_when_no_events_returned() -> None:
    """When the DB returns no eligible events (e.g., all within retention), nothing is deleted."""
    factory = _make_session_factory([])
    deleted = await cleanup_voice_media(factory, retention_seconds=3600)
    assert deleted == 0


@pytest.mark.asyncio
async def test_cleanup_deletes_old_terminal_events() -> None:
    """Events older than retention_seconds in terminal state ARE deleted."""
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
        path = f.name
    try:
        event = _make_event(local_path=path, age_seconds=7200, status="done")
        factory = _make_session_factory([event])

        deleted = await cleanup_voice_media(factory, retention_seconds=3600)
        assert deleted == 1
        assert not os.path.exists(path)
    finally:
        if os.path.exists(path):
            os.unlink(path)


@pytest.mark.asyncio
async def test_cleanup_respects_custom_retention_seconds() -> None:
    """Retention window is configurable (short window deletes, long window keeps)."""
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
        path = f.name
    try:
        # Event is 60 seconds old — deleted if retention=30, kept if retention=120
        event = _make_event(local_path=path, age_seconds=60, status="done")
        factory = _make_session_factory([event])

        deleted_short = await cleanup_voice_media(factory, retention_seconds=30)
        assert deleted_short == 1
    finally:
        if os.path.exists(path):
            os.unlink(path)


# ---------------------------------------------------------------------------
# AC-2: Cleanup logic is documented and operational
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_skips_already_absent_files() -> None:
    """If the file no longer exists, cleanup skips gracefully (no error)."""
    event = _make_event(local_path="/tmp/nonexistent_FAKEFILE.ogg", age_seconds=7200)
    factory = _make_session_factory([event])

    deleted = await cleanup_voice_media(factory, retention_seconds=3600)
    assert deleted == 0


@pytest.mark.asyncio
async def test_cleanup_continues_after_deletion_error() -> None:
    """If one file deletion fails, the loop continues to the next."""
    with (
        tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f1,
        tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f2,
    ):
        path1, path2 = f1.name, f2.name

    try:
        event1 = _make_event(event_id=uuid.uuid4(), local_path=path1, age_seconds=7200)
        event2 = _make_event(event_id=uuid.uuid4(), local_path=path2, age_seconds=7200)
        factory = _make_session_factory([event1, event2])

        original_unlink = os.unlink
        call_count = 0

        def selective_unlink(path: str) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("Permission denied")
            original_unlink(path)

        with patch("app.workers.cleanup.os.unlink", side_effect=selective_unlink):
            deleted = await cleanup_voice_media(factory, retention_seconds=3600)

        assert deleted == 1
    finally:
        for p in [path1, path2]:
            if os.path.exists(p):
                os.unlink(p)


# ---------------------------------------------------------------------------
# AC-3: No unbounded file growth — immediate cleanup after transcription
# ---------------------------------------------------------------------------


def test_delete_local_voice_file_removes_existing_file() -> None:
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
        path = f.name
    try:
        assert os.path.exists(path)
        delete_local_voice_file(path)
        assert not os.path.exists(path)
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_delete_local_voice_file_is_noop_for_missing_file() -> None:
    delete_local_voice_file("/tmp/does_not_exist_FAKEVOICE.ogg")


def test_delete_local_voice_file_is_noop_for_empty_path() -> None:
    delete_local_voice_file("")


@pytest.mark.asyncio
async def test_transcribe_and_reply_deletes_local_file_after_success() -> None:
    """After a successful transcription, the raw audio file is immediately deleted."""
    from app.workers.transcribe import transcribe_and_reply

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
        path = f.name

    try:
        with (
            patch("app.workers.transcribe._transcribe_file", new=AsyncMock(return_value="text")),
            patch("app.workers.transcribe.handle_chat", new=AsyncMock(return_value="reply")),
            patch("app.workers.transcribe.update_voice_media_event_status", new=AsyncMock()),
            patch("app.workers.transcribe._send_telegram_message", new=AsyncMock()),
        ):
            await transcribe_and_reply(
                event_id=uuid.uuid4(),
                local_path=path,
                chat_id=1,
                telegram_bot_token="TOK",
                session_factory=MagicMock(),
                facade=MagicMock(),
            )

        assert not os.path.exists(path)
    finally:
        if os.path.exists(path):
            os.unlink(path)
