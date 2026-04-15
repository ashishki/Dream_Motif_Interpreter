"""Unit tests for P7-T02: Async transcription pipeline."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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

    with patch("app.workers.transcribe._transcribe_file", new=AsyncMock(return_value=transcript)), \
         patch("app.workers.transcribe.handle_chat", new=AsyncMock(return_value=reply_text)) as mock_chat, \
         patch("app.workers.transcribe.update_voice_media_event_status", new=AsyncMock()) as mock_update, \
         patch("app.workers.transcribe._send_telegram_message", new=AsyncMock()) as mock_send:

        await transcribe_and_reply(
            event_id=event_id,
            local_path="/tmp/voice.ogg",
            chat_id=chat_id,
            telegram_bot_token="TOKEN",
            session_factory=_make_session_factory(),
            facade=_make_facade(),
        )

    mock_chat.assert_awaited_once()
    call_text = mock_chat.call_args[0][0]
    assert call_text == transcript

    mock_send.assert_awaited_once_with("TOKEN", chat_id, reply_text)
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

    with patch("app.workers.transcribe._transcribe_file", new=AsyncMock(return_value=transcript)), \
         patch("app.workers.transcribe.handle_chat", new=AsyncMock(return_value="Some reply")) as mock_chat, \
         patch("app.workers.transcribe.update_voice_media_event_status", new=AsyncMock()), \
         patch("app.workers.transcribe._send_telegram_message", new=AsyncMock()):

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


# ---------------------------------------------------------------------------
# AC-3: Provider failure is recoverable and observable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_and_reply_sends_error_on_transcription_failure() -> None:
    """When Whisper fails, user gets an error message and event status is 'failed'."""
    event_id = uuid.uuid4()

    with patch("app.workers.transcribe._transcribe_file", new=AsyncMock(side_effect=RuntimeError("API error"))), \
         patch("app.workers.transcribe.handle_chat", new=AsyncMock()) as mock_chat, \
         patch("app.workers.transcribe.update_voice_media_event_status", new=AsyncMock()) as mock_update, \
         patch("app.workers.transcribe._send_telegram_message", new=AsyncMock()) as mock_send:

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

    with patch("app.workers.transcribe._transcribe_file", new=AsyncMock(return_value="transcript")), \
         patch("app.workers.transcribe.handle_chat", new=AsyncMock(side_effect=RuntimeError("LLM down"))), \
         patch("app.workers.transcribe.update_voice_media_event_status", new=AsyncMock()) as mock_update, \
         patch("app.workers.transcribe._send_telegram_message", new=AsyncMock()) as mock_send:

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
    with patch("app.workers.transcribe._transcribe_file", new=AsyncMock(return_value="text")), \
         patch("app.workers.transcribe.handle_chat", new=AsyncMock(return_value="ok")), \
         patch("app.workers.transcribe.update_voice_media_event_status", new=AsyncMock()) as mock_update, \
         patch("app.workers.transcribe._send_telegram_message", new=AsyncMock()):

        await transcribe_and_reply(
            event_id=uuid.uuid4(),
            local_path="/tmp/ok.ogg",
            chat_id=1,
            telegram_bot_token="TOK",
            session_factory=_make_session_factory(),
            facade=_make_facade(),
        )

    statuses = [call[0][2] for call in mock_update.call_args_list]
    assert "transcribed" in statuses
    assert "done" in statuses
    assert statuses.index("transcribed") < statuses.index("done")
