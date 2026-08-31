"""Voice ingress tests: durable ack, redelivery idempotency, and honest errors."""

from __future__ import annotations

import inspect
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.assistant.facade import AssistantFacade
from app.assistant.voice_media import VoiceMediaEventState
from app.telegram.handlers import (
    VOICE_DOWNLOAD_FAILED,
    VOICE_PROCESSING_ACK,
    VOICE_RUNTIME_UNAVAILABLE,
    VOICE_TRANSCRIPT_PROCESSING,
    VOICE_TRANSCRIPT_UNAVAILABLE,
    text_message_handler,
    voice_message_handler,
)


def _make_voice_update(
    chat_id: int = 42,
    message_id: int = 1,
    file_id: str = "FILEID123",
    duration: int = 5,
) -> tuple[MagicMock, AsyncMock]:
    voice = SimpleNamespace(file_id=file_id, duration=duration)
    message = AsyncMock()
    message.voice = voice
    message.message_id = message_id
    message.reply_text = AsyncMock()
    update = MagicMock()
    update.effective_message = message
    update.effective_chat = SimpleNamespace(id=chat_id)
    return update, message


def _make_context(
    *,
    session_factory: object | None = None,
    facade: object | None = None,
    bot_token: str = "BOT_TOKEN",
    media_dir: str = "/tmp/dream_voice",
) -> SimpleNamespace:
    return SimpleNamespace(
        bot_data={
            "facade": facade or MagicMock(spec=AssistantFacade),
            "session_factory": session_factory or MagicMock(),
            "voice_media_dir": media_dir,
            "bot_token": bot_token,
        },
        bot=AsyncMock(),
    )


def _state(*, status: str = "received", event_id: uuid.UUID | None = None) -> VoiceMediaEventState:
    return VoiceMediaEventState(
        id=event_id or uuid.uuid4(),
        chat_id=42,
        telegram_message_id=1,
        status=status,
        local_path="",
        transcript_text=None,
        reply_text=None,
    )


def _capture_task(_bot_data: object, coroutine: object) -> None:
    if inspect.iscoroutine(coroutine):
        coroutine.close()


@pytest.mark.asyncio
async def test_voice_handler_persists_path_before_ack_and_schedules_job() -> None:
    update, message = _make_voice_update()
    context = _make_context()
    event = _state()
    calls: list[str] = []

    async def get_or_create(*args: object, **kwargs: object) -> tuple[VoiceMediaEventState, bool]:
        calls.append("event")
        return event, True

    async def download(*args: object, **kwargs: object) -> str:
        calls.append("download")
        return "/tmp/dream_voice/voice.ogg"

    async def store(*args: object, **kwargs: object) -> None:
        calls.append("path")

    async def reply(*args: object, **kwargs: object) -> None:
        calls.append("ack")

    message.reply_text.side_effect = reply
    with (
        patch("app.telegram.handlers.get_or_create_voice_media_event", new=get_or_create),
        patch(
            "app.assistant.voice_media.claim_voice_media_event",
            new=AsyncMock(return_value=event),
        ),
        patch("app.telegram.handlers.download_voice_file", new=download),
        patch("app.telegram.handlers.store_voice_media_path", new=store),
        patch("app.telegram.handlers.update_voice_media_event_status", new=AsyncMock()),
        patch("app.workers.transcribe.schedule_voice_task", side_effect=_capture_task) as schedule,
    ):
        await voice_message_handler(update, context)

    assert calls == ["event", "download", "path", "ack"]
    message.reply_text.assert_awaited_once_with(VOICE_PROCESSING_ACK)
    schedule.assert_called_once()


