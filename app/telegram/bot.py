from __future__ import annotations

import logging
from datetime import datetime, timezone

import sqlalchemy as sa

from telegram import ReactionTypeCustomEmoji, ReactionTypeEmoji, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    MessageHandler,
    MessageReactionHandler,
    TypeHandler,
    filters,
)

from app.assistant.facade import AssistantFacade
from app.models.reaction import MessageReaction
from app.shared.config import Settings, get_settings
from app.telegram.handlers import (
    chat_guard,
    error_handler,
    text_message_handler,
    voice_message_handler,
)

LOGGER = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    allowed_chat_id = application.bot_data["allowed_chat_id"]
    LOGGER.info("Telegram bot initialized for allowed_chat_id=%s", allowed_chat_id)


def build_application(
    facade: AssistantFacade,
    *,
    session_factory: object | None = None,
    voice_media_dir: str = "/tmp/dream_voice",
) -> Application:
    settings = get_settings()
    _validate_bot_settings(settings)

    application = (
        ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    )
    application.bot_data["facade"] = facade
    application.bot_data["allowed_chat_id"] = settings.TELEGRAM_ALLOWED_CHAT_ID
    application.bot_data["session_factory"] = session_factory
    application.bot_data["voice_media_dir"] = voice_media_dir
    application.bot_data["bot_token"] = settings.TELEGRAM_BOT_TOKEN

    application.add_handler(TypeHandler(Update, chat_guard), group=-1000)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    application.add_handler(MessageHandler(filters.VOICE, voice_message_handler))
    application.add_handler(
        MessageReactionHandler(
            handle_message_reaction,
            message_reaction_types=MessageReactionHandler.MESSAGE_REACTION_UPDATED,
        )
    )
    application.add_error_handler(error_handler)
    return application


def main(
    facade: AssistantFacade,
    *,
    session_factory: object | None = None,
    voice_media_dir: str = "/tmp/dream_voice",
) -> None:
    """Start the Telegram bot. Accepts a pre-constructed facade to keep domain imports
    out of the telegram package. Call from app/telegram/__main__.py or tests."""
    settings = get_settings()
    _validate_bot_settings(settings)
    application = build_application(
        facade, session_factory=session_factory, voice_media_dir=voice_media_dir
    )

    LOGGER.info("Starting Telegram bot with long polling")
    try:
        # Verified against the installed python-telegram-bot version: Update.ALL_TYPES
        # already includes UpdateType.MESSAGE_REACTION, so no manual override is needed.
        application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)
    except (KeyboardInterrupt, SystemExit):
        LOGGER.info("Telegram bot shutdown requested")


def _validate_bot_settings(settings: Settings) -> None:
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN must be set to start the Telegram bot runtime")
    if settings.TELEGRAM_ALLOWED_CHAT_ID == 0:
        raise RuntimeError("TELEGRAM_ALLOWED_CHAT_ID must be set to start the Telegram bot runtime")


async def handle_message_reaction(
    update: Update,
    context,
) -> None:
    reaction_update = update.message_reaction
    if reaction_update is None:
        return

    session_factory = context.bot_data.get("session_factory")
    if session_factory is None:
        return

    new_reactions = {
        raw_reaction
        for raw_reaction in (
            _serialize_reaction(reaction) for reaction in reaction_update.new_reaction
        )
        if raw_reaction is not None
    }
    old_reactions = {
        raw_reaction
        for raw_reaction in (
            _serialize_reaction(reaction) for reaction in reaction_update.old_reaction
        )
        if raw_reaction is not None
    }
    if not new_reactions and not old_reactions:
        return

    async with session_factory() as session:
        for raw_reaction in new_reactions - old_reactions:
            session.add(
                MessageReaction(
                    message_id=reaction_update.message_id,
                    chat_id=reaction_update.chat.id,
                    emoji=raw_reaction,
                )
            )

        removed_reactions = old_reactions - new_reactions
        if removed_reactions:
            # Use application UTC time for tombstones so removals are tracked even though the
            # Telegram update does not map to a specific DB row timestamp on the server side.
            await session.execute(
                sa.update(MessageReaction)
                .where(
                    MessageReaction.message_id == reaction_update.message_id,
                    MessageReaction.chat_id == reaction_update.chat.id,
                    MessageReaction.emoji.in_(removed_reactions),
                    MessageReaction.removed_at.is_(None),
                )
                .values(removed_at=datetime.now(timezone.utc))
            )

        await session.commit()


def _serialize_reaction(reaction: object) -> str | None:
    if isinstance(reaction, ReactionTypeEmoji):
        return reaction.emoji
    if isinstance(reaction, ReactionTypeCustomEmoji):
        return reaction.custom_emoji_id
    return None
