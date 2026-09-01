"""Unit coverage for durable voice transcription and reply delivery."""

from __future__ import annotations

import asyncio
import inspect
import os
import uuid
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.assistant.chat import ChatResult
from app.assistant.facade import AssistantFacade
from app.assistant.session import clear_pending_dream_draft, load_pending_dream_draft
from app.assistant.voice_media import VoiceLeaseLost, VoiceMediaEventState
from app.workers.transcribe import (
    _PROCESSING_FAILED_MESSAGE,
    _TRANSCRIPTION_FAILED_MESSAGE,
    _WHISPER_TIMEOUT_SECONDS,
    _transcribe_file,
    _voice_lease_heartbeat,
    VOICE_LEASE_SECONDS,
    deliver_pending_voice_reply,
    resume_pending_voice_jobs,
    run_claimed_voice_event,
    run_voice_retention_cycle,
    schedule_voice_task,
    stop_voice_maintenance_supervisor,
    transcribe_and_reply,
    voice_maintenance_supervisor,
)


def _facade() -> AsyncMock:
    return AsyncMock(spec=AssistantFacade)


def _state(
    *,
    event_id: uuid.UUID | None = None,
    status: str = "processing",
    local_path: str = "/tmp/dream_voice/voice.ogg",
    transcript: str | None = None,
    reply: str | None = None,
    chat_id: int = 42,
) -> VoiceMediaEventState:
    return VoiceMediaEventState(
        id=event_id or uuid.uuid4(),
        chat_id=chat_id,
        telegram_message_id=7,
        status=status,
        local_path=local_path,
        transcript_text=transcript,
        reply_text=reply,
    )


@pytest.fixture(autouse=True)
def _clear_pending_drafts() -> None:
    clear_pending_dream_draft(5)
    clear_pending_dream_draft(42)
    yield
    clear_pending_dream_draft(5)
    clear_pending_dream_draft(42)


@pytest.mark.asyncio
async def test_transcribe_routes_transcript_through_chat_and_stages_reply() -> None:
    event = _state()
    transcript = "I was flying over the ocean."
    session_factory = MagicMock()
    facade = _facade()

    with (
        patch("app.workers.transcribe.get_voice_media_event", new=AsyncMock(return_value=event)),
        patch("app.workers.transcribe._transcribe_file", new=AsyncMock(return_value=transcript)),
        patch("app.workers.transcribe.store_voice_transcript", new=AsyncMock()) as store,
        patch("app.workers.transcribe.update_voice_media_event_status", new=AsyncMock()),
        patch(
            "app.workers.transcribe.handle_chat_with_metadata",
            new=AsyncMock(return_value=ChatResult("archive reply", [])),
        ) as chat,
        patch(
            "app.workers.transcribe.stage_and_deliver_voice_reply", new=AsyncMock(return_value=True)
        ) as stage,
    ):
        await transcribe_and_reply(
            event_id=event.id,
            local_path=event.local_path,
            chat_id=42,
            telegram_bot_token="TOKEN",
            session_factory=session_factory,
            facade=facade,
        )

    store.assert_awaited_once_with(session_factory, event.id, transcript)
    chat.assert_awaited_once_with(
        transcript,
        facade,
        session_factory=session_factory,
        chat_id=42,
        source_event_key="telegram:42:message:7",
    )
    assert stage.await_args.kwargs["reply_text"] == "archive reply"


@pytest.mark.asyncio
async def test_transcribe_voice_note_bypasses_chat() -> None:
    transcript = "Добавь заметку к последнему сну, что в нём тоже была башня"
    event = _state(transcript=transcript, status="transcribed")
    facade = _facade()
    facade.add_dream_note.return_value = (True, "Заметка добавлена.")

    with (
        patch("app.workers.transcribe.get_voice_media_event", new=AsyncMock(return_value=event)),
        patch("app.workers.transcribe._transcribe_file", new=AsyncMock()) as transcribe,
        patch("app.workers.transcribe.handle_chat_with_metadata", new=AsyncMock()) as chat,
        patch("app.workers.transcribe.update_voice_media_event_status", new=AsyncMock()),
        patch(
            "app.workers.transcribe.stage_and_deliver_voice_reply", new=AsyncMock(return_value=True)
        ) as stage,
    ):
        await transcribe_and_reply(
            event_id=event.id,
            local_path=event.local_path,
            chat_id=42,
            telegram_bot_token="TOKEN",
            session_factory=MagicMock(),
            facade=facade,
        )

    transcribe.assert_not_awaited()
    chat.assert_not_awaited()
    facade.add_dream_note.assert_awaited_once_with("в нём тоже была башня", chat_id=42)
    assert stage.await_args.kwargs["reply_text"] == "Заметка добавлена."


