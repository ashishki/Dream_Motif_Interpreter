from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import logging
import os
import re
import uuid
from collections.abc import MutableMapping
from datetime import date
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import ApplicationHandlerStop, ContextTypes

from app.assistant.chat import ChatResult, handle_chat_with_metadata
from app.assistant.facade import AssistantFacade, DreamRecordingUnavailable
from app.assistant.facade import _prepare_dream_recording_input
from app.assistant.session import (
    DisplayedDreamRef,
    RedisOperationalStateStore,
    clear_pending_batch_dream_note,
    clear_pending_interpretation_request,
    clear_pending_dream_draft,
    clear_pending_single_dream_note,
    load_displayed_dream_message,
    load_displayed_dream_set,
    load_recent_dream_set,
    load_pending_batch_dream_note,
    load_pending_interpretation_request,
    load_pending_dream_draft,
    load_pending_single_dream_note,
    pop_pending_interpretation_request,
    save_displayed_dream_message,
    save_displayed_dream_set,
    save_pending_batch_dream_note,
    save_pending_dream_draft,
    save_pending_interpretation_request,
    save_pending_single_dream_note,
)
from app.assistant.tools import (
    _has_natural_dream_opening,
    _is_explicit_create_request,
    _split_natural_dream_followup,
)
from app.assistant.voice_media import get_voice_transcript_for_message
from app.assistant.voice_media import get_or_create_voice_media_event
from app.assistant.voice_media import store_voice_media_path
from app.assistant.voice_media import update_voice_media_event_status
from app.llm.client import LLMClientError
from app.services.feedback_service import FeedbackService
from app.shared.config import get_settings
from app.telegram.voice import download_voice_file

LOGGER = logging.getLogger(__name__)
GENERIC_ERROR_MESSAGE = "Что-то пошло не так. Попробуйте ещё раз."
VOICE_PROCESSING_ACK = "Обрабатываю голосовое сообщение..."
VOICE_RUNTIME_UNAVAILABLE = (
    "Сейчас я не могу надёжно принять голосовое сообщение. "
    "Пришлите его текстом или повторите позже."
)
VOICE_DOWNLOAD_FAILED = (
    "Не удалось скачать голосовое сообщение. Я ничего не добавил в архив. "
    "Отправьте его ещё раз или пришлите текстом."
)
NOTE_ACCEPTED_QUEUED_MESSAGE = (
    "Заметка сохранена и принята в очередь. Семантический индекс и Google Docs обновятся в фоне."
)
FEEDBACK_PROMPT = "Ответьте 1–5, можно с коротким комментарием."
FEEDBACK_ACK = "Спасибо, записал."
MINI_APP_OPEN_MESSAGE = "Карта памяти снов"
MINI_APP_OPEN_BUTTON = "Открыть карту"
MINI_APP_UNCONFIGURED_MESSAGE = "Карта памяти снов пока не настроена."
FULL_DREAM_CALLBACK_PREFIX = "dream_full:"
ADD_NOTE_CALLBACK_PREFIX = "dream_note:"
BATCH_NOTE_CALLBACK_PREFIX = "batch_note:"
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
MISSING_DREAM_TEXT_REPLY = "Пришлите текст сна одним сообщением: например, «Запиши сон: ...»."
START_MESSAGE = (
    "Я помогаю вести личный архив снов.\n\n"
    "Напишите «Мне приснилось…» — я сохраню сон и покажу дату, название и статус "
    "Google Docs. Можно также прислать голосовое сообщение.\n\n"
    "После сохранения можно искать сны обычными словами, открывать полный текст и "
    "добавлять заметки. Команда /help покажет короткие примеры."
)
HELP_MESSAGE = (
    "Быстрые примеры:\n"
    "• «Мне приснилось, что я иду по мосту» — сохранить сон.\n"
    "• «Найди сны про воду» — поиск по смыслу.\n"
    "• «Найди слово лестница» — точный поиск.\n"
    "• Ответьте на карточку сна: «заметка: важная деталь» — добавить заметку.\n"
    "• /map — открыть карту мотивов.\n\n"
    "Я не ставлю диагнозы: интерпретации здесь — только осторожные гипотезы."
)
UNKNOWN_CONFIRMATION_REPLY = (
    "Не вижу ожидающего подтверждения — возможно, бот перезапускался или запрос устарел. "
    "Повторите действие целиком, чтобы я точно не выбрал не тот сон."
)
_DIRECT_DREAM_RECORD_COMMAND_RE = re.compile(
    r"(?is)^\s*(?:пожалуйста[,\s]+)?"
    r"(?:(?:можешь|можно|давай|хочу|я\s+хочу)\s+)?"
    r"(?:"
    r"(?:запиши|сохрани|добавь|занеси|записать|сохранить|добавить|занести)"
    r"(?:\s+(?:мой|этот|новый|старый|следующий|прошлый))?\s+сон\b"
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
    "старый",
    "текст",
    "текстом",
}
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_DREAM_ID_FIELD_RE = re.compile(
    r"(?m)(?:^\s*(?:[-*]\s*)?(?:dream_id|result_id):\s*|^Dream\s+)"
    r"(?P<dream_id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\b"
)
_BATCH_NOTE_INTENT_RE = re.compile(
    r"(?is)\b(?:добавь|добавить|оставь|оставить|запиши|записать|сохрани|сохранить)\b"
    r".{0,80}\b(?:заметк|комментар)"
)
_NUMBER_RANGE_RE = re.compile(r"\b(?P<start>\d{1,2})\s*[-–—]\s*(?P<end>\d{1,2})\b")
_NUMBER_RE = re.compile(r"\b\d{1,2}\b")
_QUOTED_TEXT_RE = re.compile(r"[\"«“](?P<text>.+?)[\"»”]")
_ORDINAL_INDEXES = {
    "перв": 1,
    "втор": 2,
    "трет": 3,
    "четверт": 4,
    "пят": 5,
    "шест": 6,
    "седьм": 7,
    "восьм": 8,
    "девят": 9,
    "десят": 10,
}


async def chat_guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_id = context.bot_data["allowed_chat_id"]
    chat = update.effective_chat
    if chat is None:
        return
    if chat.id != allowed_chat_id:
        LOGGER.warning("Dropped update from unauthorized chat_id=%s", chat.id)
        raise ApplicationHandlerStop


async def start_command_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    message = update.effective_message
    if message is not None:
        await message.reply_text(START_MESSAGE)


async def help_command_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    message = update.effective_message
    if message is not None:
        await message.reply_text(HELP_MESSAGE)


async def dream_memory_map_command_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    message = update.effective_message
    if message is None:
        return

    mini_app_url = str(context.bot_data.get("mini_app_url") or "").strip()
    if not mini_app_url:
        await message.reply_text(MINI_APP_UNCONFIGURED_MESSAGE)
        return

    await message.reply_text(
        MINI_APP_OPEN_MESSAGE,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(MINI_APP_OPEN_BUTTON, web_app=WebAppInfo(url=mini_app_url))]]
        ),
    )


