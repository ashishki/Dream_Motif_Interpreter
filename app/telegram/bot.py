from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, ApplicationBuilder, MessageHandler, TypeHandler, filters

from app.assistant.facade import AssistantFacade
from app.shared.config import Settings, get_settings
from app.telegram.handlers import chat_guard, error_handler, text_message_handler

LOGGER = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    allowed_chat_id = application.bot_data["allowed_chat_id"]
    LOGGER.info("Telegram bot initialized for allowed_chat_id=%s", allowed_chat_id)


def build_application(facade: AssistantFacade) -> Application:
    settings = get_settings()
    _validate_bot_settings(settings)

    application = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    application.bot_data["facade"] = facade
    application.bot_data["allowed_chat_id"] = settings.TELEGRAM_ALLOWED_CHAT_ID

    application.add_handler(TypeHandler(Update, chat_guard), group=-1000)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    application.add_error_handler(error_handler)
    return application


def main(facade: AssistantFacade) -> None:
    """Start the Telegram bot. Accepts a pre-constructed facade to keep domain imports
    out of the telegram package. Call from app/telegram/__main__.py or tests."""
    settings = get_settings()
    _validate_bot_settings(settings)
    application = build_application(facade)

    LOGGER.info("Starting Telegram bot with long polling")
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)
    except (KeyboardInterrupt, SystemExit):
        LOGGER.info("Telegram bot shutdown requested")


def _validate_bot_settings(settings: Settings) -> None:
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN must be set to start the Telegram bot runtime")
    if settings.TELEGRAM_ALLOWED_CHAT_ID == 0:
        raise RuntimeError("TELEGRAM_ALLOWED_CHAT_ID must be set to start the Telegram bot runtime")