@pytest.mark.asyncio
async def test_transcribe_natural_dream_uses_direct_capture() -> None:
    transcript = "сегодня мне приснилась рыба"
    event = _state(transcript=transcript, status="transcribed", chat_id=5)
    facade = _facade()
    facade.create_dream.return_value = SimpleNamespace(
        created=True,
        written_to_google_doc=True,
        written_to_doc_name="Dream Archive",
    )

    with (
        patch("app.workers.transcribe.get_voice_media_event", new=AsyncMock(return_value=event)),
        patch("app.workers.transcribe.update_voice_media_event_status", new=AsyncMock()),
        patch("app.workers.transcribe.handle_chat_with_metadata", new=AsyncMock()) as chat,
        patch(
            "app.workers.transcribe.stage_and_deliver_voice_reply", new=AsyncMock(return_value=True)
        ) as stage,
    ):
        await transcribe_and_reply(
            event_id=event.id,
            local_path=event.local_path,
            chat_id=5,
            telegram_bot_token="TOKEN",
            session_factory=MagicMock(),
            facade=facade,
        )

    chat.assert_not_awaited()
    facade.create_dream.assert_awaited_once_with(
        transcript,
        chat_id=5,
        source_event_key="telegram:5:message:7",
    )
    reply_text = stage.await_args.kwargs["reply_text"]
    assert "Сон сохранён" in reply_text
    assert "Google Docs: добавлено" in reply_text
    assert load_pending_dream_draft(5) is None


@pytest.mark.asyncio
async def test_transcription_failure_stages_honest_russian_error() -> None:
    event = _state()
    with (
        patch("app.workers.transcribe.get_voice_media_event", new=AsyncMock(return_value=event)),
        patch(
            "app.workers.transcribe._transcribe_file",
            new=AsyncMock(side_effect=RuntimeError("provider down")),
        ) as transcribe,
        patch("app.workers.transcribe.update_voice_media_event_status", new=AsyncMock()),
        patch(
            "app.workers.transcribe.record_voice_transcription_failure",
            new=AsyncMock(side_effect=[1, 2, 3]),
        ),
        patch("app.workers.transcribe.asyncio.sleep", new=AsyncMock()) as sleep,
        patch(
            "app.workers.transcribe.stage_and_deliver_voice_reply", new=AsyncMock(return_value=True)
        ) as stage,
    ):
        await transcribe_and_reply(
            event_id=event.id,
            local_path=event.local_path,
            chat_id=42,
            telegram_bot_token="TOKEN",
            session_factory=MagicMock(),
            facade=_facade(),
        )

    assert stage.await_args.kwargs["reply_text"] == _TRANSCRIPTION_FAILED_MESSAGE
    assert "ничего не добавил" in _TRANSCRIPTION_FAILED_MESSAGE
    assert transcribe.await_count == 3
    assert sleep.await_count == 2


@pytest.mark.asyncio
async def test_transient_whisper_failure_retries_before_staging_reply() -> None:
    event = _state()
    with (
        patch("app.workers.transcribe.get_voice_media_event", new=AsyncMock(return_value=event)),
        patch(
            "app.workers.transcribe._transcribe_file",
            new=AsyncMock(side_effect=[RuntimeError("temporary"), "recovered transcript"]),
        ) as transcribe,
        patch(
            "app.workers.transcribe.record_voice_transcription_failure",
            new=AsyncMock(return_value=1),
        ) as record_failure,
        patch("app.workers.transcribe.asyncio.sleep", new=AsyncMock()),
        patch("app.workers.transcribe.store_voice_transcript", new=AsyncMock()) as store,
        patch("app.workers.transcribe.update_voice_media_event_status", new=AsyncMock()),
        patch(
            "app.workers.transcribe.handle_chat_with_metadata",
            new=AsyncMock(return_value=ChatResult("recovered reply", [])),
        ),
        patch(
            "app.workers.transcribe.stage_and_deliver_voice_reply", new=AsyncMock(return_value=True)
        ) as stage,
    ):
        await transcribe_and_reply(
            event_id=event.id,
            local_path=event.local_path,
            chat_id=42,
            telegram_bot_token="TOKEN",
            session_factory=MagicMock(),
            facade=_facade(),
        )

    assert transcribe.await_count == 2
    record_failure.assert_awaited_once()
    store.assert_awaited_once()
    assert stage.await_args.kwargs["reply_text"] == "recovered reply"


