from __future__ import annotations

import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ApplicationHandlerStop, ContextTypes

from app.assistant.facade import AssistantFacade, SearchResult

LOGGER = logging.getLogger(__name__)
GENERIC_ERROR_MESSAGE = "Something went wrong. Please try again."


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
    result = await facade.search_dreams(message.text)
    await message.reply_text(_format_search_result(result))


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


def _format_search_result(result: SearchResult) -> str:
    if result.insufficient_reason is not None:
        return f"I could not find enough archive evidence for that request: {result.insufficient_reason}."

    if not result.items:
        return "I could not find matching dream archive entries."

    lines = ["Archive matches:"]
    for item in result.items[:3]:
        date_label = item.date.isoformat() if item.date is not None else "unknown-date"
        lines.append(f"- {date_label} [{item.relevance_score:.2f}] {item.chunk_text}")
    return "\n".join(lines)