async def dream_full_text_callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    if query is None:
        return
    data = str(query.data or "")
    if not data.startswith(FULL_DREAM_CALLBACK_PREFIX):
        return

    with contextlib.suppress(Exception):
        await query.answer()

    raw_id = data.removeprefix(FULL_DREAM_CALLBACK_PREFIX)
    try:
        dream_id = uuid.UUID(raw_id)
    except ValueError:
        if query.message is not None:
            await query.message.reply_text("Не смог распознать, какой сон открыть.")
        return

    detail = await _get_facade(context).get_dream(dream_id)
    if query.message is None:
        return
    if detail is None:
        await query.message.reply_text("Не нашёл этот сон в архиве.")
        return

    sent_message = await _reply_text(query.message, _format_dream_full_text_reply(detail))
    chat = getattr(query.message, "chat", None)
    chat_id = getattr(chat, "id", None)
    message_id = getattr(sent_message, "message_id", None)
    if chat_id is not None and message_id is not None:
        await _save_displayed_dream_message(
            _operational_state_store(context),
            int(chat_id),
            message_id=int(message_id),
            refs=[
                DisplayedDreamRef(
                    index=1,
                    dream_id=str(dream_id),
                    date=str(getattr(detail, "date", "") or ""),
                    title=str(getattr(detail, "title", "") or ""),
                )
            ],
        )