@pytest.mark.asyncio
async def test_blank_whisper_result_is_retryable_without_empty_chat() -> None:
    event = _state()
    owner = "worker-a"
    with (
        patch("app.workers.transcribe.get_voice_media_event", new=AsyncMock(return_value=event)),
        patch("app.workers.transcribe._transcribe_file", new=AsyncMock(return_value="   ")),
        patch(
            "app.workers.transcribe.record_voice_transcription_failure",
            new=AsyncMock(return_value=1),
        ) as record_failure,
        patch("app.workers.transcribe.store_voice_transcript", new=AsyncMock()) as store,
        patch("app.workers.transcribe.handle_chat_with_metadata", new=AsyncMock()) as chat,
        patch("app.workers.transcribe.stage_and_deliver_voice_reply", new=AsyncMock()) as stage,
        patch("app.workers.transcribe.asyncio.sleep", new=AsyncMock()) as sleep,
        patch("app.workers.transcribe.update_voice_media_event_status", new=AsyncMock()),
    ):
        await transcribe_and_reply(
            event_id=event.id,
            local_path=event.local_path,
            chat_id=42,
            telegram_bot_token="TOKEN",
            session_factory=MagicMock(),
            facade=_facade(),
            lease_owner=owner,
        )

    record_failure.assert_awaited_once()
    assert record_failure.await_args.kwargs["lease_owner"] == owner
    store.assert_not_awaited()
    chat.assert_not_awaited()
    stage.assert_not_awaited()
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_leased_transcription_failure_defers_to_live_supervisor() -> None:
    event = _state()
    owner = "worker-a"
    with (
        patch("app.workers.transcribe.get_voice_media_event", new=AsyncMock(return_value=event)),
        patch(
            "app.workers.transcribe._transcribe_file",
            new=AsyncMock(side_effect=RuntimeError("temporary")),
        ) as transcribe,
        patch(
            "app.workers.transcribe.record_voice_transcription_failure",
            new=AsyncMock(return_value=1),
        ) as record_failure,
        patch("app.workers.transcribe.asyncio.sleep", new=AsyncMock()) as sleep,
        patch("app.workers.transcribe.update_voice_media_event_status", new=AsyncMock()),
        patch("app.workers.transcribe.stage_and_deliver_voice_reply", new=AsyncMock()) as stage,
    ):
        await transcribe_and_reply(
            event_id=event.id,
            local_path=event.local_path,
            chat_id=42,
            telegram_bot_token="TOKEN",
            session_factory=MagicMock(),
            facade=_facade(),
            lease_owner=owner,
        )

    transcribe.assert_awaited_once()
    record_failure.assert_awaited_once()
    assert record_failure.await_args.kwargs["lease_owner"] == owner
    assert record_failure.await_args.kwargs["retry_delay_seconds"] > 0
    sleep.assert_not_awaited()
    stage.assert_not_awaited()


@pytest.mark.asyncio
async def test_restart_reuses_stored_transcript_without_whisper() -> None:
    event = _state(status="transcribed", transcript="stored transcript")
    with (
        patch("app.workers.transcribe.get_voice_media_event", new=AsyncMock(return_value=event)),
        patch("app.workers.transcribe._transcribe_file", new=AsyncMock()) as transcribe,
        patch("app.workers.transcribe.update_voice_media_event_status", new=AsyncMock()),
        patch(
            "app.workers.transcribe.handle_chat_with_metadata",
            new=AsyncMock(return_value=ChatResult("resumed", [])),
        ) as chat,
        patch(
            "app.workers.transcribe.stage_and_deliver_voice_reply", new=AsyncMock(return_value=True)
        ) as stage,
    ):
        await transcribe_and_reply(
            event_id=event.id,
            local_path=event.local_path,
            chat_id=42,
            telegram_bot_token="TOKEN",
            session_factory=MagicMock(),
            facade=_facade(),
        )

    transcribe.assert_not_awaited()
    assert chat.await_args.kwargs["source_event_key"] == "telegram:42:message:7"
    assert stage.await_args.kwargs["reply_text"] == "resumed"


