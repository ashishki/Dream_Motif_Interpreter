from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import MutableMapping
from datetime import date
from typing import Any

from telegram import Update
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import ApplicationHandlerStop, ContextTypes

from app.assistant.chat import ChatResult, handle_chat_with_metadata
from app.assistant.facade import AssistantFacade
from app.assistant.session import (
    clear_pending_dream_draft,
    load_pending_dream_draft,
    pop_pending_dream_draft,
    save_pending_dream_draft,
)
from app.assistant.tools import _has_natural_dream_opening, _is_explicit_create_request
from app.assistant.voice_media import create_voice_media_event
from app.assistant.voice_media import get_voice_transcript_for_message
from app.services.feedback_service import FeedbackService
from app.telegram.voice import download_voice_file

LOGGER = logging.getLogger(__name__)
GENERIC_ERROR_MESSAGE = "Something went wrong. Please try again."
VOICE_PROCESSING_ACK = "Обрабатываю голосовое сообщение..."
FEEDBACK_PROMPT = "Оцените ответ от 1 до 5 или добавьте комментарий после цифры."
FEEDBACK_ACK = "Thanks, noted."
VOICE_TRANSCRIPT_PROCESSING = (
    "Расшифровка голосового сообщения ещё выполняется. Повторите команду после завершения."
)
VOICE_TRANSCRIPT_UNAVAILABLE = (
    "Расшифровка этого голосового сообщения недоступна, поэтому я не могу сохранить сон."
)
_FEEDBACK_STATE_KEY = "_feedback_pending_by_chat"
_BOT_MESSAGE_IDS_KEY = "_bot_message_ids_by_chat"


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
    bot_msg_ids = _bot_message_ids(context)
    stripped_text = message.text.strip()
    reply_to_msg_id = getattr(getattr(message, "reply_to_message", None), "message_id", None)
    session_factory = context.bot_data.get("session_factory")

    if chat_id is not None and await _handle_reply_to_voice_save(
        message,
        stripped_text,
        chat_id=chat_id,
        session_factory=session_factory,
        facade=_get_facade(context),
    ):
        if chat_key is not None:
            pending_feedback.pop(chat_key, None)
            bot_msg_ids.pop(chat_key, None)
        return

    if (
        chat_key is not None
        and reply_to_msg_id is not None
        and reply_to_msg_id == bot_msg_ids.get(chat_key)
    ):
        parsed_feedback = _parse_feedback_reply(stripped_text)
        if (
            parsed_feedback is not None
            and chat_key in pending_feedback
            and session_factory is not None
        ):
            score, comment = parsed_feedback
            feedback_context = pending_feedback.pop(chat_key)
            bot_msg_ids.pop(chat_key, None)
            async with session_factory() as session:
                await FeedbackService().record(
                    chat_key,
                    score,
                    feedback_context,
                    session,
                    comment=comment,
                )
                await session.commit()
            await message.reply_text(FEEDBACK_ACK)
            return

    if (
        chat_key is not None
        and reply_to_msg_id is None
        and _is_rating_message(stripped_text)
        and chat_key in pending_feedback
        and session_factory is not None
    ):
        feedback_context = pending_feedback.pop(chat_key)
        bot_msg_ids.pop(chat_key, None)
        async with session_factory() as session:
            await FeedbackService().record(
                chat_key,
                int(stripped_text),
                feedback_context,
                session,
                comment=None,
            )
            await session.commit()
        await message.reply_text(FEEDBACK_ACK)
        return

    if chat_id is not None and await _handle_pending_dream_confirmation(
        message,
        stripped_text,
        chat_id=chat_id,
        facade=_get_facade(context),
    ):
        if chat_key is not None:
            pending_feedback.pop(chat_key, None)
            bot_msg_ids.pop(chat_key, None)
        return

    if chat_key is not None:
        pending_feedback.pop(chat_key, None)
        bot_msg_ids.pop(chat_key, None)

    facade = _get_facade(context)
    typing_task: asyncio.Task[None] | None = None
    if chat_id is not None:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        typing_task = asyncio.create_task(_send_typing_action_loop(context, chat_id))
    try:
        result = await handle_chat_with_metadata(
            message.text,
            facade,
            session_factory=session_factory,
            chat_id=chat_id,
        )
    finally:
        if typing_task is not None:
            typing_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await typing_task
    reply_text = _format_reply_text(result)
    sent_message = await message.reply_text(reply_text)

    if chat_id is not None:
        _maybe_store_pending_dream(
            result,
            message.text,
            chat_id=chat_id,
            source_message_id=getattr(message, "message_id", None),
            source_kind="text",
        )

    if chat_key is not None and _is_substantive_response(result.text):
        pending_feedback[chat_key] = {
            "message_id": int(getattr(sent_message, "message_id", 0)),
            "response_summary": result.text[:200],
            "tool_calls_made": list(result.tool_calls_made),
        }
        bot_msg_ids[chat_key] = int(getattr(sent_message, "message_id", 0))


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

    chat_key = str(chat.id)
    _feedback_state(context).pop(chat_key, None)
    _bot_message_ids(context).pop(chat_key, None)

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


