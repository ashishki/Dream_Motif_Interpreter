from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import uuid
from collections.abc import MutableMapping
from datetime import date
from typing import Any

from telegram import Update
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import ApplicationHandlerStop, ContextTypes

from app.assistant.chat import ChatResult, handle_chat_with_metadata
from app.assistant.facade import AssistantFacade
from app.assistant.facade import _prepare_dream_recording_input
from app.assistant.session import (
    clear_pending_interpretation_request,
    clear_pending_dream_draft,
    load_pending_interpretation_request,
    load_pending_dream_draft,
    pop_pending_interpretation_request,
    pop_pending_dream_draft,
    save_pending_dream_draft,
)
from app.assistant.tools import _has_natural_dream_opening, _is_explicit_create_request
from app.assistant.voice_media import create_voice_media_event
from app.assistant.voice_media import get_voice_transcript_for_message
from app.llm.client import LLMClientError
from app.services.feedback_service import FeedbackService
from app.shared.config import get_settings
from app.telegram.voice import download_voice_file

LOGGER = logging.getLogger(__name__)
GENERIC_ERROR_MESSAGE = "Something went wrong. Please try again."
VOICE_PROCESSING_ACK = "Обрабатываю голосовое сообщение..."
FEEDBACK_PROMPT = "Ответьте 1–5, можно с коротким комментарием."
FEEDBACK_ACK = "Thanks, noted."
VOICE_TRANSCRIPT_PROCESSING = (
    "Расшифровка голосового сообщения ещё выполняется. Повторите команду после завершения."
)
VOICE_TRANSCRIPT_UNAVAILABLE = (
    "Расшифровка этого голосового сообщения недоступна, поэтому я не могу сохранить сон."
)
_FEEDBACK_STATE_KEY = "_feedback_pending_by_chat"
_BOT_MESSAGE_IDS_KEY = "_bot_message_ids_by_chat"
MAX_PENDING_FEEDBACK_REQUESTS = 10_000
TELEGRAM_MESSAGE_CHUNK_SIZE = 3900
MISSING_DREAM_TEXT_REPLY = (
    "Пришлите текст сна одним сообщением: например, «Запиши сон: ...»."
)
_DIRECT_DREAM_RECORD_COMMAND_RE = re.compile(
    r"(?is)^\s*(?:пожалуйста[,\s]+)?"
    r"(?:(?:можешь|можно|давай|хочу|я\s+хочу)\s+)?"
    r"(?:"
    r"(?:запиши|сохрани|добавь|занеси|записать|сохранить|добавить|занести)"
    r"(?:\s+(?:мой|этот|новый|следующий))?\s+сон\b"
    r"|"
    r"(?:запиши|сохрани|добавь|занеси|записать|сохранить|добавить|занести)"
    r"\s+в\s+архив\b"
    r")"
)
_EMPTY_DREAM_TEXT_WORDS = {
    "архив",
    "гугл",
    "документ",
    "запиши",
    "записать",
    "пожалуйста",
    "сон",
    "текст",
    "текстом",
}


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
    feedback_enabled = _numeric_feedback_enabled(context)
    stripped_text = message.text.strip()
    reply_to_msg_id = getattr(getattr(message, "reply_to_message", None), "message_id", None)
    session_factory = context.bot_data.get("session_factory")

    if not feedback_enabled and chat_key is not None:
        pending_feedback.pop(chat_key, None)
        bot_msg_ids.pop(chat_key, None)

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
        feedback_enabled
        and chat_key is not None
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
            await _record_feedback_safely(
                chat_key=chat_key,
                score=score,
                feedback_context=feedback_context,
                session_factory=session_factory,
                comment=comment,
            )
            await message.reply_text(FEEDBACK_ACK)
            return

    if (
        feedback_enabled
        and chat_key is not None
        and reply_to_msg_id is None
        and _is_rating_message(stripped_text)
        and chat_key in pending_feedback
        and session_factory is not None
    ):
        feedback_context = pending_feedback.pop(chat_key)
        bot_msg_ids.pop(chat_key, None)
        await _record_feedback_safely(
            chat_key=chat_key,
            score=int(stripped_text),
            feedback_context=feedback_context,
            session_factory=session_factory,
            comment=None,
        )
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

    if chat_id is not None and await _handle_pending_interpretation_confirmation(
        message,
        stripped_text,
        chat_id=chat_id,
        facade=_get_facade(context),
    ):
        if chat_key is not None:
            pending_feedback.pop(chat_key, None)
            bot_msg_ids.pop(chat_key, None)
        return

    direct_note_text = _extract_direct_note_text(stripped_text)
    if chat_id is not None and direct_note_text is not None:
        if chat_key is not None:
            pending_feedback.pop(chat_key, None)
            bot_msg_ids.pop(chat_key, None)
        _success, reply = await _get_facade(context).add_dream_note(
            direct_note_text,
            chat_id=chat_id,
        )
        await message.reply_text(reply)
        return

    if chat_id is not None and _is_direct_dream_record_command(stripped_text):
        if chat_key is not None:
            pending_feedback.pop(chat_key, None)
            bot_msg_ids.pop(chat_key, None)
        if not _has_direct_dream_text(stripped_text):
            await message.reply_text(MISSING_DREAM_TEXT_REPLY)
            return
        created = await _get_facade(context).create_dream(stripped_text, chat_id=chat_id)
        clear_pending_dream_draft(chat_id)
        await message.reply_text(_format_create_dream_reply(created))
        return

    if chat_id is not None and _has_natural_dream_opening(stripped_text.casefold()):
        if chat_key is not None:
            pending_feedback.pop(chat_key, None)
            bot_msg_ids.pop(chat_key, None)
        created = await _get_facade(context).create_dream(stripped_text, chat_id=chat_id)
        clear_pending_dream_draft(chat_id)
        await message.reply_text(_format_create_dream_reply(created))
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
    reply_text = _format_reply_text(result, feedback_enabled=feedback_enabled)
    if _claims_dream_saved_without_create_tool(stripped_text, result):
        reply_text = MISSING_DREAM_TEXT_REPLY
    sent_message = await _reply_text(message, reply_text)

    if chat_id is not None:
        _maybe_store_pending_dream(
            result,
            message.text,
            chat_id=chat_id,
            source_message_id=getattr(message, "message_id", None),
            source_kind="text",
        )

    if feedback_enabled and chat_key is not None and _is_substantive_response(result.text):
        _remember_feedback_request(
            pending_feedback,
            bot_msg_ids,
            chat_key=chat_key,
            message_id=int(getattr(sent_message, "message_id", 0)),
            response_text=result.text,
            tool_calls_made=list(result.tool_calls_made),
        )


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


