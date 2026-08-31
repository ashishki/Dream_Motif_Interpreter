"""Unit tests for P7-T03: Voice media retention and cleanup."""

from __future__ import annotations

import os
import logging
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.assistant.voice_media import VoiceMediaEventState
from app.workers.cleanup import (
    cleanup_orphan_voice_files,
    cleanup_voice_media,
    delete_local_voice_file,
    purge_expired_bot_sessions,
    purge_expired_voice_transcripts,
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


def _make_session_factory(
    events: list,
    *,
    claimed_events: list | None = None,
) -> MagicMock:
    scan_result = MagicMock()
    scan_result.scalars.return_value.all.return_value = events

    claim_results = []
    for event in events if claimed_events is None else claimed_events:
        claim_result = MagicMock()
        claim_result.scalar_one_or_none.return_value = event
        claim_results.append(claim_result)

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[scan_result, *claim_results])

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

        deleted = await cleanup_voice_media(
            factory,
            retention_seconds=3600,
            media_dir=str(Path(path).parent),
        )
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

        deleted_short = await cleanup_voice_media(
            factory,
            retention_seconds=30,
            media_dir=str(Path(path).parent),
        )
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
            deleted = await cleanup_voice_media(
                factory,
                retention_seconds=3600,
                media_dir=str(Path(path1).parent),
            )

        assert deleted == 1
    finally:
        for p in [path1, path2]:
            if os.path.exists(p):
                os.unlink(p)


@pytest.mark.asyncio
async def test_cleanup_cas_skips_candidate_that_changed_before_unlink() -> None:
    """A stale detached candidate cannot authorize a later filesystem deletion."""
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as voice_file:
        path = voice_file.name
    try:
        event = _make_event(local_path=path, age_seconds=7200, status="downloaded")
        factory = _make_session_factory([event], claimed_events=[None])

        with patch("app.workers.cleanup.os.unlink") as unlink:
            deleted = await cleanup_voice_media(
                factory,
                retention_seconds=0,
                media_dir=str(Path(path).parent),
            )

        assert deleted == 0
        assert os.path.exists(path)
        unlink.assert_not_called()

        session = factory.return_value.__aenter__.return_value
        claim_statement = session.execute.await_args_list[1].args[0]
        rendered_claim = str(claim_statement)
        assert "FOR UPDATE" in rendered_claim
        assert "voice_media_events.updated_at =" in rendered_claim
        assert "voice_media_events.local_path =" in rendered_claim
        assert "voice_media_events.lease_owner IS NULL" in rendered_claim
        assert "voice_media_events.lease_expires_at" in rendered_claim
    finally:
        if os.path.exists(path):
            os.unlink(path)


@pytest.mark.asyncio
async def test_cleanup_holds_row_fence_until_path_is_cleared() -> None:
    """The row remains locked until unlink succeeds and local_path is cleared."""
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as voice_file:
        path = voice_file.name
    try:
        event = _make_event(local_path=path, age_seconds=7200, status="downloaded")
        factory = _make_session_factory([event])
        session = factory.return_value.__aenter__.return_value
        operations: list[str] = []
        original_unlink = os.unlink

        def tracked_unlink(candidate: Path) -> None:
            operations.append("unlink")
            original_unlink(candidate)

        async def tracked_commit() -> None:
            operations.append("commit")

        session.commit.side_effect = tracked_commit
        with patch("app.workers.cleanup.os.unlink", side_effect=tracked_unlink):
            deleted = await cleanup_voice_media(
                factory,
                retention_seconds=0,
                media_dir=str(Path(path).parent),
            )

        assert deleted == 1
        assert operations == ["unlink", "commit"]
        assert event.local_path == ""
    finally:
        if os.path.exists(path):
            os.unlink(path)


@pytest.mark.asyncio
async def test_cleanup_rejects_negative_retention() -> None:
    factory = _make_session_factory([])

    with pytest.raises(ValueError, match="non-negative"):
        await cleanup_voice_media(factory, retention_seconds=-1)

    factory.assert_not_called()


# ---------------------------------------------------------------------------
# AC-3: No unbounded file growth — immediate cleanup after transcription
# ---------------------------------------------------------------------------


def test_delete_local_voice_file_removes_existing_file() -> None:
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
        path = f.name
    try:
        assert os.path.exists(path)
        delete_local_voice_file(path, media_dir=str(Path(path).parent))
        assert not os.path.exists(path)
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_delete_local_voice_file_is_noop_for_missing_file() -> None:
    delete_local_voice_file("/tmp/does_not_exist_FAKEVOICE.ogg")


def test_delete_local_voice_file_is_noop_for_empty_path() -> None:
    delete_local_voice_file("")


def test_delete_local_voice_file_refuses_path_outside_media_root() -> None:
    with tempfile.TemporaryDirectory() as media_dir:
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as outside:
            outside_path = outside.name
        try:
            delete_local_voice_file(outside_path, media_dir=media_dir)
            assert os.path.exists(outside_path)
        finally:
            os.unlink(outside_path)