@pytest.mark.asyncio
async def test_restart_after_terminal_transcription_failure_stages_reply_without_whisper() -> None:
    event = _state(status="transcription_failed")
    with (
        patch("app.workers.transcribe.get_voice_media_event", new=AsyncMock(return_value=event)),
        patch("app.workers.transcribe._transcribe_file", new=AsyncMock()) as transcribe,
        patch(
            "app.workers.transcribe.stage_and_deliver_voice_reply",
            new=AsyncMock(return_value=True),
        ) as stage,
    ):
        await transcribe_and_reply(
            event_id=event.id,
            local_path=event.local_path,
            chat_id=42,
            telegram_bot_token="TOKEN",
            session_factory=MagicMock(),
            facade=_facade(),
            lease_owner="worker-a",
        )

    transcribe.assert_not_awaited()
    assert stage.await_args.kwargs["reply_text"] == _TRANSCRIPTION_FAILED_MESSAGE
    assert stage.await_args.kwargs["lease_owner"] == "worker-a"


@pytest.mark.asyncio
async def test_downstream_failure_does_not_claim_transcription_failed() -> None:
    event = _state(status="transcribed", transcript="already transcribed")
    with (
        patch("app.workers.transcribe.get_voice_media_event", new=AsyncMock(return_value=event)),
        patch("app.workers.transcribe.update_voice_media_event_status", new=AsyncMock()),
        patch(
            "app.workers.transcribe.handle_chat_with_metadata",
            new=AsyncMock(side_effect=RuntimeError("assistant down")),
        ),
        patch(
            "app.workers.transcribe.stage_and_deliver_voice_reply", new=AsyncMock(return_value=True)
        ) as stage,
    ):
        await transcribe_and_reply(
            event_id=event.id,
            local_path=event.local_path,
            chat_id=42,
            telegram_bot_token="TOKEN",
            session_factory=MagicMock(),
            facade=_facade(),
        )

    assert stage.await_args.kwargs["reply_text"] == _PROCESSING_FAILED_MESSAGE
    assert "расшифровано" in _PROCESSING_FAILED_MESSAGE


@pytest.mark.asyncio
async def test_lease_loss_cancels_inflight_whisper_before_any_durable_result() -> None:
    event = _state()
    lease_lost = asyncio.Event()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def blocked_transcription(_path: str) -> str:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        return "must not be stored"

    with (
        patch("app.workers.transcribe.get_voice_media_event", new=AsyncMock(return_value=event)),
        patch("app.workers.transcribe._transcribe_file", new=blocked_transcription),
        patch("app.workers.transcribe.update_voice_media_event_status", new=AsyncMock()),
        patch("app.workers.transcribe.store_voice_transcript", new=AsyncMock()) as store,
        patch("app.workers.transcribe.stage_and_deliver_voice_reply", new=AsyncMock()) as stage,
    ):
        task = asyncio.create_task(
            transcribe_and_reply(
                event_id=event.id,
                local_path=event.local_path,
                chat_id=42,
                telegram_bot_token="TOKEN",
                session_factory=MagicMock(),
                facade=_facade(),
                lease_owner="worker-a",
                lease_lost=lease_lost,
            )
        )
        await started.wait()
        lease_lost.set()
        with pytest.raises(VoiceLeaseLost):
            await asyncio.wait_for(task, timeout=0.2)

    assert cancelled.is_set()
    store.assert_not_awaited()
    stage.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_heartbeat_signals_lease_loss() -> None:
    stop = asyncio.Event()
    lease_lost = asyncio.Event()
    event_id = uuid.uuid4()

    async def immediate_timeout(awaitable: object, *, timeout: float) -> None:
        del timeout
        if inspect.iscoroutine(awaitable):
            awaitable.close()
        raise TimeoutError

    with (
        patch("app.workers.transcribe.asyncio.wait_for", new=immediate_timeout),
        patch(
            "app.workers.transcribe.renew_voice_media_lease",
            new=AsyncMock(return_value=False),
        ) as renew,
    ):
        await _voice_lease_heartbeat(
            MagicMock(),
            event_id=event_id,
            lease_owner="worker-a",
            stop=stop,
            lease_lost=lease_lost,
        )

    assert lease_lost.is_set()
    renew.assert_awaited_once()