def _bot_message_ids(context: ContextTypes.DEFAULT_TYPE) -> MutableMapping[str, int]:
    return context.bot_data.setdefault(_BOT_MESSAGE_IDS_KEY, {})


def _is_rating_message(text: str) -> bool:
    return len(text) == 1 and text in "12345"


def _parse_feedback_reply(text: str) -> tuple[int, str | None] | None:
    """Parse reply text as (score, comment) or None if not a feedback reply."""
    parts = text.strip().split(None, 1)
    if not parts:
        return None
    if len(parts[0]) == 1 and parts[0] in "12345":
        score = int(parts[0])
        comment = parts[1].strip() if len(parts) > 1 else None
        return score, comment
    return None


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


async def _handle_pending_dream_confirmation(
    message: Any,
    text: str,
    *,
    chat_id: int,
    facade: AssistantFacade,
) -> bool:
    normalized = _normalize_confirmation_text(text)
    if not normalized:
        return False

    if _is_negative_confirmation(normalized):
        if load_pending_dream_draft(chat_id) is None:
            return False
        clear_pending_dream_draft(chat_id)
        await message.reply_text("Хорошо, не сохраняю.")
        return True

    if not _is_positive_confirmation(normalized):
        return False

    draft = pop_pending_dream_draft(chat_id)
    if draft is None:
        return False

    dream_date = date.fromisoformat(draft.dream_date) if draft.dream_date else None
    created = await facade.create_dream(
        draft.raw_text,
        title=draft.title,
        dream_date=dream_date,
        chat_id=chat_id,
    )
    await message.reply_text(_format_create_dream_reply(created))
    return True


async def _handle_reply_to_voice_save(
    message: Any,
    text: str,
    *,
    chat_id: int,
    session_factory: Any,
    facade: AssistantFacade,
) -> bool:
    reply_to = getattr(message, "reply_to_message", None)
    if reply_to is None or getattr(reply_to, "voice", None) is None:
        return False
    if not _is_explicit_create_request(text):
        return False
    if session_factory is None:
        await message.reply_text(VOICE_TRANSCRIPT_UNAVAILABLE)
        return True

    status, transcript = await get_voice_transcript_for_message(
        session_factory,
        chat_id=chat_id,
        telegram_message_id=int(getattr(reply_to, "message_id", 0)),
    )
    if status in {"received", "processing", "transcribed"} and not transcript:
        await message.reply_text(VOICE_TRANSCRIPT_PROCESSING)
        return True
    if not transcript:
        await message.reply_text(VOICE_TRANSCRIPT_UNAVAILABLE)
        return True

    created = await facade.create_dream(transcript, chat_id=chat_id)
    await message.reply_text(_format_create_dream_reply(created))
    clear_pending_dream_draft(chat_id)
    return True


def _maybe_store_pending_dream(
    result: ChatResult,
    raw_text: str,
    *,
    chat_id: int,
    source_message_id: int | None,
    source_kind: str,
) -> None:
    if "create_dream" in result.tool_calls_made:
        clear_pending_dream_draft(chat_id)
        return
    if not _has_natural_dream_opening(raw_text.casefold()):
        return
    if not _is_pending_dream_confirmation_reply(result.text):
        return

    save_pending_dream_draft(
        chat_id,
        raw_text=raw_text,
        title=None,
        dream_date=None,
        source_message_id=source_message_id,
        source_kind=source_kind,
    )


def _is_pending_dream_confirmation_reply(text: str) -> bool:
    lowered = text.casefold()
    return "?" in lowered and any(
        phrase in lowered
        for phrase in (
            "записать",
            "сохранить",
            "добавить в архив",
            "занести в архив",
        )
    )


def _normalize_confirmation_text(text: str) -> str:
    return text.strip().casefold().strip("!?. ,")


def _is_positive_confirmation(text: str) -> bool:
    return text in {"да", "ага", "ok", "okay", "yes"}


def _is_negative_confirmation(text: str) -> bool:
    return text in {"нет", "не надо", "не нужно"}


def _format_create_dream_reply(created: Any) -> str:
    if not getattr(created, "created", False):
        return "Эта запись уже есть в архиве. В Google Doc повторно не записываю."
    if getattr(created, "written_to_google_doc", False):
        doc_label = getattr(created, "written_to_doc_name", "") or "Google Doc"
        return f"Сон сохранён и добавлен в документ {doc_label}."
    return (
        "Сон сохранён в архиве. "
        "Чтобы повторить запись в Google Doc, скажите «повтори запись в Google Doc»."
    )


async def _send_typing_action_loop(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
) -> None:
    while True:
        await asyncio.sleep(4)
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        except TelegramError:
            LOGGER.warning("Failed to send typing action", exc_info=True)