@pytest.mark.asyncio
async def test_voice_handler_persists_correct_telegram_identity() -> None:
    update, _message = _make_voice_update(
        chat_id=99,
        message_id=7,
        file_id="VOICE_FILE_XYZ",
        duration=12,
    )
    context = _make_context()
    event = _state()
    persist = AsyncMock(return_value=(event, True))
    with (
        patch("app.telegram.handlers.get_or_create_voice_media_event", new=persist),
        patch(
            "app.assistant.voice_media.claim_voice_media_event",
            new=AsyncMock(return_value=event),
        ),
        patch(
            "app.telegram.handlers.download_voice_file",
            new=AsyncMock(return_value="/tmp/dream_voice/voice.ogg"),
        ),
        patch("app.telegram.handlers.store_voice_media_path", new=AsyncMock()),
        patch("app.telegram.handlers.update_voice_media_event_status", new=AsyncMock()),
        patch("app.workers.transcribe.schedule_voice_task", side_effect=_capture_task),
    ):
        await voice_message_handler(update, context)

    assert persist.await_args.kwargs == {
        "chat_id": 99,
        "telegram_message_id": 7,
        "telegram_file_id": "VOICE_FILE_XYZ",
        "duration_seconds": 12,
    }


@pytest.mark.asyncio
async def test_duplicate_voice_update_does_not_download_ack_or_schedule() -> None:
    update, message = _make_voice_update()
    context = _make_context()
    event = _state(status="processing")
    with (
        patch(
            "app.telegram.handlers.get_or_create_voice_media_event",
            new=AsyncMock(return_value=(event, False)),
        ),
        patch("app.telegram.handlers.download_voice_file", new=AsyncMock()) as download,
        patch("app.workers.transcribe.schedule_voice_task") as schedule,
    ):
        await voice_message_handler(update, context)

    download.assert_not_awaited()
    message.reply_text.assert_not_awaited()
    schedule.assert_not_called()


@pytest.mark.asyncio
async def test_duplicate_received_update_reclaims_and_finishes_download() -> None:
    update, message = _make_voice_update()
    context = _make_context()
    event = _state(status="received")
    claim = AsyncMock(return_value=event)
    download = AsyncMock(return_value="/tmp/dream_voice/recovered.ogg")
    with (
        patch(
            "app.telegram.handlers.get_or_create_voice_media_event",
            new=AsyncMock(return_value=(event, False)),
        ),
        patch("app.assistant.voice_media.claim_voice_media_event", new=claim),
        patch("app.telegram.handlers.download_voice_file", new=download),
        patch("app.telegram.handlers.store_voice_media_path", new=AsyncMock()) as store,
        patch("app.telegram.handlers.update_voice_media_event_status", new=AsyncMock()),
        patch("app.workers.transcribe.schedule_voice_task", side_effect=_capture_task) as schedule,
    ):
        await voice_message_handler(update, context)

    claim.assert_awaited_once()
    download.assert_awaited_once()
    store.assert_awaited_once()
    message.reply_text.assert_awaited_once_with(VOICE_PROCESSING_ACK)
    schedule.assert_called_once()


@pytest.mark.asyncio
async def test_voice_handler_rejects_when_durable_runtime_is_missing() -> None:
    update, message = _make_voice_update()
    context = _make_context()
    context.bot_data["session_factory"] = None
    with patch("app.telegram.handlers.download_voice_file", new=AsyncMock()) as download:
        await voice_message_handler(update, context)

    download.assert_not_awaited()
    message.reply_text.assert_awaited_once_with(VOICE_RUNTIME_UNAVAILABLE)


@pytest.mark.asyncio
async def test_voice_handler_does_not_download_when_event_persistence_fails() -> None:
    update, message = _make_voice_update()
    context = _make_context()
    with (
        patch(
            "app.telegram.handlers.get_or_create_voice_media_event",
            new=AsyncMock(side_effect=RuntimeError("database unavailable")),
        ),
        patch("app.telegram.handlers.download_voice_file", new=AsyncMock()) as download,
    ):
        await voice_message_handler(update, context)

    download.assert_not_awaited()
    message.reply_text.assert_awaited_once_with(VOICE_RUNTIME_UNAVAILABLE)