@pytest.mark.asyncio
async def test_lease_loss_cancels_inflight_assistant_before_reply_staging() -> None:
    event = _state(status="transcribed", transcript="stored transcript")
    lease_lost = asyncio.Event()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def blocked_reply(*args: object, **kwargs: object) -> ChatResult:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        return ChatResult("must not be staged", [])

    with (
        patch("app.workers.transcribe.get_voice_media_event", new=AsyncMock(return_value=event)),
        patch("app.workers.transcribe.update_voice_media_event_status", new=AsyncMock()),
        patch("app.workers.transcribe.handle_chat_with_metadata", new=blocked_reply),
        patch("app.workers.transcribe.stage_and_deliver_voice_reply", new=AsyncMock()) as stage,
    ):
        task = asyncio.create_task(
            transcribe_and_reply(
                event_id=event.id,
                local_path=event.local_path,
                chat_id=42,
                telegram_bot_token="TOKEN",
                session_factory=MagicMock(),
                facade=_facade(),
                lease_owner="worker-a",
                lease_lost=lease_lost,
            )
        )
        await started.wait()
        lease_lost.set()
        with pytest.raises(VoiceLeaseLost):
            await asyncio.wait_for(task, timeout=0.2)

    assert cancelled.is_set()
    stage.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_failure_keeps_reply_pending_for_retry() -> None:
    event = _state(status="reply_pending", reply="durable reply")
    with (
        patch("app.workers.transcribe.get_voice_media_event", new=AsyncMock(return_value=event)),
        patch(
            "app.workers.transcribe._send_telegram_message",
            new=AsyncMock(side_effect=RuntimeError("Telegram unavailable")),
        ),
        patch("app.workers.transcribe.update_voice_media_event_status", new=AsyncMock()) as update,
    ):
        delivered = await deliver_pending_voice_reply(
            event_id=event.id,
            chat_id=42,
            telegram_bot_token="TOKEN",
            session_factory=MagicMock(),
        )

    assert delivered is False
    update.assert_not_awaited()


@pytest.mark.asyncio
async def test_pending_reply_without_text_is_failed_without_send() -> None:
    event = _state(status="reply_pending")
    owner = "worker-a"
    session_factory = MagicMock()
    with (
        patch("app.workers.transcribe.get_voice_media_event", new=AsyncMock(return_value=event)),
        patch("app.workers.transcribe._send_telegram_message", new=AsyncMock()) as send,
        patch("app.workers.transcribe.mark_voice_reply_failed", new=AsyncMock()) as mark_failed,
    ):
        delivered = await deliver_pending_voice_reply(
            event_id=event.id,
            chat_id=42,
            telegram_bot_token="TOKEN",
            session_factory=session_factory,
            lease_owner=owner,
        )

    assert delivered is False
    send.assert_not_awaited()
    mark_failed.assert_awaited_once_with(session_factory, event.id, lease_owner=owner)


@pytest.mark.asyncio
async def test_leased_send_failure_schedules_durable_backoff() -> None:
    event = _state(status="reply_pending", reply="durable reply")
    owner = "worker-a"
    record = AsyncMock(return_value=1)
    with (
        patch("app.workers.transcribe.get_voice_media_event", new=AsyncMock(return_value=event)),
        patch(
            "app.workers.transcribe._send_telegram_message",
            new=AsyncMock(side_effect=RuntimeError("Telegram unavailable")),
        ),
        patch("app.workers.transcribe.record_voice_delivery_failure", new=record),
    ):
        delivered = await deliver_pending_voice_reply(
            event_id=event.id,
            chat_id=42,
            telegram_bot_token="TOKEN",
            session_factory=MagicMock(),
            lease_owner=owner,
        )

    assert delivered is False
    record.assert_awaited_once()
    assert record.await_args.kwargs["lease_owner"] == owner
    assert record.await_args.kwargs["retry_delay_seconds"] > 0


@pytest.mark.asyncio
async def test_successful_send_marks_delivered() -> None:
    event = _state(status="reply_pending", reply="durable reply")
    session_factory = MagicMock()
    with (
        patch("app.workers.transcribe.get_voice_media_event", new=AsyncMock(return_value=event)),
        patch("app.workers.transcribe._send_telegram_message", new=AsyncMock()) as send,
        patch("app.workers.transcribe.store_voice_delivery_progress", new=AsyncMock()) as progress,
        patch("app.workers.transcribe.mark_voice_reply_delivered", new=AsyncMock()) as mark,
    ):
        delivered = await deliver_pending_voice_reply(
            event_id=event.id,
            chat_id=42,
            telegram_bot_token="TOKEN",
            session_factory=session_factory,
        )

    assert delivered is True
    send.assert_awaited_once_with("TOKEN", 42, "durable reply")
    progress.assert_awaited_once_with(session_factory, event.id, 1)
    mark.assert_awaited_once_with(session_factory, event.id)