async def add_note_callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Turn the save-card action into an unambiguous reply target."""
    query = update.callback_query
    if query is None:
        return
    data = str(query.data or "")
    if not data.startswith(ADD_NOTE_CALLBACK_PREFIX):
        return

    with contextlib.suppress(Exception):
        await query.answer()

    raw_id = data.removeprefix(ADD_NOTE_CALLBACK_PREFIX)
    try:
        dream_id = uuid.UUID(raw_id)
    except ValueError:
        if query.message is not None:
            await query.message.reply_text("Не смог распознать сон для заметки.")
        return

    message = query.message
    chat = update.effective_chat
    if message is None or chat is None:
        return
    detail = await _get_facade(context).get_dream(dream_id)
    if detail is None:
        await message.reply_text("Не нашёл этот сон в архиве.")
        return

    date_value = str(getattr(detail, "date", "") or "").strip()
    title = str(getattr(detail, "title", "") or "без названия").strip()
    label = ", ".join(part for part in (date_value, f"«{title}»") if part)
    sent_message = await message.reply_text(
        f"Добавляем заметку к сну {label}.\nОтветьте на это сообщение: «заметка: …»."
    )
    message_id = getattr(sent_message, "message_id", None)
    if isinstance(message_id, int):
        await _save_displayed_dream_message(
            _operational_state_store(context),
            chat.id,
            message_id=message_id,
            refs=[
                DisplayedDreamRef(
                    index=1,
                    dream_id=str(dream_id),
                    date=date_value,
                    title=title,
                )
            ],
        )


async def batch_note_callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    if query is None:
        return
    data = str(query.data or "")
    if not data.startswith(BATCH_NOTE_CALLBACK_PREFIX):
        return

    with contextlib.suppress(Exception):
        await query.answer()

    message = query.message
    chat = update.effective_chat
    if message is None or chat is None:
        return

    action = data.removeprefix(BATCH_NOTE_CALLBACK_PREFIX)
    state_store = _operational_state_store(context)
    if action == "cancel":
        clear_pending_batch_dream_note(chat.id)
        if state_store is not None:
            await state_store.delete_pending_batch_note(chat.id)
        await message.reply_text("Хорошо, не добавляю заметку.")
        return
    if action != "confirm":
        await message.reply_text("Не смог распознать действие с заметкой.")
        return

    reply = await _apply_pending_batch_note(
        chat.id,
        _get_facade(context),
        state_store=state_store,
    )
    await message.reply_text(reply)


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
    source_event_key = _telegram_source_event_key(
        chat_id,
        getattr(message, "message_id", None),
    )
    reply_to_msg_id = getattr(getattr(message, "reply_to_message", None), "message_id", None)
    session_factory = context.bot_data.get("session_factory")
    state_store = _operational_state_store(context)

    if not feedback_enabled and chat_key is not None:
        pending_feedback.pop(chat_key, None)
        bot_msg_ids.pop(chat_key, None)

    if chat_id is not None and await _handle_reply_to_voice_save(
        message,
        stripped_text,
        chat_id=chat_id,
        session_factory=session_factory,
        facade=_get_facade(context),
        state_store=state_store,
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
        state_store=state_store,
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
        state_store=state_store,
    ):
        if chat_key is not None:
            pending_feedback.pop(chat_key, None)
            bot_msg_ids.pop(chat_key, None)
        return

    if chat_id is not None and await _handle_pending_batch_note_confirmation(
        message,
        stripped_text,
        chat_id=chat_id,
        facade=_get_facade(context),
        state_store=state_store,
    ):
        if chat_key is not None:
            pending_feedback.pop(chat_key, None)
            bot_msg_ids.pop(chat_key, None)
        return

    if chat_id is not None and await _handle_pending_single_note_target(
        message,
        stripped_text,
        chat_id=chat_id,
        facade=_get_facade(context),
        state_store=state_store,
    ):
        if chat_key is not None:
            pending_feedback.pop(chat_key, None)
            bot_msg_ids.pop(chat_key, None)
        return

    if chat_id is not None and await _try_start_batch_note_confirmation(
        message,
        stripped_text,
        chat_id=chat_id,
        state_store=state_store,
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
        target_dream_id = await _resolve_direct_note_target_dream_id(
            message,
            chat_id,
            state_store=state_store,
        )
        if target_dream_id is None and _direct_note_requires_context(stripped_text):
            pending = save_pending_single_dream_note(chat_id, note_text=direct_note_text)
            if state_store is not None:
                await state_store.save_pending_single_note(chat_id, pending)
            await message.reply_text(
                "Не понял, к какому сну добавить заметку. "
                "Ответьте на сообщение с одним конкретным сном коротко: «к этому»."
            )
            return
        _success, reply = await _get_facade(context).add_dream_note(
            direct_note_text,
            dream_id=target_dream_id,
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
        try:
            created = await _create_dream_with_typing(
                context,
                chat_id,
                _get_facade(context),
                stripped_text,
                source_event_key=source_event_key,
            )
        except DreamRecordingUnavailable as exc:
            await message.reply_text(str(exc))
            return
        await _clear_pending_dream(chat_id, state_store=state_store)
        await _reply_create_dream_and_remember(
            message,
            chat_id,
            created,
            raw_text=stripped_text,
            state_store=state_store,
        )
        return

    if chat_id is not None and _has_natural_dream_opening(stripped_text.casefold()):
        if chat_key is not None:
            pending_feedback.pop(chat_key, None)
            bot_msg_ids.pop(chat_key, None)
        dream_text, followup_question = _split_natural_dream_followup(stripped_text)
        try:
            created = await _create_dream_with_typing(
                context,
                chat_id,
                _get_facade(context),
                dream_text,
                source_event_key=source_event_key,
            )
        except DreamRecordingUnavailable as exc:
            await message.reply_text(str(exc))
            return
        await _clear_pending_dream(chat_id, state_store=state_store)
        await _reply_create_dream_and_remember(
            message,
            chat_id,
            created,
            raw_text=dream_text,
            state_store=state_store,
        )
        if followup_question is not None:
            await message.reply_text(
                f"Вопрос заметил: «{followup_question}»\n"
                "Я сохранил только описание сна. Для бережного разбора напишите "
                "«интерпретируй этот сон» — перед запуском я покажу запрос на подтверждение."
            )
        return

    if _is_unbound_confirmation(stripped_text):
        await message.reply_text(UNKNOWN_CONFIRMATION_REPLY)
        return

    if _is_bare_context_reference(stripped_text):
        await message.reply_text(
            "Не понял, что именно сделать с этим сном. "
            "Если нужно добавить заметку, напишите: «добавь заметку: ...»."
        )
        return

    reply_context_text = _reply_context_text(message)
    if chat_id is not None and reply_context_text and _is_reply_full_text_request(stripped_text):
        dream_ids = _extract_dream_ids_from_text(reply_context_text)
        if dream_ids:
            detail = await _get_facade(context).get_dream(dream_ids[0])
            if detail is not None:
                await _reply_text(message, _format_dream_full_text_reply(detail))
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
        chat_kwargs: dict[str, Any] = {
            "session_factory": session_factory,
            "chat_id": chat_id,
            "operational_state_store": state_store,
        }
        if source_event_key is not None:
            chat_kwargs["source_event_key"] = source_event_key
        result = await handle_chat_with_metadata(
            _message_text_with_reply_context(message, message.text),
            facade,
            **chat_kwargs,
        )
    finally:
        if typing_task is not None:
            typing_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await typing_task
    reply_text = _format_reply_text(result, feedback_enabled=feedback_enabled)
    if _claims_dream_saved_without_create_tool(stripped_text, result):
        reply_text = MISSING_DREAM_TEXT_REPLY
    reply_markup = _full_text_reply_markup(reply_text, result, chat_id=chat_id)
    sent_message = await _reply_text(message, reply_text, reply_markup=reply_markup)
    if chat_id is not None:
        await _remember_displayed_dreams(
            chat_id,
            reply_text,
            result,
            sent_message=sent_message,
            state_store=state_store,
        )

    if chat_id is not None:
        await _maybe_store_pending_dream(
            result,
            message.text,
            chat_id=chat_id,
            source_message_id=getattr(message, "message_id", None),
            source_kind="text",
            state_store=state_store,
        )

    if feedback_enabled and chat_key is not None and _is_substantive_response(result.text):
        _remember_feedback_request(
            pending_feedback,
            bot_msg_ids,
            chat_key=chat_key,
            message_id=int(getattr(sent_message, "message_id", 0)),
            request_text=stripped_text,
            response_text=result.text,
            tool_calls_made=list(result.tool_calls_made),
            dream_ids=list(result.dream_ids),
            has_reply_context=reply_to_msg_id is not None,
        )


async def voice_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Telegram voice messages from the authorized user.

    The acknowledgement is sent only after both the ingress event and downloaded
    path are durable. Telegram update redelivery reuses the unique event and does
    not schedule duplicate transcription.
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
    facade = context.bot_data.get("facade")
    voice = message.voice

    if session_factory is None or not bot_token or not isinstance(facade, AssistantFacade):
        LOGGER.error("Voice ingress rejected because durable runtime is not configured")
        await _reply_voice_text(message, VOICE_RUNTIME_UNAVAILABLE)
        return

    try:
        state, created = await get_or_create_voice_media_event(
            session_factory,
            chat_id=chat.id,
            telegram_message_id=message.message_id,
            telegram_file_id=voice.file_id,
            duration_seconds=voice.duration,
        )
    except Exception:
        LOGGER.exception(
            "Failed to persist voice ingress message_id=%s",
            message.message_id,
        )
        await _reply_voice_text(message, VOICE_RUNTIME_UNAVAILABLE)
        return

    if not created and not (state.status == "received" and not state.local_path):
        LOGGER.info(
            "Duplicate voice update ignored event_id=%s status=%s",
            state.id,
            state.status,
        )
        return

    # Claim even a newly-created row before touching Telegram media. A duplicate
    # update can therefore finish a crash-before-path event, while concurrent
    # deliveries or another bot instance cannot download/process it twice.
    from app.assistant.voice_media import claim_voice_media_event
    from app.workers.transcribe import VOICE_LEASE_SECONDS

    lease_owner = f"ingress:{uuid.uuid4().hex}"[:128]
    claimed = await claim_voice_media_event(
        session_factory,
        state.id,
        lease_owner=lease_owner,
        lease_seconds=VOICE_LEASE_SECONDS,
    )
    if claimed is None:
        LOGGER.info("Voice ingress already claimed event_id=%s", state.id)
        return
    state = claimed

    try:
        local_path = await download_voice_file(
            update,
            context,
            media_dir=media_dir,
            event_id=state.id,
        )
        LOGGER.info(
            "Voice file downloaded event_id=%s path=%s",
            state.id,
            local_path,
        )
    except Exception:
        LOGGER.exception(
            "Voice download failed for message_id=%s event_id=%s",
            message.message_id,
            state.id,
        )
        from app.workers.transcribe import stage_and_deliver_voice_reply

        await stage_and_deliver_voice_reply(
            event_id=state.id,
            chat_id=chat.id,
            telegram_bot_token=bot_token,
            session_factory=session_factory,
            reply_text=VOICE_DOWNLOAD_FAILED,
            local_path="",
            media_dir=media_dir,
            lease_owner=lease_owner,
        )
        return

    try:
        from app.workers.cleanup import resolve_voice_media_path

        resolved_path = resolve_voice_media_path(local_path, media_dir=media_dir)
        if resolved_path is None:
            raise RuntimeError("Downloaded voice path is outside the configured media root")
        local_path = str(resolved_path)
        await store_voice_media_path(
            session_factory,
            state.id,
            local_path,
            lease_owner=lease_owner,
        )
        await update_voice_media_event_status(
            session_factory,
            state.id,
            "processing",
            lease_owner=lease_owner,
        )
    except Exception:
        LOGGER.exception("Failed to persist downloaded voice path event_id=%s", state.id)
        from app.workers.cleanup import delete_local_voice_file

        delete_local_voice_file(local_path, media_dir=media_dir)
        await _reply_voice_text(message, VOICE_RUNTIME_UNAVAILABLE)
        return

    await _reply_voice_text(message, VOICE_PROCESSING_ACK)

    from app.workers.transcribe import run_claimed_voice_event, schedule_voice_task

    schedule_voice_task(
        context.bot_data,
        run_claimed_voice_event(
            bot_data=context.bot_data,
            event_id=state.id,
            lease_owner=lease_owner,
        ),
    )
    LOGGER.info(
        "Transcription task scheduled event_id=%s duration=%ss",
        state.id,
        voice.duration,
    )


async def _reply_voice_text(message: Any, text: str) -> None:
    """Best-effort voice-specific Telegram response without masking durable state."""
    try:
        await message.reply_text(text)
    except TelegramError:
        LOGGER.warning("Failed to send voice ingress reply", exc_info=True)


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


def _operational_state_store(
    context: ContextTypes.DEFAULT_TYPE,
) -> RedisOperationalStateStore | None:
    store = context.bot_data.get("operational_state_store")
    return store if isinstance(store, RedisOperationalStateStore) else None


async def _save_displayed_dream_set(
    state_store: RedisOperationalStateStore | None,
    chat_id: int,
    *,
    refs: list[DisplayedDreamRef],
) -> None:
    displayed = save_displayed_dream_set(chat_id, refs=refs)
    if state_store is not None:
        await state_store.save_displayed_set(chat_id, displayed)


async def _save_displayed_dream_message(
    state_store: RedisOperationalStateStore | None,
    chat_id: int,
    *,
    message_id: int,
    refs: list[DisplayedDreamRef],
) -> None:
    displayed = save_displayed_dream_message(chat_id, message_id=message_id, refs=refs)
    if state_store is not None:
        await state_store.save_displayed_message(chat_id, message_id, displayed)


async def _load_pending_batch_note(
    chat_id: int,
    *,
    state_store: RedisOperationalStateStore | None,
) -> Any:
    pending = load_pending_batch_dream_note(chat_id)
    if pending is None and state_store is not None:
        pending = await state_store.load_pending_batch_note(chat_id)
        if pending is not None:
            save_pending_batch_dream_note(
                chat_id,
                note_text=pending.note_text,
                refs=pending.refs,
            )
    return pending


async def _load_pending_dream(
    chat_id: int,
    *,
    state_store: RedisOperationalStateStore | None,
) -> Any:
    draft = load_pending_dream_draft(chat_id)
    if draft is None and state_store is not None:
        draft = await state_store.load_pending_dream(chat_id)
        if draft is not None:
            save_pending_dream_draft(
                chat_id,
                raw_text=draft.raw_text,
                title=draft.title,
                dream_date=draft.dream_date,
                source_message_id=draft.source_message_id,
                source_kind=draft.source_kind,
            )
    return draft


async def _clear_pending_dream(
    chat_id: int,
    *,
    state_store: RedisOperationalStateStore | None,
) -> None:
    """Clear both caches after a durable save or explicit rejection."""
    clear_pending_dream_draft(chat_id)
    if state_store is None:
        return
    try:
        await state_store.delete_pending_dream(chat_id)
    except Exception:
        # The archive transaction already committed. Keep the user-facing save
        # successful; ingress idempotency still protects a repeated action.
        LOGGER.warning(
            "Could not clear persisted pending dream after capture",
            extra={"chat_id": chat_id},
            exc_info=True,
        )


async def _load_pending_interpretation(
    chat_id: int,
    *,
    state_store: RedisOperationalStateStore | None,
) -> Any:
    request = load_pending_interpretation_request(chat_id)
    if request is None and state_store is not None:
        request = await state_store.load_pending_interpretation(chat_id)
        if request is not None:
            save_pending_interpretation_request(
                chat_id,
                dream_id=request.dream_id,
                prompt=request.prompt,
                source_message_id=request.source_message_id,
            )
    return request


async def _load_pending_single_note(
    chat_id: int,
    *,
    state_store: RedisOperationalStateStore | None,
) -> Any:
    pending = load_pending_single_dream_note(chat_id)
    if pending is None and state_store is not None:
        pending = await state_store.load_pending_single_note(chat_id)
        if pending is not None:
            save_pending_single_dream_note(chat_id, note_text=pending.note_text)
    return pending


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
    request_text: str = "",
    dream_ids: list[str] | None = None,
    has_reply_context: bool = False,
) -> None:
    while len(pending_feedback) >= MAX_PENDING_FEEDBACK_REQUESTS:
        oldest_key = next(iter(pending_feedback))
        pending_feedback.pop(oldest_key, None)
        bot_msg_ids.pop(oldest_key, None)

    settings = get_settings()
    pending_feedback[chat_key] = {
        "message_id": message_id,
        "request_summary": {
            "intent": _feedback_intent(tool_calls_made),
            "chars": len(request_text),
            "words": len(request_text.split()),
            "has_reply_context": has_reply_context,
        },
        "request_hash": _content_hash(request_text),
        "response_summary": {
            "chars": len(response_text),
            "words": len(response_text.split()),
        },
        "response_hash": _content_hash(response_text),
        "tool_calls_made": tool_calls_made,
        "dream_ids": list(dict.fromkeys(str(value) for value in (dream_ids or [])))[:10],
        "build_sha": settings.BUILD_SHA,
        "model": os.environ.get("ASSISTANT_MODEL", "claude-haiku-4-5-20251001"),
        "route": "tool_use" if tool_calls_made else "conversation",
        "issue_categories": [
            "wrong_dream",
            "weak_evidence",
            "transcription",
            "not_saved",
            "duplicate",
        ],
    }
    bot_msg_ids[chat_key] = message_id


def _content_hash(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).strip().casefold()
    payload = b"telegram-feedback-v1\0" + normalized.encode("utf-8")
    return hmac.new(
        get_settings().SECRET_KEY.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()


def _feedback_intent(tool_calls_made: list[str]) -> str:
    calls = set(tool_calls_made)
    if "create_dream" in calls:
        return "capture"
    if "add_dream_note" in calls:
        return "note"
    if calls & {"search_dreams", "search_dreams_exact", "search_dreams_by_title"}:
        return "search"
    if "prepare_dream_interpretation" in calls:
        return "interpretation"
    return "conversation"


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


async def _reply_text(message: Any, text: str, *, reply_markup: Any | None = None) -> Any:
    sent_message: Any = None
    chunks = _split_telegram_text(text)
    for index, chunk in enumerate(chunks):
        kwargs = {"reply_markup": reply_markup} if reply_markup is not None and index == 0 else {}
        sent_message = await message.reply_text(chunk, **kwargs)
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
    state_store: RedisOperationalStateStore | None,
) -> bool:
    normalized = _normalize_confirmation_text(text)
    if not normalized:
        return False

    if _is_negative_confirmation(normalized):
        if await _load_pending_dream(chat_id, state_store=state_store) is None:
            return False
        await _clear_pending_dream(chat_id, state_store=state_store)
        await message.reply_text("Хорошо, не сохраняю.")
        return True

    if not _is_positive_confirmation(normalized):
        return False

    # Do not consume the only copy until the archive transaction succeeds. A
    # database outage must leave the user's text available for another «да».
    draft = await _load_pending_dream(chat_id, state_store=state_store)
    if draft is None:
        return False

    dream_date = date.fromisoformat(draft.dream_date) if draft.dream_date else None
    try:
        create_kwargs: dict[str, Any] = {
            "title": draft.title,
            "dream_date": dream_date,
            "chat_id": chat_id,
        }
        source_event_key = _telegram_source_event_key(chat_id, draft.source_message_id)
        if source_event_key is not None:
            create_kwargs["source_event_key"] = source_event_key
        created = await facade.create_dream(draft.raw_text, **create_kwargs)
    except DreamRecordingUnavailable as exc:
        await message.reply_text(str(exc))
        return True
    await _clear_pending_dream(chat_id, state_store=state_store)
    await _reply_create_dream_and_remember(
        message,
        chat_id,
        created,
        raw_text=draft.raw_text,
        state_store=state_store,
    )
    return True


async def _handle_pending_interpretation_confirmation(
    message: Any,
    text: str,
    *,
    chat_id: int,
    facade: AssistantFacade,
    state_store: RedisOperationalStateStore | None,
) -> bool:
    normalized = _normalize_confirmation_text(text)
    if not normalized:
        return False

    if _is_negative_confirmation(normalized):
        if await _load_pending_interpretation(chat_id, state_store=state_store) is None:
            return False
        clear_pending_interpretation_request(chat_id)
        if state_store is not None:
            await state_store.delete_pending_interpretation(chat_id)
        await message.reply_text("Хорошо, не запускаю интерпретацию.")
        return True

    if not _is_positive_confirmation(normalized):
        return False

    pending = pop_pending_interpretation_request(chat_id)
    if pending is None:
        pending = await _load_pending_interpretation(chat_id, state_store=state_store)
    clear_pending_interpretation_request(chat_id)
    if state_store is not None:
        await state_store.delete_pending_interpretation(chat_id)
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


async def _handle_pending_batch_note_confirmation(
    message: Any,
    text: str,
    *,
    chat_id: int,
    facade: AssistantFacade,
    state_store: RedisOperationalStateStore | None,
) -> bool:
    normalized = _normalize_confirmation_text(text)
    if not normalized:
        return False

    if _is_negative_confirmation(normalized):
        if await _load_pending_batch_note(chat_id, state_store=state_store) is None:
            return False
        clear_pending_batch_dream_note(chat_id)
        if state_store is not None:
            await state_store.delete_pending_batch_note(chat_id)
        await message.reply_text("Хорошо, не добавляю заметку.")
        return True

    if not _is_positive_confirmation(normalized):
        return False

    if await _load_pending_batch_note(chat_id, state_store=state_store) is None:
        return False

    await message.reply_text(
        await _apply_pending_batch_note(chat_id, facade, state_store=state_store)
    )
    return True


async def _handle_pending_single_note_target(
    message: Any,
    text: str,
    *,
    chat_id: int,
    facade: AssistantFacade,
    state_store: RedisOperationalStateStore | None,
) -> bool:
    pending = await _load_pending_single_note(chat_id, state_store=state_store)
    if pending is None:
        return False

    normalized = _normalize_confirmation_text(text)
    if _is_negative_confirmation(normalized):
        clear_pending_single_dream_note(chat_id)
        if state_store is not None:
            await state_store.delete_pending_single_note(chat_id)
        await message.reply_text("Хорошо, не добавляю заметку.")
        return True

    if not (_is_bare_context_reference(text) or _is_positive_confirmation(normalized)):
        return False

    target_dream_id = await _resolve_direct_note_target_dream_id(
        message,
        chat_id,
        state_store=state_store,
    )
    if target_dream_id is None:
        await message.reply_text(
            "Всё ещё не понял, к какому сну добавить заметку. "
            "Ответьте «к этому» именно на сообщение с одним конкретным сном."
        )
        return True

    try:
        success, reply = await facade.add_dream_note(
            pending.note_text,
            dream_id=target_dream_id,
            chat_id=chat_id,
        )
    except Exception:
        LOGGER.exception("Failed to durably save pending single dream note")
        success = False

    if success:
        clear_pending_single_dream_note(chat_id)
        if state_store is not None:
            await state_store.delete_pending_single_note(chat_id)
        await message.reply_text(reply or NOTE_ACCEPTED_QUEUED_MESSAGE)
        return True

    await message.reply_text(
        "Не получилось надёжно сохранить заметку. Запрос сохранён для повтора — "
        "ответьте «к этому» ещё раз."
    )
    return True


async def _try_start_batch_note_confirmation(
    message: Any,
    text: str,
    *,
    chat_id: int,
    state_store: RedisOperationalStateStore | None,
) -> bool:
    pending = await _parse_batch_note_request(
        text,
        chat_id=chat_id,
        state_store=state_store,
    )
    if pending is None:
        return False

    pending_note = save_pending_batch_dream_note(
        chat_id,
        note_text=pending["note_text"],
        refs=pending["refs"],
    )
    if state_store is not None:
        await state_store.save_pending_batch_note(chat_id, pending_note)
    await message.reply_text(
        _format_batch_note_confirmation(
            note_text=pending["note_text"],
            refs=pending["refs"],
        ),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Да, добавить",
                        callback_data=f"{BATCH_NOTE_CALLBACK_PREFIX}confirm",
                    ),
                    InlineKeyboardButton(
                        "Отмена",
                        callback_data=f"{BATCH_NOTE_CALLBACK_PREFIX}cancel",
                    ),
                ]
            ]
        ),
    )
    return True


async def _apply_pending_batch_note(
    chat_id: int,
    facade: AssistantFacade,
    *,
    state_store: RedisOperationalStateStore | None,
) -> str:
    pending = await _load_pending_batch_note(chat_id, state_store=state_store)
    if pending is None:
        return "Не вижу ожидающей заметки. Повтори, пожалуйста, к каким снам её добавить."

    accepted_results: list[tuple[DisplayedDreamRef, str]] = []
    failed_refs: list[DisplayedDreamRef] = []
    for ref in pending.refs:
        try:
            success, result_message = await facade.add_dream_note(
                pending.note_text,
                dream_id=uuid.UUID(ref.dream_id),
                chat_id=chat_id,
            )
        except ValueError:
            success = False
        except Exception:
            LOGGER.exception(
                "Failed to durably save one pending batch dream note",
                extra={"dream_id": ref.dream_id, "chat_id": chat_id},
            )
            success = False

        if success:
            accepted_results.append((ref, result_message))
        else:
            failed_refs.append(ref)

    total = len(pending.refs)
    accepted = len(accepted_results)
    if accepted == total:
        clear_pending_batch_dream_note(chat_id)
        if state_store is not None:
            await state_store.delete_pending_batch_note(chat_id)
        return _format_batch_note_success(
            f"Готово. Заметка для всех выбранных снов ({total}) надёжно сохранена.",
            accepted_results,
        )

    failed_lines = "\n".join(_format_displayed_ref(ref) for ref in failed_refs)
    if accepted:
        return (
            f"Надёжно сохранено {accepted} из {total}. Не получилось сохранить "
            f"для этих снов:\n{failed_lines}\n"
            "Запрос сохранён для повтора; уже принятые заметки не продублируются."
        )
    return (
        "Не получилось надёжно сохранить заметку для выбранных снов. "
        "Запрос сохранён для повтора; уже принятые заметки не продублируются."
    )


def _format_batch_note_success(
    prefix: str,
    accepted_results: list[tuple[DisplayedDreamRef, str]],
) -> str:
    messages = [message.strip() for _ref, message in accepted_results if message.strip()]
    unique_messages = list(dict.fromkeys(messages))
    if not unique_messages:
        return prefix
    if len(unique_messages) == 1:
        return f"{prefix}\n{unique_messages[0]}"

    status_lines = [
        f"{ref.index}. «{ref.title}»: {message.strip()}"
        for ref, message in accepted_results
        if message.strip()
    ]
    return f"{prefix}\n" + "\n".join(status_lines)


async def _parse_batch_note_request(
    text: str,
    *,
    chat_id: int,
    state_store: RedisOperationalStateStore | None,
) -> dict[str, Any] | None:
    displayed = load_displayed_dream_set(chat_id)
    if displayed is None and state_store is not None:
        displayed = await state_store.load_displayed_set(chat_id)
        if displayed is not None:
            save_displayed_dream_set(chat_id, refs=displayed.refs)
    if displayed is None or not displayed.refs:
        return None
    if _BATCH_NOTE_INTENT_RE.search(text) is None:
        return None

    note_text = _extract_batch_note_text(text)
    if note_text is None:
        return None

    selected_refs = _select_displayed_refs_for_batch_note(text, displayed.refs)
    if not selected_refs:
        return None

    return {"note_text": note_text, "refs": selected_refs}


def _extract_batch_note_text(text: str) -> str | None:
    quoted = [match.group("text").strip() for match in _QUOTED_TEXT_RE.finditer(text)]
    if quoted:
        return quoted[-1] or None
    if ":" not in text:
        return None
    note_text = text.rsplit(":", 1)[1].strip(" \t\r\n\"'«»“”")
    return note_text or None


def _select_displayed_refs_for_batch_note(
    text: str,
    refs: list[DisplayedDreamRef],
) -> list[DisplayedDreamRef]:
    lowered = text.casefold()
    if any(marker in lowered for marker in ("ко всем", "к всем", "всем найден", "к этим снам")):
        return list(refs)

    target_text = text.split(":", 1)[0]
    indexes = _extract_referenced_indexes(target_text)
    if not indexes:
        return []

    refs_by_index = {ref.index: ref for ref in refs}
    return [refs_by_index[index] for index in indexes if index in refs_by_index]


def _extract_referenced_indexes(text: str) -> list[int]:
    indexes: list[int] = []
    seen: set[int] = set()

    def add_index(value: int) -> None:
        if value <= 0 or value in seen:
            return
        seen.add(value)
        indexes.append(value)

    for match in _NUMBER_RANGE_RE.finditer(text):
        start = int(match.group("start"))
        end = int(match.group("end"))
        if start <= end:
            values = range(start, end + 1)
        else:
            values = range(start, end - 1, -1)
        for value in values:
            add_index(value)

    without_ranges = _NUMBER_RANGE_RE.sub(" ", text)
    for match in _NUMBER_RE.finditer(without_ranges):
        add_index(int(match.group(0)))

    lowered = without_ranges.casefold()
    for stem, index in _ORDINAL_INDEXES.items():
        if stem in lowered:
            add_index(index)

    return indexes


def _format_batch_note_confirmation(
    *,
    note_text: str,
    refs: list[DisplayedDreamRef],
) -> str:
    lines = [
        f"Я понял так: добавить заметку «{note_text}» к {len(refs)} {_dream_count_word(len(refs))} из последней подборки:",
        *(_format_displayed_ref(ref) for ref in refs),
        "",
        "Добавляю?",
    ]
    return "\n".join(lines)


def _format_displayed_ref(ref: DisplayedDreamRef) -> str:
    date_part = f"{ref.date}, " if ref.date else ""
    title = ref.title or "без названия"
    return f"{ref.index}. {date_part}«{title}»"


def _dream_count_word(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "сну"
    if count % 10 in {2, 3, 4} and count % 100 not in {12, 13, 14}:
        return "снам"
    return "снам"


async def _handle_reply_to_voice_save(
    message: Any,
    text: str,
    *,
    chat_id: int,
    session_factory: Any,
    facade: AssistantFacade,
    state_store: RedisOperationalStateStore | None,
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

    try:
        source_event_key = _telegram_source_event_key(
            chat_id,
            getattr(reply_to, "message_id", None),
        )
        create_kwargs: dict[str, Any] = {"chat_id": chat_id}
        if source_event_key is not None:
            create_kwargs["source_event_key"] = source_event_key
        created = await facade.create_dream(transcript, **create_kwargs)
    except DreamRecordingUnavailable as exc:
        await message.reply_text(str(exc))
        return True
    await _reply_create_dream_and_remember(
        message,
        chat_id,
        created,
        raw_text=transcript,
        state_store=state_store,
    )
    await _clear_pending_dream(chat_id, state_store=state_store)
    return True


async def _maybe_store_pending_dream(
    result: ChatResult,
    raw_text: str,
    *,
    chat_id: int,
    source_message_id: int | None,
    source_kind: str,
    state_store: RedisOperationalStateStore | None,
) -> None:
    if "create_dream" in result.tool_calls_made:
        await _clear_pending_dream(chat_id, state_store=state_store)
        return
    if not _has_natural_dream_opening(raw_text.casefold()):
        return
    if not _is_pending_dream_confirmation_reply(result.text):
        return

    draft = save_pending_dream_draft(
        chat_id,
        raw_text=raw_text,
        title=None,
        dream_date=None,
        source_message_id=source_message_id,
        source_kind=source_kind,
    )
    if state_store is not None:
        await state_store.save_pending_dream(chat_id, draft)


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


async def _create_dream_with_typing(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    facade: AssistantFacade,
    raw_text: str,
    *,
    source_event_key: str | None = None,
) -> Any:
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    typing_task = asyncio.create_task(_send_typing_action_loop(context, chat_id))
    try:
        create_kwargs: dict[str, Any] = {"chat_id": chat_id}
        if source_event_key is not None:
            create_kwargs["source_event_key"] = source_event_key
        return await facade.create_dream(raw_text, **create_kwargs)
    finally:
        typing_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await typing_task


def _telegram_source_event_key(chat_id: object, message_id: object) -> str | None:
    """Return the stable ingress identity for one real Telegram message."""
    if (
        isinstance(chat_id, bool)
        or not isinstance(chat_id, int)
        or isinstance(message_id, bool)
        or not isinstance(message_id, int)
    ):
        return None
    return f"telegram:{chat_id}:message:{message_id}"


def _reply_context_text(message: Any) -> str:
    reply = getattr(message, "reply_to_message", None)
    if reply is None:
        return ""
    value = getattr(reply, "text", None) or getattr(reply, "caption", None) or ""
    return str(value).strip()


def _message_text_with_reply_context(message: Any, message_text: str) -> str:
    context_text = _reply_context_text(message)
    if not context_text:
        return message_text
    context_text = context_text[-2500:]
    return (
        "Контекст сообщения, на которое отвечает пользователь:\n"
        f"{context_text}\n\n"
        "Новое сообщение пользователя:\n"
        f"{message_text}"
    )


def _is_reply_full_text_request(text: str) -> bool:
    lowered = text.casefold()
    return any(
        marker in lowered
        for marker in (
            "полный текст",
            "весь текст",
            "полностью",
            "целиком",
            "full text",
            "complete text",
        )
    )


def _extract_dream_ids_from_text(text: str) -> list[uuid.UUID]:
    raw_ids = [match.group("dream_id") for match in _DREAM_ID_FIELD_RE.finditer(text)]
    if not raw_ids:
        raw_ids = _UUID_RE.findall(text)
    result: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for raw_id in raw_ids:
        try:
            dream_id = uuid.UUID(raw_id)
        except ValueError:
            continue
        if dream_id not in seen:
            seen.add(dream_id)
            result.append(dream_id)
    return result


def _full_text_reply_markup(
    reply_text: str,
    result: ChatResult,
    *,
    chat_id: int | None,
) -> InlineKeyboardMarkup | None:
    dream_ids = _extract_dream_ids_from_text(reply_text)
    if not dream_ids:
        refs = getattr(result, "dream_refs", [])
        dream_ids = _visible_dream_reference_ids(reply_text, refs)
        visible_count = _visible_numbered_result_count(reply_text)
        if refs and visible_count and visible_count <= len(refs) and len(dream_ids) < visible_count:
            dream_ids = _coerce_dream_ids(
                [str(getattr(ref, "dream_id", "") or "") for ref in refs[:visible_count]]
            )
        if not dream_ids and refs:
            return None
    if not dream_ids and not getattr(result, "dream_refs", []):
        dream_ids = _coerce_dream_ids(getattr(result, "dream_ids", []))
    if not dream_ids and chat_id is not None and _should_offer_recent_full_text_buttons(result):
        recent = load_recent_dream_set(chat_id)
        if recent is not None:
            dream_ids = _coerce_dream_ids(recent.dream_ids)
    if not dream_ids:
        return None

    buttons = []
    for index, dream_id in enumerate(dream_ids[:10], start=1):
        label = "Полный текст" if len(dream_ids) == 1 else f"Текст {index}"
        buttons.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"{FULL_DREAM_CALLBACK_PREFIX}{dream_id}",
                )
            ]
        )
    return InlineKeyboardMarkup(buttons)


def _visible_dream_reference_ids(reply_text: str, refs: Any) -> list[uuid.UUID]:
    return _coerce_dream_ids([ref.dream_id for ref in _visible_dream_references(reply_text, refs)])


async def _remember_displayed_dreams(
    chat_id: int,
    reply_text: str,
    result: ChatResult,
    *,
    sent_message: Any | None = None,
    state_store: RedisOperationalStateStore | None,
) -> None:
    refs = _visible_dream_references(reply_text, getattr(result, "dream_refs", []))
    if not refs:
        return
    displayed_refs = [
        DisplayedDreamRef(
            index=index,
            dream_id=ref.dream_id,
            date=ref.date,
            title=ref.title,
        )
        for index, ref in enumerate(refs, start=1)
    ]

    await _save_displayed_dream_set(state_store, chat_id, refs=displayed_refs)
    message_id = getattr(sent_message, "message_id", None)
    if message_id is not None:
        await _save_displayed_dream_message(
            state_store,
            chat_id,
            message_id=int(message_id),
            refs=displayed_refs,
        )


def _visible_dream_references(reply_text: str, refs: Any) -> list[Any]:
    if not isinstance(refs, list):
        return []
    visible_refs: list[Any] = []
    normalized_reply = _normalize_visible_match_text(reply_text)
    for ref in refs:
        dream_id = str(getattr(ref, "dream_id", "") or "").strip()
        if not dream_id:
            continue
        title = str(getattr(ref, "title", "") or "").strip()
        date_value = str(getattr(ref, "date", "") or "").strip()
        if _dream_reference_visible(normalized_reply, title=title, date_value=date_value):
            visible_refs.append(ref)

    if refs:
        visible_count = _visible_numbered_result_count(reply_text)
        if visible_count and visible_count <= len(refs) and len(visible_refs) < visible_count:
            visible_refs = list(refs[:visible_count])

    return visible_refs


def _visible_numbered_result_count(reply_text: str) -> int:
    return len(re.findall(r"(?m)^\s*\d+[\.)]\s+\S", reply_text))


def _dream_reference_visible(normalized_reply: str, *, title: str, date_value: str) -> bool:
    title_normalized = _normalize_visible_match_text(title)
    if (
        title_normalized
        and title_normalized != "без названия"
        and title_normalized in normalized_reply
    ):
        return True
    return any(
        _normalize_visible_match_text(variant) in normalized_reply
        for variant in _date_display_variants(date_value)
        if variant
    )


def _date_display_variants(value: str) -> list[str]:
    stripped = value.strip()
    if not stripped or stripped == "unknown":
        return []
    variants = [stripped]
    match = re.match(r"^(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})$", stripped)
    if match is not None:
        day = match.group("day")
        month = match.group("month")
        year = match.group("year")
        variants.extend([f"{day}.{month}.{year[-2:]}", f"{day}.{month}.{year}"])
    return list(dict.fromkeys(variants))


def _normalize_visible_match_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _should_offer_recent_full_text_buttons(result: ChatResult) -> bool:
    return bool(
        set(result.tool_calls_made)
        & {"search_dreams", "search_dreams_exact", "search_dreams_by_title", "list_recent_dreams"}
    )


def _coerce_dream_ids(raw_ids: list[str]) -> list[uuid.UUID]:
    result: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for raw_id in raw_ids:
        try:
            dream_id = uuid.UUID(str(raw_id))
        except ValueError:
            continue
        if dream_id not in seen:
            seen.add(dream_id)
            result.append(dream_id)
    return result


def _format_dream_full_text_reply(detail: Any) -> str:
    date_value = str(getattr(detail, "date", "") or "").strip()
    title = str(getattr(detail, "title", "") or "без названия").strip()
    raw_text = str(getattr(detail, "raw_text", "") or "").rstrip()
    notes = [str(note).strip() for note in getattr(detail, "notes", []) if str(note).strip()]

    header_parts = [part for part in (date_value, title) if part and part != "unknown"]
    parts = [", ".join(header_parts)] if header_parts else []
    parts.append(raw_text or "В архиве у этого сна пустой текст.")
    if notes:
        parts.append("Заметки:\n" + "\n".join(notes))
    return "\n\n".join(parts)


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


def _is_unbound_confirmation(text: str) -> bool:
    normalized = _normalize_confirmation_text(text)
    return _is_positive_confirmation(normalized) or _is_negative_confirmation(normalized)


async def _resolve_direct_note_target_dream_id(
    message: Any,
    chat_id: int,
    *,
    state_store: RedisOperationalStateStore | None,
) -> uuid.UUID | None:
    reply = getattr(message, "reply_to_message", None)
    reply_message_id = getattr(reply, "message_id", None)
    if reply_message_id is not None:
        displayed = load_displayed_dream_message(chat_id, int(reply_message_id))
        if displayed is None and state_store is not None:
            displayed = await state_store.load_displayed_message(
                chat_id,
                int(reply_message_id),
            )
            if displayed is not None:
                save_displayed_dream_message(
                    chat_id,
                    message_id=int(reply_message_id),
                    refs=displayed.refs,
                )
        dream_id = _single_displayed_ref_dream_id(getattr(displayed, "refs", []))
        if dream_id is not None:
            return dream_id

    reply_context_text = _reply_context_text(message)
    if reply_context_text:
        reply_dream_ids = _extract_dream_ids_from_text(reply_context_text)
        if len(reply_dream_ids) == 1:
            return reply_dream_ids[0]

        # A reply is an explicit target. Falling back to an unrelated "latest"
        # result after a restart can attach a private note to the wrong dream.
        return None

    displayed = load_displayed_dream_set(chat_id)
    if displayed is None and state_store is not None:
        displayed = await state_store.load_displayed_set(chat_id)
        if displayed is not None:
            save_displayed_dream_set(chat_id, refs=displayed.refs)
    return _single_displayed_ref_dream_id(getattr(displayed, "refs", []))


def _single_displayed_ref_dream_id(refs: Any) -> uuid.UUID | None:
    if not isinstance(refs, list) or len(refs) != 1:
        return None
    try:
        return uuid.UUID(str(refs[0].dream_id))
    except (AttributeError, ValueError):
        return None


def _direct_note_requires_context(text: str) -> bool:
    lowered = text.casefold()
    return any(
        marker in lowered
        for marker in (
            "к этому сну",
            "к этому",
            "этому сну",
            "к нему",
            "для этого сна",
            "this dream",
            "that dream",
        )
    )


def _is_bare_context_reference(text: str) -> bool:
    normalized = _normalize_confirmation_text(text)
    return normalized in {
        "к этому",
        "к этому сну",
        "этому",
        "этому сну",
        "к нему",
        "вот к этому",
        "вот к этому сну",
        "сюда",
        "сюда добавь",
    }


async def _reply_create_dream_and_remember(
    message: Any,
    chat_id: int,
    created: Any,
    *,
    raw_text: str,
    state_store: RedisOperationalStateStore | None,
) -> None:
    reply_markup = _create_dream_reply_markup(created)
    kwargs = {"reply_markup": reply_markup} if reply_markup is not None else {}
    sent_message = await message.reply_text(
        _format_create_dream_reply(created, raw_text=raw_text),
        **kwargs,
    )
    await _remember_created_dream(
        chat_id,
        created,
        sent_message=sent_message,
        state_store=state_store,
    )


async def _remember_created_dream(
    chat_id: int,
    created: Any,
    *,
    sent_message: Any | None = None,
    state_store: RedisOperationalStateStore | None,
) -> None:
    dream_id = str(getattr(created, "id", "") or "").strip()
    if not dream_id:
        return
    ref = DisplayedDreamRef(
        index=1,
        dream_id=dream_id,
        date=str(getattr(created, "date", "") or ""),
        title=str(getattr(created, "title", "") or "без названия"),
    )
    await _save_displayed_dream_set(state_store, chat_id, refs=[ref])
    message_id = getattr(sent_message, "message_id", None)
    if isinstance(message_id, int):
        await _save_displayed_dream_message(
            state_store,
            chat_id,
            message_id=message_id,
            refs=[ref],
        )


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
        r"^(?:к|для)\s+(?:(?:последн(?:ему|ий|его)|эт(?:ому|от|ого)|данн(?:ому|ый|ого))\s+)?сн[ау]\b",
        "",
        note_text,
        count=1,
        flags=re.IGNORECASE,
    ).strip(" \t\r\n:—–-,.")
    note_text = re.sub(
        r"^к\s+нему\b",
        "",
        note_text,
        count=1,
        flags=re.IGNORECASE,
    ).strip(" \t\r\n:—–-,.")
    note_text = re.sub(
        r"^to\s+(?:the\s+)?(?:(?:last|latest|previous|this|that)\s+)?dream\b",
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


def _format_create_dream_reply(created: Any, *, raw_text: str | None = None) -> str:
    created_now = bool(getattr(created, "created", False))
    written_to_doc = bool(getattr(created, "written_to_google_doc", False))
    processing_status = str(getattr(created, "processing_status", "") or "").strip()
    semantic_status = str(getattr(created, "semantic_index_status", "") or "").strip()
    google_status = str(getattr(created, "google_doc_write_status", "") or "").strip()
    date_value = _human_dream_date(str(getattr(created, "date", "") or "").strip())
    title = str(getattr(created, "title", "") or "без названия").strip()
    prepared_text = _prepare_dream_recording_input(raw_text or "").raw_text
    snippet = _dream_snippet(prepared_text)

    lines = ["✅ Сон сохранён" if created_now else "ℹ️ Этот сон уже был в архиве"]
    if date_value or title:
        metadata = " · ".join(part for part in (date_value, f"«{title}»") if part)
        lines.append(metadata)
    if snippet:
        lines.extend(("", f"{snippet}"))
    archive_label = "сохранено" if created_now else "без дубля"
    processing_label = {
        "pending": "в очереди",
        "running": "выполняется",
        "retryable": "будет повторена",
        "succeeded": "готово",
        "failed": "нужна проверка",
    }.get(processing_status)
    if processing_label is None and semantic_status:
        processing_label = "готово" if semantic_status == "succeeded" else "в очереди"
    google_label = {
        "pending": "ожидает",
        "succeeded": "добавлено",
        "failed": "нужен повтор",
    }.get(google_status, "добавлено" if written_to_doc else "нужен повтор")

    lines.extend(("", f"Архив: {archive_label}"))
    if processing_label is not None:
        lines.append(f"Обработка: {processing_label}")
    lines.append(f"Google Docs: {google_label}")
    if google_label == "нужен повтор":
        lines.append("Для повтора напишите: «повтори запись в Google Doc». ")
    return "\n".join(lines).rstrip()


def _create_dream_reply_markup(created: Any) -> InlineKeyboardMarkup | None:
    raw_id = str(getattr(created, "id", "") or "").strip()
    try:
        dream_id = uuid.UUID(raw_id)
    except ValueError:
        return None
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Полный текст",
                    callback_data=f"{FULL_DREAM_CALLBACK_PREFIX}{dream_id}",
                ),
                InlineKeyboardButton(
                    "Добавить заметку",
                    callback_data=f"{ADD_NOTE_CALLBACK_PREFIX}{dream_id}",
                ),
            ]
        ]
    )


def _dream_snippet(text: str, *, max_chars: int = 220) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return ""
    if len(normalized) <= max_chars:
        return f"«{normalized}»"
    return f"«{normalized[: max_chars - 1].rstrip()}…»"


def _human_dream_date(value: str) -> str:
    match = re.fullmatch(r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})", value)
    if match is None:
        return value
    return f"{match.group('day')}.{match.group('month')}.{match.group('year')[-2:]}"


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