@pytest.mark.asyncio
async def test_sweep_refuses_path_outside_media_root() -> None:
    with tempfile.TemporaryDirectory() as media_dir:
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as outside:
            outside_path = outside.name
        try:
            factory = _make_session_factory([_make_event(local_path=outside_path)])
            deleted = await cleanup_voice_media(
                factory,
                retention_seconds=0,
                media_dir=media_dir,
            )
            assert deleted == 0
            assert os.path.exists(outside_path)
        finally:
            os.unlink(outside_path)


@pytest.mark.asyncio
async def test_orphan_sweep_deletes_only_aged_untracked_voice_files() -> None:
    with tempfile.TemporaryDirectory() as media_dir:
        root = Path(media_dir)
        orphan = root / "crash-window.ogg"
        partial = root / "download.ogg.part"
        young = root / "in-flight.ogg"
        ignored = root / "notes.txt"
        for path in (orphan, partial, young, ignored):
            path.write_bytes(b"voice")
        old_timestamp = (datetime.now(tz=timezone.utc) - timedelta(hours=2)).timestamp()
        os.utime(orphan, (old_timestamp, old_timestamp))
        os.utime(partial, (old_timestamp, old_timestamp))
        os.utime(ignored, (old_timestamp, old_timestamp))

        deleted = await cleanup_orphan_voice_files(
            _make_session_factory([]),
            retention_seconds=3600,
            media_dir=media_dir,
        )

        assert deleted == 2
        assert not orphan.exists()
        assert not partial.exists()
        assert young.exists()
        assert ignored.exists()


@pytest.mark.asyncio
async def test_orphan_sweep_keeps_tracked_file() -> None:
    with tempfile.TemporaryDirectory() as media_dir:
        tracked = Path(media_dir) / "tracked.ogg"
        tracked.write_bytes(b"voice")
        old_timestamp = (datetime.now(tz=timezone.utc) - timedelta(hours=2)).timestamp()
        os.utime(tracked, (old_timestamp, old_timestamp))

        deleted = await cleanup_orphan_voice_files(
            _make_session_factory([str(tracked)]),
            retention_seconds=3600,
            media_dir=media_dir,
        )

        assert deleted == 0
        assert tracked.exists()


@pytest.mark.asyncio
async def test_purge_expired_voice_transcripts_commits_cleared_rows() -> None:
    factory = _make_session_factory([uuid.uuid4(), uuid.uuid4()])

    purged = await purge_expired_voice_transcripts(factory, retention_seconds=604_800)

    assert purged == 2
    session = factory.return_value.__aenter__.return_value
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_purge_expired_voice_transcripts_rejects_negative_retention() -> None:
    factory = _make_session_factory([])

    with pytest.raises(ValueError, match="non-negative"):
        await purge_expired_voice_transcripts(factory, retention_seconds=-1)

    factory.assert_not_called()


@pytest.mark.asyncio
async def test_purge_expired_bot_sessions_physically_deletes_rows_without_logging_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sensitive_history = "private dream about a glass forest"
    factory = _make_session_factory([101, 202])

    with caplog.at_level(logging.INFO, logger="app.workers.cleanup"):
        purged = await purge_expired_bot_sessions(factory, retention_seconds=604_800)

    assert purged == 2
    session = factory.return_value.__aenter__.return_value
    statement = session.execute.await_args.args[0]
    assert str(statement).startswith("DELETE FROM bot_sessions")
    assert "bot_sessions.updated_at" in str(statement)
    session.commit.assert_awaited_once()
    assert sensitive_history not in caplog.text


@pytest.mark.asyncio
async def test_purge_expired_bot_sessions_rejects_negative_retention() -> None:
    factory = _make_session_factory([])

    with pytest.raises(ValueError, match="non-negative"):
        await purge_expired_bot_sessions(factory, retention_seconds=-1)

    factory.assert_not_called()


@pytest.mark.asyncio
async def test_transcribe_and_reply_deletes_local_file_after_success() -> None:
    """Raw audio is deleted only after the reply has been durably staged."""
    from app.workers.transcribe import stage_and_deliver_voice_reply

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
        path = f.name
    event_id = uuid.uuid4()
    session_factory = MagicMock()
    state = VoiceMediaEventState(
        id=event_id,
        chat_id=1,
        telegram_message_id=1,
        status="reply_pending",
        local_path=path,
        transcript_text="text",
        reply_text="reply",
    )

    try:
        with (
            patch("app.workers.transcribe.store_voice_reply_pending", new=AsyncMock()),
            patch(
                "app.workers.transcribe.get_voice_media_event", new=AsyncMock(return_value=state)
            ),
            patch("app.workers.transcribe.store_voice_delivery_progress", new=AsyncMock()),
            patch("app.workers.transcribe.mark_voice_reply_delivered", new=AsyncMock()),
            patch("app.workers.transcribe._send_telegram_message", new=AsyncMock()),
        ):
            await stage_and_deliver_voice_reply(
                event_id=event_id,
                local_path=path,
                chat_id=1,
                telegram_bot_token="TOK",
                session_factory=session_factory,
                reply_text="reply",
                media_dir=str(Path(path).parent),
            )

        assert not os.path.exists(path)
    finally:
        if os.path.exists(path):
            os.unlink(path)