def _numeric_feedback_enabled(context: ContextTypes.DEFAULT_TYPE) -> bool:
    override = context.bot_data.get("numeric_feedback_enabled")
    if override is not None:
        return bool(override)
    try:
        return get_settings().TELEGRAM_NUMERIC_FEEDBACK_ENABLED
    except Exception:
        LOGGER.warning("Could not load Telegram feedback setting", exc_info=True)
        return False


async def _record_feedback_safely(
    *,
    chat_key: str,
    score: int,
    feedback_context: dict[str, Any],
    session_factory: Any,
    comment: str | None,
) -> None:
    try:
        async with session_factory() as session:
            await FeedbackService().record(
                chat_key,
                score,
                feedback_context,
                session,
                comment=comment,
            )
            await session.commit()
    except Exception:
        LOGGER.warning(
            "Failed to persist Telegram feedback",
            extra={"chat_id": chat_key},
            exc_info=True,
        )


def _remember_feedback_request(
    pending_feedback: MutableMapping[str, dict[str, Any]],
    bot_msg_ids: MutableMapping[str, int],
    *,
    chat_key: str,
    message_id: int,
    response_text: str,
    tool_calls_made: list[str],
) -> None:
    while len(pending_feedback) >= MAX_PENDING_FEEDBACK_REQUESTS:
        oldest_key = next(iter(pending_feedback))
        pending_feedback.pop(oldest_key, None)
        bot_msg_ids.pop(oldest_key, None)

    pending_feedback[chat_key] = {
        "message_id": message_id,
        "response_summary": response_text[:200],
        "tool_calls_made": tool_calls_made,
    }
    bot_msg_ids[chat_key] = message_id


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


def _format_reply_text(result: ChatResult, *, feedback_enabled: bool = False) -> str:
    if not feedback_enabled or not _is_substantive_response(result.text):
        return result.text
    return f"{result.text}\n\n{FEEDBACK_PROMPT}"


async def _reply_text(message: Any, text: str) -> Any:
    sent_message: Any = None
    for chunk in _split_telegram_text(text):
        sent_message = await message.reply_text(chunk)
    return sent_message


