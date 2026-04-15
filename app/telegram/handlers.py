from __future__ import annotations

import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ApplicationHandlerStop, ContextTypes

from app.assistant.chat import handle_chat
from app.assistant.facade import AssistantFacade
from app.assistant.voice_media import create_voice_media_event
from app.telegram.voice import download_voice_file

LOGGER = logging.getLogger(__name__)
GENERIC_ERROR_MESSAGE = "Something went wrong. Please try again."
VOICE_PROCESSING_ACK = "Processing your voice note..."


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

    facade = _get_facade(context)
    chat = update.effective_chat
    chat_id = chat.id if chat is not None else None
    session_factory = context.bot_data.get("session_factory")

    reply = await handle_chat(
        message.text,
        facade,
        session_factory=session_factory,
        chat_id=chat_id,
    )
    await message.reply_text(reply)


async def voice_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Telegram voice messages from the authorized user.

    Lifecycle (P7-T01):
    1. Validate voice attachment is present.
    2. Persist VoiceMediaEvent with metadata (AC-2).
    3. Download the file to local temp storage.
    4. Acknowledge that processing has started (AC-3).

    Transcription enqueuing (step 5+) is deferred to P7-T02.
    """
    message = update.effective_message
    chat = update.effective_chat
    if message is None or chat is None or message.voice is None:
        LOGGER.warning("voice_message_handler called without voice attachment")
        return

    session_factory = context.bot_data.get("session_factory")
    media_dir: str = context.bot_data.get("voice_media_dir", "/tmp/dream_voice")
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

    LOGGER.info(
        "Voice ingress complete — transcription pending event_id=%s duration=%ss",
        event_id,
        voice.duration,
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