@pytest.mark.asyncio
async def test_voice_download_failure_is_staged_as_honest_russian_reply() -> None:
    update, message = _make_voice_update()
    context = _make_context()
    event = _state()
    with (
        patch(
            "app.telegram.handlers.get_or_create_voice_media_event",
            new=AsyncMock(return_value=(event, True)),
        ),
        patch(
            "app.assistant.voice_media.claim_voice_media_event",
            new=AsyncMock(return_value=event),
        ),
        patch(
            "app.telegram.handlers.download_voice_file",
            new=AsyncMock(side_effect=RuntimeError("timeout")),
        ),
        patch(
            "app.workers.transcribe.stage_and_deliver_voice_reply",
            new=AsyncMock(return_value=True),
        ) as stage,
    ):
        await voice_message_handler(update, context)

    message.reply_text.assert_not_awaited()
    assert stage.await_args.kwargs["reply_text"] == VOICE_DOWNLOAD_FAILED
    assert "ничего не добавил" in VOICE_DOWNLOAD_FAILED


@pytest.mark.asyncio
async def test_voice_handler_skips_update_without_voice_attachment() -> None:
    update, message = _make_voice_update()
    message.voice = None
    with patch("app.telegram.handlers.get_or_create_voice_media_event", new=AsyncMock()) as persist:
        await voice_message_handler(update, _make_context())
    persist.assert_not_awaited()


def _make_reply_to_voice_update(
    text: str = "запиши сон",
    *,
    chat_id: int = 42,
    reply_message_id: int = 10,
) -> tuple[MagicMock, AsyncMock]:
    reply_to = SimpleNamespace(message_id=reply_message_id, voice=MagicMock())
    message = AsyncMock()
    message.text = text
    message.reply_to_message = reply_to
    message.reply_text = AsyncMock()
    update = MagicMock()
    update.effective_message = message
    update.effective_chat = SimpleNamespace(id=chat_id)
    return update, message


@pytest.mark.asyncio
async def test_reply_to_voice_can_use_transcript_after_restart() -> None:
    update, message = _make_reply_to_voice_update()
    facade = AsyncMock(spec=AssistantFacade)
    facade.create_dream.return_value = SimpleNamespace(
        created=True,
        written_to_google_doc=True,
        written_to_doc_name="Сны",
    )
    context = _make_context(facade=facade)
    with patch(
        "app.telegram.handlers.get_voice_transcript_for_message",
        new=AsyncMock(return_value=("delivered", "сегодня мне приснилось море и мост")),
    ):
        await text_message_handler(update, context)

    facade.create_dream.assert_awaited_once_with(
        "сегодня мне приснилось море и мост",
        chat_id=42,
        source_event_key="telegram:42:message:10",
    )
    reply_text = message.reply_text.await_args.args[0]
    assert "Сон сохранён" in reply_text
    assert "Google Docs: добавлено" in reply_text


@pytest.mark.asyncio
async def test_reply_to_voice_reports_processing_transcript() -> None:
    update, message = _make_reply_to_voice_update()
    facade = AsyncMock(spec=AssistantFacade)
    context = _make_context(facade=facade)
    with patch(
        "app.telegram.handlers.get_voice_transcript_for_message",
        new=AsyncMock(return_value=("processing", None)),
    ):
        await text_message_handler(update, context)

    facade.create_dream.assert_not_awaited()
    message.reply_text.assert_awaited_once_with(VOICE_TRANSCRIPT_PROCESSING)


@pytest.mark.asyncio
async def test_reply_to_voice_reports_unavailable_transcript() -> None:
    update, message = _make_reply_to_voice_update()
    facade = AsyncMock(spec=AssistantFacade)
    context = _make_context(facade=facade)
    with patch(
        "app.telegram.handlers.get_voice_transcript_for_message",
        new=AsyncMock(return_value=("delivered", None)),
    ):
        await text_message_handler(update, context)

    facade.create_dream.assert_not_awaited()
    message.reply_text.assert_awaited_once_with(VOICE_TRANSCRIPT_UNAVAILABLE)
