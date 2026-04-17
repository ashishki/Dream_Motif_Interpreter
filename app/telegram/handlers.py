from __future__ import annotations

import asyncio
import logging
from collections.abc import MutableMapping
from typing import Any

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ApplicationHandlerStop, ContextTypes

from app.assistant.chat import ChatResult, handle_chat_with_metadata
from app.assistant.facade import AssistantFacade
from app.assistant.voice_media import create_voice_media_event
from app.services.feedback_service import FeedbackService
from app.telegram.voice import download_voice_file

LOGGER = logging.getLogger(__name__)
GENERIC_ERROR_MESSAGE = "Something went wrong. Please try again."
VOICE_PROCESSING_ACK = "Processing your voice note..."
FEEDBACK_PROMPT = "Rate this response: reply with 1–5."
FEEDBACK_ACK = "Thanks, noted."
_FEEDBACK_STATE_KEY = "_feedback_pending_by_chat"


async def chat_guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_id = context.bot_data["allowed_chat_id"]
    chat = update.effective_chat
    if chat is None:
        return
    if chat.id != allowed_chat_id:
        LOGGER.warning("Dropped update from unauthorized chat_id=%s", chat.id)
        raise ApplicationHandlerStop


async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not message.text:
        return

    chat = update.effective_chat
    chat_id = chat.id if chat is not None else None
    chat_key = str(chat_id) if chat_id is not None else None
    pending_feedback = _feedback_state(context)
    stripped_text = message.text.strip()
    session_factory = context.bot_data.get("session_factory")

    if (
        chat_key is not None
        and _is_rating_message(stripped_text)
        and chat_key in pending_feedback
        and session_factory is not None
    ):
        feedback_context = pending_feedback.pop(chat_key)
        async with session_factory() as session:
            await FeedbackService().record(chat_key, int(stripped_text), feedback_context, session)
            await session.commit()
        await message.reply_text(FEEDBACK_ACK)
        return

    if chat_key is not None:
        pending_feedback.pop(chat_key, None)

    facade = _get_facade(context)
    result = await handle_chat_with_metadata(
        message.text,
        facade,
        session_factory=session_factory,
        chat_id=chat_id,
    )
    reply_text = _format_reply_text(result)
    sent_message = await message.reply_text(reply_text)

    if chat_key is not None and _is_substantive_response(result.text):
        pending_feedback[chat_key] = {
            "message_id": int(getattr(sent_message, "message_id", 0)),
            "response_summary": result.text[:200],
            "tool_calls_made": list(result.tool_calls_made),
        }


async def voice_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Telegram voice messages from the authorized user.

    Lifecycle (P7-T01 + P7-T02):
    1. Validate voice attachment is present.
    2. Persist VoiceMediaEvent with metadata (AC-2).
    3. Download the file to local temp storage.
    4. Acknowledge that processing has started (AC-3).
    5. Enqueue async transcription task via asyncio.create_task.
    """
    message = update.effective_message
    chat = update.effective_chat
    if message is None or chat is None or message.voice is None:
        LOGGER.warning("voice_message_handler called without voice attachment")
        return

    _feedback_state(context).pop(str(chat.id), None)

    session_factory = context.bot_data.get("session_factory")
    media_dir: str = context.bot_data.get("voice_media_dir", "/tmp/dream_voice")
    bot_token: str = context.bot_data.get("bot_token", "")
    voice = message.voice

    event_id = None
    if session_factory is not None:
        try:
            event_id = await create_voice_media_event(
                session_factory,
                chat_id=chat.id,
                telegram_message_id=message.message_id,
                telegram_file_id=voice.file_id,
                duration_seconds=voice.duration,
                local_path="",
            )
        except Exception:
            LOGGER.warning(
                "Failed to persist voice media event for message_id=%s",
                message.message_id,
                exc_info=True,
            )

    try:
        local_path = await download_voice_file(update, context, media_dir=media_dir)
        LOGGER.info(
            "Voice file downloaded event_id=%s path=%s",
            event_id,
            local_path,
        )
    except Exception:
        LOGGER.exception(
            "Voice download failed for message_id=%s event_id=%s",
            message.message_id,
            event_id,
        )
        try:
            await message.reply_text("Could not download your voice message. Please try again.")
        except TelegramError:
            pass
        return

    try:
        await message.reply_text(VOICE_PROCESSING_ACK)
    except TelegramError:
        LOGGER.warning("Failed to send voice processing acknowledgement", exc_info=True)

    facade = context.bot_data.get("facade")
    if (
        event_id is not None
        and session_factory is not None
        and bot_token
        and isinstance(facade, AssistantFacade)
    ):
        from app.workers.transcribe import transcribe_and_reply

        task = asyncio.create_task(
            transcribe_and_reply(
                event_id=event_id,
                local_path=local_path,
                chat_id=chat.id,
                telegram_bot_token=bot_token,
                session_factory=session_factory,
                facade=facade,
            )
        )
        context.bot_data.setdefault("_transcription_tasks", set()).add(task)
        task.add_done_callback(context.bot_data["_transcription_tasks"].discard)
        LOGGER.info(
            "Transcription task enqueued event_id=%s duration=%ss",
            event_id,
            voice.duration,
        )
    else:
        LOGGER.info(
            "Voice ingress complete — transcription skipped (missing config) event_id=%s",
            event_id,
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    LOGGER.error("Unhandled Telegram bot error", exc_info=context.error)

    if not isinstance(update, Update):
        return

    message = update.effective_message
    if message is None:
        return

    try:
        await message.reply_text(GENERIC_ERROR_MESSAGE)
    except TelegramError:
        LOGGER.warning("Failed to send generic Telegram error reply", exc_info=True)


def _get_facade(context: ContextTypes.DEFAULT_TYPE) -> AssistantFacade:
    facade = context.bot_data.get("facade")
    if not isinstance(facade, AssistantFacade):
        raise RuntimeError("Telegram bot facade not configured")
    return facade


def _feedback_state(context: ContextTypes.DEFAULT_TYPE) -> MutableMapping[str, dict[str, Any]]:
    return context.bot_data.setdefault(_FEEDBACK_STATE_KEY, {})


def _is_rating_message(text: str) -> bool:
    return len(text) == 1 and text in "12345"


def _is_substantive_response(text: str) -> bool:
    if not text:
        return False
    if text in {GENERIC_ERROR_MESSAGE, VOICE_PROCESSING_ACK, "No response from the assistant."}:
        return False
    return not (
        text.startswith("The assistant is not available:")
        or text.startswith("Something went wrong while contacting the assistant.")
        or text.startswith("Could not download your voice message.")
    )


def _format_reply_text(result: ChatResult) -> str:
    if not _is_substantive_response(result.text):
        return result.text
    return f"{result.text}\n\n{FEEDBACK_PROMPT}"