@pytest.mark.asyncio
async def test_lease_loss_cancels_inflight_send_without_advancing_cursor() -> None:
    event = _state(status="reply_pending", reply="durable reply")
    lease_lost = asyncio.Event()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def blocked_send(*args: object, **kwargs: object) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with (
        patch("app.workers.transcribe.get_voice_media_event", new=AsyncMock(return_value=event)),
        patch("app.workers.transcribe._send_telegram_message", new=blocked_send),
        patch("app.workers.transcribe.store_voice_delivery_progress", new=AsyncMock()) as progress,
        patch("app.workers.transcribe.mark_voice_reply_delivered", new=AsyncMock()) as mark,
    ):
        task = asyncio.create_task(
            deliver_pending_voice_reply(
                event_id=event.id,
                chat_id=42,
                telegram_bot_token="TOKEN",
                session_factory=MagicMock(),
                lease_owner="worker-a",
                lease_lost=lease_lost,
            )
        )
        await started.wait()
        lease_lost.set()
        assert await asyncio.wait_for(task, timeout=0.2) is False

    assert cancelled.is_set()
    progress.assert_not_awaited()
    mark.assert_not_awaited()


@pytest.mark.asyncio
async def test_whisper_transport_is_single_attempt_bounded_and_closed(tmp_path) -> None:
    audio_path = tmp_path / "voice.ogg"
    audio_path.write_bytes(b"voice")
    create = AsyncMock(return_value=SimpleNamespace(text=" transcript "))
    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create)))
    transport = MagicMock()
    transport.__aenter__ = AsyncMock(return_value=client)
    transport.__aexit__ = AsyncMock(return_value=None)
    constructor = MagicMock(return_value=transport)

    with (
        patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}),
        patch("openai.AsyncOpenAI", constructor),
    ):
        result = await _transcribe_file(str(audio_path))

    assert result == "transcript"
    assert 0 < _WHISPER_TIMEOUT_SECONDS < VOICE_LEASE_SECONDS
    constructor.assert_called_once_with(
        api_key="test-key",
        timeout=_WHISPER_TIMEOUT_SECONDS,
        max_retries=0,
    )
    transport.__aexit__.assert_awaited_once()
    assert create.await_args.kwargs["file"].closed is True


@pytest.mark.asyncio
async def test_whisper_transport_rejects_blank_transcript(tmp_path) -> None:
    audio_path = tmp_path / "voice.ogg"
    audio_path.write_bytes(b"voice")
    create = AsyncMock(return_value=SimpleNamespace(text=" \n "))
    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create)))
    transport = MagicMock()
    transport.__aenter__ = AsyncMock(return_value=client)
    transport.__aexit__ = AsyncMock(return_value=None)
    constructor = MagicMock(return_value=transport)

    with (
        patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}),
        patch("openai.AsyncOpenAI", constructor),
    ):
        with pytest.raises(RuntimeError, match="empty transcript"):
            await _transcribe_file(str(audio_path))

    transport.__aexit__.assert_awaited_once()
    assert create.await_args.kwargs["file"].closed is True


@pytest.mark.asyncio
async def test_delivery_resumes_after_persisted_chunk_cursor() -> None:
    long_reply = "A" * 4000
    event = _state(status="reply_pending", reply=long_reply)
    event = replace(event, reply_chunks_delivered=1)
    session_factory = MagicMock()
    with (
        patch("app.workers.transcribe.get_voice_media_event", new=AsyncMock(return_value=event)),
        patch("app.workers.transcribe._send_telegram_message", new=AsyncMock()) as send,
        patch("app.workers.transcribe.store_voice_delivery_progress", new=AsyncMock()) as progress,
        patch("app.workers.transcribe.mark_voice_reply_delivered", new=AsyncMock()) as mark,
    ):
        delivered = await deliver_pending_voice_reply(
            event_id=event.id,
            chat_id=42,
            telegram_bot_token="TOKEN",
            session_factory=session_factory,
        )

    assert delivered is True
    send.assert_awaited_once_with("TOKEN", 42, "A" * 100)
    progress.assert_awaited_once_with(session_factory, event.id, 2)
    mark.assert_awaited_once_with(session_factory, event.id)


