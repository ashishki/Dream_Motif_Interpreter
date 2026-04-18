"""Async transcription worker for Telegram voice messages.

Transcribes a downloaded voice file using the OpenAI Whisper API (managed),
then routes the resulting transcript through the standard text assistant path
so the user receives an archive-grounded response.

Provider failure is observable and recoverable: the user receives an error
message and the VoiceMediaEvent status is updated to 'failed'.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.assistant.chat import handle_chat
from app.assistant.facade import AssistantFacade
from app.assistant.voice_media import update_voice_media_event_status
from app.workers.cleanup import delete_local_voice_file

LOGGER = logging.getLogger(__name__)

_WHISPER_MODEL = "whisper-1"
_TRANSCRIPTION_FAILED_MESSAGE = (
    "I could not transcribe your voice note. "
    "The audio has been saved — please try again or send your message as text."
)


async def transcribe_and_reply(
    *,
    event_id: uuid.UUID,
    local_path: str,
    chat_id: int,
    telegram_bot_token: str,
    session_factory: async_sessionmaker[AsyncSession],
    facade: AssistantFacade,
) -> None:
    """Transcribe the voice file at local_path and route through the text assistant.

    This function is intended to run as a background asyncio.Task started from the
    Telegram voice handler after the ack has been sent to the user.

    Steps:
    1. Transcribe local audio file via OpenAI Whisper API.
    2. Route transcript through handle_chat (same path as text messages).
    3. Send assistant reply to the user via Bot.send_message.
    4. On any failure: send error message, update event status to 'failed'.
    """
    try:
        transcript = await _transcribe_file(local_path)
    except Exception:
        LOGGER.exception("Transcription failed for event_id=%s path=%s", event_id, local_path)
        await update_voice_media_event_status(session_factory, event_id, "failed")
        await _send_telegram_message(telegram_bot_token, chat_id, _TRANSCRIPTION_FAILED_MESSAGE)
        return

    LOGGER.info("Transcription succeeded event_id=%s chars=%s", event_id, len(transcript))
    await update_voice_media_event_status(session_factory, event_id, "transcribed")

    try:
        reply = await handle_chat(
            transcript,
            facade,
            session_factory=session_factory,
            chat_id=chat_id,
        )
    except Exception:
        LOGGER.exception("handle_chat failed after transcription for event_id=%s", event_id)
        await update_voice_media_event_status(session_factory, event_id, "failed")
        await _send_telegram_message(telegram_bot_token, chat_id, _TRANSCRIPTION_FAILED_MESSAGE)
        return

    await update_voice_media_event_status(session_factory, event_id, "done")
    delete_local_voice_file(local_path)
    await _send_telegram_message(telegram_bot_token, chat_id, reply)


async def _transcribe_file(local_path: str) -> str:
    """Call the OpenAI Whisper API in a thread and return the transcript text."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set — transcription unavailable")

    return await asyncio.to_thread(_call_whisper_api, local_path, api_key)


def _call_whisper_api(local_path: str, api_key: str) -> str:
    """Synchronous Whisper API call (runs in a thread via asyncio.to_thread)."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    path = Path(local_path)
    with path.open("rb") as audio_file:
        response = client.audio.transcriptions.create(
            model=_WHISPER_MODEL,
            file=audio_file,
        )
    return response.text.strip()


async def _send_telegram_message(bot_token: str, chat_id: int, text: str) -> None:
    """Send a Telegram message via the Bot API without requiring the full Application context."""
    from telegram import Bot

    try:
        bot = Bot(token=bot_token)
        await bot.send_message(chat_id=chat_id, text=text)
    except Exception:
        LOGGER.exception("Failed to send Telegram reply for chat_id=%s", chat_id)