def _split_telegram_text(
    text: str,
    *,
    chunk_size: int = TELEGRAM_MESSAGE_CHUNK_SIZE,
) -> list[str]:
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > chunk_size:
        split_at = max(
            remaining.rfind("\n\n", 0, chunk_size + 1),
            remaining.rfind("\n", 0, chunk_size + 1),
            remaining.rfind(" ", 0, chunk_size + 1),
        )
        if split_at < chunk_size // 2:
            split_at = chunk_size

        chunk = remaining[:split_at]
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_at:]

    if remaining:
        chunks.append(remaining)
    return chunks


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


async def _handle_pending_interpretation_confirmation(
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
        if load_pending_interpretation_request(chat_id) is None:
            return False
        clear_pending_interpretation_request(chat_id)
        await message.reply_text("Хорошо, не запускаю интерпретацию.")
        return True

    if not _is_positive_confirmation(normalized):
        return False

    pending = pop_pending_interpretation_request(chat_id)
    if pending is None:
        return False

    try:
        result = await facade.interpret_dream_with_prompt(
            dream_id=uuid.UUID(pending.dream_id),
            prompt=pending.prompt,
        )
    except (ValueError, LLMClientError):
        await message.reply_text("Не удалось запустить интерпретацию сна.")
        return True

    if result is None:
        await message.reply_text("Сон для интерпретации не найден.")
        return True

    await message.reply_text(result.text)
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


def _is_direct_dream_record_command(text: str) -> bool:
    return _DIRECT_DREAM_RECORD_COMMAND_RE.match(text) is not None


def _has_direct_dream_text(text: str) -> bool:
    prepared = _prepare_dream_recording_input(text)
    words = re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", prepared.raw_text.casefold())
    if not words:
        return False
    return any(word not in _EMPTY_DREAM_TEXT_WORDS for word in words)


def _claims_dream_saved_without_create_tool(request_text: str, result: ChatResult) -> bool:
    if "create_dream" in result.tool_calls_made:
        return False
    if not _is_explicit_create_request(request_text):
        return False
    lowered = result.text.casefold()
    return any(
        phrase in lowered
        for phrase in (
            "сон сохран",
            "сон запис",
            "записал сон",
            "записала сон",
            "добавлен в документ",
            "добавлена в google doc",
            "запись добавлена",
        )
    )


def _normalize_confirmation_text(text: str) -> str:
    return text.strip().casefold().strip("!?. ,")


def _is_positive_confirmation(text: str) -> bool:
    return text in {"да", "ага", "ok", "okay", "yes"}


def _is_negative_confirmation(text: str) -> bool:
    return text in {"нет", "не надо", "не нужно"}


def _extract_direct_note_text(text: str) -> str | None:
    lowered = text.casefold()
    for prefix in ("note:", "notes:", "заметка:", "заметки:"):
        if lowered.startswith(prefix):
            return text[len(prefix) :].strip()

    russian_match = re.match(
        r"^(?:добавь|добавить|запиши|записать|сохрани|сохранить)\s+"
        r"(?:ещ[её]\s+)?заметк[ауи]\b(?P<tail>.*)$",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if russian_match is not None:
        return _normalize_direct_note_tail(russian_match.group("tail"))

    english_match = re.match(
        r"^(?:add|save|record)\s+(?:another\s+)?note\b(?P<tail>.*)$",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if english_match is not None:
        return _normalize_direct_note_tail(english_match.group("tail"))

    return None


def _normalize_direct_note_tail(text: str) -> str | None:
    note_text = text.strip(" \t\r\n:—–-,.")
    note_text = re.sub(
        r"^(?:к|для)\s+(?:последн(?:ему|ий|его)\s+)?сн[ау]\b",
        "",
        note_text,
        count=1,
        flags=re.IGNORECASE,
    ).strip(" \t\r\n:—–-,.")
    note_text = re.sub(
        r"^to\s+(?:the\s+)?(?:(?:last|latest|previous)\s+)?dream\b",
        "",
        note_text,
        count=1,
        flags=re.IGNORECASE,
    ).strip(" \t\r\n:—–-,.")
    note_text = re.sub(
        r"^(?:о\s+том,?\s+)?(?:что|that)\s+",
        "",
        note_text,
        count=1,
        flags=re.IGNORECASE,
    ).strip()
    return note_text or None


def _format_create_dream_reply(created: Any) -> str:
    if not getattr(created, "created", False):
        if getattr(created, "written_to_google_doc", False):
            return "Сон сохранён и добавлен в документ"
        return (
            "Эта запись уже есть в архиве. "
            "Повторная запись в Google Doc не получилась; попробуйте позже."
        )
    if getattr(created, "written_to_google_doc", False):
        return "Сон сохранён и добавлен в документ"
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