@pytest.mark.asyncio
async def test_delivery_marks_delivered_without_resending_after_final_cursor() -> None:
    """Crash recovery after final cursor commit must not duplicate Telegram sends."""
    long_reply = "A" * 4000
    event = _state(status="reply_pending", reply=long_reply)
    event = replace(event, reply_chunks_delivered=2)
    session_factory = MagicMock()
    with (
        patch("app.workers.transcribe.get_voice_media_event", new=AsyncMock(return_value=event)),
        patch("app.workers.transcribe._send_telegram_message", new=AsyncMock()) as send,
        patch("app.workers.transcribe.store_voice_delivery_progress", new=AsyncMock()) as progress,
        patch("app.workers.transcribe.mark_voice_reply_delivered", new=AsyncMock()) as mark,
    ):
        delivered = await deliver_pending_voice_reply(
            event_id=event.id,
            chat_id=42,
            telegram_bot_token="TOKEN",
            session_factory=session_factory,
        )

    assert delivered is True
    send.assert_not_awaited()
    progress.assert_not_awaited()
    mark.assert_awaited_once_with(session_factory, event.id)


@pytest.mark.asyncio
async def test_startup_recovery_schedules_pending_delivery_and_transcription() -> None:
    pending = _state(status="reply_pending", reply="reply")
    transcribed = _state(status="transcribed", transcript="text")
    facade = MagicMock(spec=AssistantFacade)
    application = SimpleNamespace(
        bot_data={
            "session_factory": MagicMock(),
            "facade": facade,
            "bot_token": "TOKEN",
            "voice_media_dir": "/tmp/dream_voice",
        }
    )
    coroutines: list[object] = []

    def capture_task(_bot_data: object, coroutine: object) -> None:
        coroutines.append(coroutine)
        if inspect.iscoroutine(coroutine):
            coroutine.close()

    with (
        patch(
            "app.workers.transcribe.claim_recoverable_voice_media_events",
            new=AsyncMock(return_value=[pending, transcribed]),
        ) as claim,
        patch("app.workers.transcribe.schedule_voice_task", side_effect=capture_task),
    ):
        count = await resume_pending_voice_jobs(application)

    assert count == 2
    assert len(coroutines) == 2
    assert claim.await_args.kwargs["lease_seconds"] > 0


@pytest.mark.asyncio
async def test_each_recovery_claim_uses_a_fresh_fencing_owner() -> None:
    application = SimpleNamespace(
        bot_data={
            "session_factory": MagicMock(),
            "facade": MagicMock(spec=AssistantFacade),
            "bot_token": "TOKEN",
        }
    )
    with patch(
        "app.workers.transcribe.claim_recoverable_voice_media_events",
        new=AsyncMock(return_value=[]),
    ) as claim:
        await resume_pending_voice_jobs(application)
        await resume_pending_voice_jobs(application)

    first_owner = claim.await_args_list[0].kwargs["lease_owner"]
    second_owner = claim.await_args_list[1].kwargs["lease_owner"]
    assert first_owner != second_owner
    assert len(first_owner) <= 128
    assert len(second_owner) <= 128


@pytest.mark.asyncio
async def test_recovery_redownloads_when_retention_removed_tracked_media(tmp_path) -> None:
    missing_path = tmp_path / "missing.ogg"
    downloaded_path = tmp_path / "redownloaded.ogg"
    event = _state(status="downloaded", local_path=str(missing_path))
    bot_data = {
        "session_factory": MagicMock(),
        "facade": MagicMock(spec=AssistantFacade),
        "bot_token": "TOKEN",
        "voice_media_dir": str(tmp_path),
    }

    with (
        patch(
            "app.workers.transcribe.get_voice_media_event",
            new=AsyncMock(return_value=event),
        ),
        patch(
            "app.workers.transcribe.download_voice_file_by_id",
            new=AsyncMock(return_value=str(downloaded_path)),
        ) as download,
        patch("telegram.Bot", return_value=MagicMock()),
        patch("app.workers.transcribe.store_voice_media_path", new=AsyncMock()) as store,
        patch("app.workers.transcribe.transcribe_and_reply", new=AsyncMock()) as process,
        patch("app.workers.transcribe.release_voice_media_lease", new=AsyncMock()),
        patch("app.workers.transcribe._voice_lease_heartbeat", new=AsyncMock()),
    ):
        await run_claimed_voice_event(
            bot_data=bot_data,
            event_id=event.id,
            lease_owner="claim-token",
        )

    download.assert_awaited_once()
    store.assert_awaited_once_with(
        bot_data["session_factory"],
        event.id,
        str(downloaded_path),
        lease_owner="claim-token",
    )
    assert process.await_args.kwargs["local_path"] == str(downloaded_path)


