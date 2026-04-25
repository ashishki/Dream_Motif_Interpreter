"""Unit tests for P7-T01/P7-T04: Voice ingress, media persistence, and end-to-end success path."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.telegram.handlers import voice_message_handler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_voice_update(
    chat_id: int = 42,
    message_id: int = 1,
    file_id: str = "FILEID123",
    duration: int = 5,
) -> tuple[MagicMock, MagicMock]:
    voice = MagicMock()
    voice.file_id = file_id
    voice.duration = duration

    message = AsyncMock()
    message.voice = voice
    message.message_id = message_id
    message.reply_text = AsyncMock()

    chat = MagicMock()
    chat.id = chat_id

    update = MagicMock()
    update.effective_message = message
    update.effective_chat = chat
    return update, message


def _make_context(
    session_factory: object = None, voice_media_dir: str = "/tmp/test_voice"
) -> SimpleNamespace:
    return SimpleNamespace(
        bot_data={
            "session_factory": session_factory,
            "voice_media_dir": voice_media_dir,
        },
        bot=AsyncMock(),
    )


# ---------------------------------------------------------------------------
# AC-1: Voice updates are accepted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_handler_accepts_authorized_voice_message() -> None:
    """Voice handler runs through the download + ack flow without error."""
    update, message = _make_voice_update()
    context = _make_context()

    with (
        patch(
            "app.telegram.handlers.create_voice_media_event",
            new=AsyncMock(return_value=uuid.uuid4()),
        ),
        patch(
            "app.telegram.handlers.download_voice_file",
            new=AsyncMock(return_value="/tmp/test_voice/file.ogg"),
        ),
    ):
        await voice_message_handler(update, context)

    message.reply_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_voice_handler_skips_when_no_voice_attachment() -> None:
    """Handler returns early without any error when voice attachment is missing."""
    message = AsyncMock()
    message.voice = None
    message.reply_text = AsyncMock()

    update = MagicMock()
    update.effective_message = message
    update.effective_chat = MagicMock()
    update.effective_chat.id = 1

    context = _make_context()

    with (
        patch("app.telegram.handlers.create_voice_media_event", new=AsyncMock()) as mock_persist,
        patch("app.telegram.handlers.download_voice_file", new=AsyncMock()) as mock_dl,
    ):
        await voice_message_handler(update, context)

    mock_persist.assert_not_awaited()
    mock_dl.assert_not_awaited()


# ---------------------------------------------------------------------------
# AC-2: Media metadata is persisted before transcription starts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_handler_persists_media_event_before_download() -> None:
    """create_voice_media_event is called with correct metadata."""
    chat_id = 99
    message_id = 7
    file_id = "VOICE_FILE_XYZ"
    duration = 12

    update, _ = _make_voice_update(
        chat_id=chat_id, message_id=message_id, file_id=file_id, duration=duration
    )
    session_factory = MagicMock()
    context = _make_context(session_factory=session_factory)

    call_order: list[str] = []

    async def mock_persist(sf: object, **kwargs: object) -> uuid.UUID:
        call_order.append("persist")
        return uuid.uuid4()

    async def mock_download(*args: object, **kwargs: object) -> str:
        call_order.append("download")
        return "/tmp/test_voice/out.ogg"

    with (
        patch("app.telegram.handlers.create_voice_media_event", new=mock_persist),
        patch("app.telegram.handlers.download_voice_file", new=mock_download),
    ):
        await voice_message_handler(update, context)

    assert "persist" in call_order
    assert call_order.index("persist") < call_order.index("download")


@pytest.mark.asyncio
async def test_voice_handler_passes_correct_metadata_to_persist() -> None:
    update, _ = _make_voice_update(chat_id=5, message_id=3, file_id="FID", duration=8)
    session_factory = MagicMock()
    context = _make_context(session_factory=session_factory)

    captured: dict = {}

    async def mock_persist(sf: object, **kwargs: object) -> uuid.UUID:
        captured.update(kwargs)
        return uuid.uuid4()

    with (
        patch("app.telegram.handlers.create_voice_media_event", new=mock_persist),
        patch(
            "app.telegram.handlers.download_voice_file", new=AsyncMock(return_value="/tmp/x.ogg")
        ),
    ):
        await voice_message_handler(update, context)

    assert captured["chat_id"] == 5
    assert captured["telegram_message_id"] == 3
    assert captured["telegram_file_id"] == "FID"
    assert captured["duration_seconds"] == 8


# ---------------------------------------------------------------------------
# AC-3: Bot acknowledges processing is in progress
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_handler_sends_processing_acknowledgement() -> None:
    update, message = _make_voice_update()
    context = _make_context()

    with (
        patch(
            "app.telegram.handlers.create_voice_media_event",
            new=AsyncMock(return_value=uuid.uuid4()),
        ),
        patch(
            "app.telegram.handlers.download_voice_file", new=AsyncMock(return_value="/tmp/f.ogg")
        ),
    ):
        await voice_message_handler(update, context)

    message.reply_text.assert_awaited_once_with("Обрабатываю голосовое сообщение...")


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_handler_sends_error_reply_when_download_fails() -> None:
    update, message = _make_voice_update()
    context = _make_context(session_factory=MagicMock())

    with (
        patch(
            "app.telegram.handlers.create_voice_media_event",
            new=AsyncMock(return_value=uuid.uuid4()),
        ),
        patch(
            "app.telegram.handlers.download_voice_file",
            new=AsyncMock(side_effect=RuntimeError("timeout")),
        ),
    ):
        await voice_message_handler(update, context)

    message.reply_text.assert_awaited_once()
    call_text = message.reply_text.call_args[0][0]
    assert "download" in call_text.lower() or "voice" in call_text.lower()


@pytest.mark.asyncio
async def test_voice_handler_continues_without_session_factory() -> None:
    """When no session_factory is configured, handler skips persistence but still downloads."""
    update, message = _make_voice_update()
    context = _make_context(session_factory=None)

    with (
        patch("app.telegram.handlers.create_voice_media_event", new=AsyncMock()) as mock_persist,
        patch(
            "app.telegram.handlers.download_voice_file", new=AsyncMock(return_value="/tmp/f.ogg")
        ),
    ):
        await voice_message_handler(update, context)

    mock_persist.assert_not_awaited()
    message.reply_text.assert_awaited_once_with("Обрабатываю голосовое сообщение...")


# ---------------------------------------------------------------------------
# P7-T04 AC-1: Voice success path end-to-end (handler enqueues transcription)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_handler_enqueues_transcription_task_when_fully_configured() -> None:
    """When all required config is present (session_factory, bot_token, facade),
    voice_message_handler enqueues a transcribe_and_reply task. AC-1 (success path)."""
    from app.assistant.facade import AssistantFacade

    event_id = uuid.uuid4()
    update, message = _make_voice_update(chat_id=77)

    facade = AsyncMock(spec=AssistantFacade)
    session_factory = MagicMock()
    context = SimpleNamespace(
        bot_data={
            "session_factory": session_factory,
            "voice_media_dir": "/tmp/test_voice",
            "bot_token": "BOT_TOKEN",
            "facade": facade,
        },
        bot=AsyncMock(),
    )

    enqueued_coros: list = []

    def mock_create_task(coro: object) -> MagicMock:
        import inspect

        if inspect.iscoroutine(coro):
            coro.close()
        enqueued_coros.append(coro)
        task = MagicMock()
        task.add_done_callback = MagicMock()
        return task

    with (
        patch(
            "app.telegram.handlers.create_voice_media_event", new=AsyncMock(return_value=event_id)
        ),
        patch(
            "app.telegram.handlers.download_voice_file",
            new=AsyncMock(return_value="/tmp/voice.ogg"),
        ),
        patch("app.telegram.handlers.asyncio.create_task", side_effect=mock_create_task),
    ):
        await voice_message_handler(update, context)

    assert len(enqueued_coros) == 1
    message.reply_text.assert_awaited_once_with("Обрабатываю голосовое сообщение...")
