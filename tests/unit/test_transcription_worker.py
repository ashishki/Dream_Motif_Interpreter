"""Unit tests for P7-T02: Async transcription pipeline."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.assistant.chat import ChatResult
from app.assistant.session import clear_pending_dream_draft, load_pending_dream_draft
from app.workers.transcribe import (
    _TRANSCRIPTION_FAILED_MESSAGE,
    transcribe_and_reply,
)


def _make_session_factory() -> MagicMock:
    factory = MagicMock()
    return factory


def _make_facade() -> MagicMock:
    from app.assistant.facade import AssistantFacade

    return AsyncMock(spec=AssistantFacade)


@pytest.fixture(autouse=True)
def _clear_pending_drafts() -> None:
    clear_pending_dream_draft(5)
    clear_pending_dream_draft(42)
    yield
    clear_pending_dream_draft(5)
    clear_pending_dream_draft(42)


# ---------------------------------------------------------------------------
# AC-1: Transcription job is processed asynchronously
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_and_reply_calls_whisper_and_sends_reply() -> None:
    """Full success path: transcribe → handle_chat → send reply."""
    event_id = uuid.uuid4()
    chat_id = 42
    transcript = "I was flying over the ocean."
    reply_text = "The archive shows flying dreams on several occasions."
    session_factory = _make_session_factory()

    with (
        patch("app.workers.transcribe._transcribe_file", new=AsyncMock(return_value=transcript)),
        patch(
            "app.workers.transcribe.handle_chat_with_metadata",
            new=AsyncMock(return_value=ChatResult(reply_text, [])),
        ) as mock_chat,
        patch(
            "app.workers.transcribe.update_voice_media_event_status", new=AsyncMock()
        ) as mock_update,
        patch("app.workers.transcribe.store_voice_transcript", new=AsyncMock()) as mock_store,
        patch("app.workers.transcribe._send_telegram_message", new=AsyncMock()) as mock_send,
    ):
        await transcribe_and_reply(
            event_id=event_id,
            local_path="/tmp/voice.ogg",
            chat_id=chat_id,
            telegram_bot_token="TOKEN",
            session_factory=session_factory,
            facade=_make_facade(),
        )

    mock_chat.assert_awaited_once()
    call_text = mock_chat.call_args[0][0]
    assert call_text == transcript

    mock_send.assert_awaited_once_with("TOKEN", chat_id, reply_text)
    mock_store.assert_awaited_once_with(session_factory, event_id, transcript)
    mock_update.assert_awaited()


# ---------------------------------------------------------------------------
# AC-2: Transcript is routed through the same text assistant path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_and_reply_routes_through_handle_chat() -> None:
    """The transcript text is passed verbatim to handle_chat (same as text path)."""
    event_id = uuid.uuid4()
    transcript = "There was a red door that kept appearing."
    facade = _make_facade()
    session_factory = _make_session_factory()

    with (
        patch("app.workers.transcribe._transcribe_file", new=AsyncMock(return_value=transcript)),
        patch(
            "app.workers.transcribe.handle_chat_with_metadata",
            new=AsyncMock(return_value=ChatResult("Some reply", [])),
        ) as mock_chat,
        patch("app.workers.transcribe.store_voice_transcript", new=AsyncMock()),
        patch("app.workers.transcribe.update_voice_media_event_status", new=AsyncMock()),
        patch("app.workers.transcribe._send_telegram_message", new=AsyncMock()),
    ):
        await transcribe_and_reply(
            event_id=event_id,
            local_path="/tmp/f.ogg",
            chat_id=5,
            telegram_bot_token="TOK",
            session_factory=session_factory,
            facade=facade,
        )

    mock_chat.assert_awaited_once_with(
        transcript,
        facade,
        session_factory=session_factory,
        chat_id=5,
    )


@pytest.mark.asyncio
async def test_transcribe_and_reply_saves_short_natural_dream_transcript_without_chat() -> None:
    event_id = uuid.uuid4()
    transcript = "сегодня мне приснилось рыба"
    facade = _make_facade()
    facade.create_dream = AsyncMock(
        return_value=SimpleNamespace(
            created=True,
            written_to_google_doc=True,
            written_to_doc_name="Dream Archive",
        )
    )
    session_factory = _make_session_factory()

    with (
        patch("app.workers.transcribe._transcribe_file", new=AsyncMock(return_value=transcript)),
        patch("app.workers.transcribe.handle_chat_with_metadata", new=AsyncMock()) as mock_chat,
        patch("app.workers.transcribe.store_voice_transcript", new=AsyncMock()),
        patch(
            "app.workers.transcribe.update_voice_media_event_status", new=AsyncMock()
        ) as mock_update,
        patch("app.workers.transcribe.delete_local_voice_file") as mock_delete,
        patch("app.workers.transcribe._send_telegram_message", new=AsyncMock()) as mock_send,
    ):
        await transcribe_and_reply(
            event_id=event_id,
            local_path="/tmp/f.ogg",
            chat_id=5,
            telegram_bot_token="TOK",
            session_factory=session_factory,
            facade=facade,
        )

    mock_chat.assert_not_awaited()
    facade.create_dream.assert_awaited_once_with(transcript, chat_id=5)
    mock_update.assert_awaited_with(session_factory, event_id, "done")
    mock_delete.assert_called_once_with("/tmp/f.ogg")
    mock_send.assert_awaited_once_with(
        "TOK",
        5,
        "Сон сохранён и добавлен в документ",
    )


# ---------------------------------------------------------------------------
# AC-3: Provider failure is recoverable and observable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_and_reply_sends_error_on_transcription_failure() -> None:
    """When Whisper fails, user gets an error message and event status is 'failed'."""
    event_id = uuid.uuid4()

    with (
        patch(
            "app.workers.transcribe._transcribe_file",
            new=AsyncMock(side_effect=RuntimeError("API error")),
        ),
        patch("app.workers.transcribe.handle_chat_with_metadata", new=AsyncMock()) as mock_chat,
        patch(
            "app.workers.transcribe.update_voice_media_event_status", new=AsyncMock()
        ) as mock_update,
        patch("app.workers.transcribe._send_telegram_message", new=AsyncMock()) as mock_send,
    ):
        await transcribe_and_reply(
            event_id=event_id,
            local_path="/tmp/bad.ogg",
            chat_id=7,
            telegram_bot_token="TOK",
            session_factory=_make_session_factory(),
            facade=_make_facade(),
        )

    mock_chat.assert_not_awaited()
    mock_send.assert_awaited_once_with("TOK", 7, _TRANSCRIPTION_FAILED_MESSAGE)

    status_call = mock_update.call_args_list[-1]
    assert status_call[0][2] == "failed"


@pytest.mark.asyncio
async def test_transcribe_and_reply_sends_error_when_handle_chat_fails() -> None:
    """When handle_chat fails after transcription, user gets an error and event is 'failed'."""
    event_id = uuid.uuid4()

    with (
        patch("app.workers.transcribe._transcribe_file", new=AsyncMock(return_value="transcript")),
        patch(
            "app.workers.transcribe.handle_chat_with_metadata",
            new=AsyncMock(side_effect=RuntimeError("LLM down")),
        ),
        patch("app.workers.transcribe.store_voice_transcript", new=AsyncMock()),
        patch(
            "app.workers.transcribe.update_voice_media_event_status", new=AsyncMock()
        ) as mock_update,
        patch("app.workers.transcribe._send_telegram_message", new=AsyncMock()) as mock_send,
    ):
        await transcribe_and_reply(
            event_id=event_id,
            local_path="/tmp/ok.ogg",
            chat_id=9,
            telegram_bot_token="TOK",
            session_factory=_make_session_factory(),
            facade=_make_facade(),
        )

    mock_send.assert_awaited_once_with("TOK", 9, _TRANSCRIPTION_FAILED_MESSAGE)
    status_call = mock_update.call_args_list[-1]
    assert status_call[0][2] == "failed"


@pytest.mark.asyncio
async def test_transcribe_and_reply_updates_status_to_done_on_success() -> None:
    with (
        patch("app.workers.transcribe._transcribe_file", new=AsyncMock(return_value="text")),
        patch(
            "app.workers.transcribe.handle_chat_with_metadata",
            new=AsyncMock(return_value=ChatResult("ok", [])),
        ),
        patch("app.workers.transcribe.store_voice_transcript", new=AsyncMock()) as mock_store,
        patch(
            "app.workers.transcribe.update_voice_media_event_status", new=AsyncMock()
        ) as mock_update,
        patch("app.workers.transcribe._send_telegram_message", new=AsyncMock()),
    ):
        await transcribe_and_reply(
            event_id=uuid.uuid4(),
            local_path="/tmp/ok.ogg",
            chat_id=1,
            telegram_bot_token="TOK",
            session_factory=_make_session_factory(),
            facade=_make_facade(),
        )

    mock_store.assert_awaited_once()
    statuses = [call[0][2] for call in mock_update.call_args_list]
    assert "done" in statuses


@pytest.mark.asyncio
async def test_transcribe_and_reply_does_not_store_pending_draft_for_natural_dream() -> None:
    event_id = uuid.uuid4()
    transcript = "сегодня мне приснилось рыба"
    facade = _make_facade()
    facade.create_dream = AsyncMock(
        return_value=SimpleNamespace(
            created=True,
            written_to_google_doc=True,
            written_to_doc_name="Dream Archive",
        )
    )

    with (
        patch("app.workers.transcribe._transcribe_file", new=AsyncMock(return_value=transcript)),
        patch("app.workers.transcribe.handle_chat_with_metadata", new=AsyncMock()),
        patch("app.workers.transcribe.store_voice_transcript", new=AsyncMock()),
        patch("app.workers.transcribe.update_voice_media_event_status", new=AsyncMock()),
        patch("app.workers.transcribe.delete_local_voice_file"),
        patch("app.workers.transcribe._send_telegram_message", new=AsyncMock()),
    ):
        await transcribe_and_reply(
            event_id=event_id,
            local_path="/tmp/f.ogg",
            chat_id=5,
            telegram_bot_token="TOK",
            session_factory=_make_session_factory(),
            facade=facade,
        )

    assert load_pending_dream_draft(5) is None