@pytest.mark.asyncio
async def test_live_supervisor_repeats_recovery_and_retention_cycles() -> None:
    application = SimpleNamespace(bot_data={})
    stop = asyncio.Event()
    recovery_calls = 0

    async def recover(*args: object, **kwargs: object) -> int:
        nonlocal recovery_calls
        recovery_calls += 1
        if recovery_calls >= 2:
            stop.set()
        return 0

    with (
        patch("app.workers.transcribe.resume_pending_voice_jobs", new=recover),
        patch(
            "app.workers.transcribe.run_voice_retention_cycle",
            new=AsyncMock(return_value=(0, 0, 0)),
        ) as retention,
    ):
        await voice_maintenance_supervisor(
            application,
            stop=stop,
            poll_interval_seconds=0.001,
            cleanup_interval_seconds=0,
            batch_size=3,
        )

    assert recovery_calls == 2
    assert retention.await_count == 2


@pytest.mark.asyncio
async def test_retention_cycle_purges_expired_bot_sessions() -> None:
    session_factory = MagicMock()
    application = SimpleNamespace(
        bot_data={"session_factory": session_factory, "voice_media_dir": "/safe/voice"}
    )
    settings = SimpleNamespace(
        VOICE_RETENTION_SECONDS=3600,
        VOICE_TRANSCRIPT_RETENTION_SECONDS=604_800,
        VOICE_MEDIA_DIR="/default/voice",
    )

    with (
        patch("app.workers.transcribe.get_settings", return_value=settings),
        patch("app.workers.transcribe.cleanup_voice_media", new=AsyncMock(return_value=1)),
        patch("app.workers.transcribe.cleanup_orphan_voice_files", new=AsyncMock(return_value=2)),
        patch(
            "app.workers.transcribe.purge_expired_voice_transcripts",
            new=AsyncMock(return_value=3),
        ),
        patch(
            "app.workers.transcribe.purge_expired_bot_sessions",
            new=AsyncMock(return_value=4),
        ) as purge_sessions,
    ):
        counts = await run_voice_retention_cycle(application)

    assert counts == (1, 2, 3)
    purge_sessions.assert_awaited_once_with(session_factory, retention_seconds=604_800)


@pytest.mark.asyncio
async def test_supervisor_poll_wait_is_interrupted_by_stop_event() -> None:
    application = SimpleNamespace(bot_data={})
    stop = asyncio.Event()
    first_cycle_finished = asyncio.Event()

    async def retention(*args: object, **kwargs: object) -> tuple[int, int, int]:
        first_cycle_finished.set()
        return 0, 0, 0

    with (
        patch(
            "app.workers.transcribe.resume_pending_voice_jobs",
            new=AsyncMock(return_value=0),
        ),
        patch("app.workers.transcribe.run_voice_retention_cycle", new=retention),
    ):
        task = asyncio.create_task(
            voice_maintenance_supervisor(
                application,
                stop=stop,
                poll_interval_seconds=3600,
                cleanup_interval_seconds=3600,
                batch_size=1,
            )
        )
        await first_cycle_finished.wait()
        stop.set()
        await asyncio.wait_for(task, timeout=0.2)

    assert task.done()


@pytest.mark.asyncio
async def test_stop_supervisor_cancels_and_awaits_retained_voice_tasks() -> None:
    started = asyncio.Event()
    finalized = asyncio.Event()

    async def pending_job() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            finalized.set()

    application = SimpleNamespace(bot_data={})
    task = schedule_voice_task(application.bot_data, pending_job())
    await started.wait()

    await stop_voice_maintenance_supervisor(application)

    assert task.cancelled()
    assert finalized.is_set()
    assert not application.bot_data.get("_transcription_tasks")


@pytest.mark.asyncio
async def test_stop_supervisor_is_bounded_for_cancellation_resistant_active_task() -> None:
    started = asyncio.Event()
    cancellation_seen = asyncio.Event()
    release = asyncio.Event()

    async def resistant_job() -> None:
        started.set()
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancellation_seen.set()

    application = SimpleNamespace(bot_data={})
    task = schedule_voice_task(application.bot_data, resistant_job())
    await started.wait()

    try:
        with patch("app.workers.transcribe.VOICE_ACTIVE_TASK_STOP_TIMEOUT_SECONDS", 0.01):
            await asyncio.wait_for(stop_voice_maintenance_supervisor(application), timeout=0.1)

        assert cancellation_seen.is_set()
        assert not task.done()
    finally:
        release.set()
        await asyncio.wait_for(task, timeout=0.2)
