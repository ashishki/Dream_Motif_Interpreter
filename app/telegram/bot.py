from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa

from telegram import ReactionTypeCustomEmoji, ReactionTypeEmoji, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    MessageReactionHandler,
    TypeHandler,
    filters,
)

from app.assistant.facade import AssistantFacade
from app.assistant.session import RedisOperationalStateStore
from app.models.reaction import MessageReaction
from app.shared.config import Settings, get_settings
from app.telegram.handlers import (
    ADD_NOTE_CALLBACK_PREFIX,
    BATCH_NOTE_CALLBACK_PREFIX,
    add_note_callback_handler,
    batch_note_callback_handler,
    chat_guard,
    dream_memory_map_command_handler,
    FULL_DREAM_CALLBACK_PREFIX,
    dream_full_text_callback_handler,
    error_handler,
    help_command_handler,
    start_command_handler,
    text_message_handler,
    voice_message_handler,
)
from app.workers.dream_supervisor import (
    dream_processing_wake_handler,
    start_dream_processing_supervisor,
    stop_dream_processing_supervisor,
)

LOGGER = logging.getLogger(__name__)

_DEPENDENCY_CHECK_TIMEOUT_SECONDS = 5.0
_STARTUP_SWEEP_TIMEOUT_SECONDS = 30.0
_APPLICATION_SHUTDOWN_TIMEOUT_SECONDS = 40.0
_RUNTIME_RESOURCES_CLOSED_KEY = "_telegram_runtime_resources_closed"


async def post_init(application: Application) -> None:
    LOGGER.info("Telegram bot initialized for the configured private chat")
    from app.workers.transcribe import (
        resume_pending_voice_jobs,
        run_voice_retention_cycle,
        start_voice_maintenance_supervisor,
    )

    try:
        await _validate_runtime_dependencies(application)
        facade = application.bot_data.get("facade")
        if isinstance(facade, AssistantFacade):
            await facade.start_background_workers()

        try:
            await asyncio.wait_for(
                run_voice_retention_cycle(application),
                timeout=_STARTUP_SWEEP_TIMEOUT_SECONDS,
            )
        except Exception:
            LOGGER.exception("Operational retention cleanup failed during Telegram startup")

        # A transient failure in the immediate recovery sweep must not disable
        # every later retry.  Dependency validation above still happens before
        # this call can schedule any per-event tasks.
        try:
            await asyncio.wait_for(
                resume_pending_voice_jobs(application),
                timeout=_STARTUP_SWEEP_TIMEOUT_SECONDS,
            )
        except Exception:
            LOGGER.exception("Initial voice job recovery failed during Telegram startup")

        start_voice_maintenance_supervisor(application)
        start_dream_processing_supervisor(application)
    except BaseException:
        # PTB does not promise to call post_stop when post_init itself fails.
        # Roll back any supervisor or per-event task created by a partial start,
        # and close transports owned by this application before propagating.
        await _bounded_runtime_shutdown(application, reason="startup rollback")
        raise


async def post_stop(application: Application) -> None:
    await _bounded_runtime_shutdown(application, reason="shutdown")


async def _validate_runtime_dependencies(application: Application) -> None:
    settings = get_settings()
    production_like = settings.ENV.strip().casefold() in {"production", "staging"}
    bot_data = application.bot_data
    state_store = bot_data.get("operational_state_store")

    if isinstance(state_store, RedisOperationalStateStore):
        try:
            available = await asyncio.wait_for(
                state_store.check_available(),
                timeout=_DEPENDENCY_CHECK_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            available = False
            LOGGER.error("Telegram operational state Redis dependency check timed out")
        bot_data["operational_state_degraded"] = not available
        if not available:
            LOGGER.error(
                "Bot started with degraded restart safety; Redis operational state "
                "must be restored before relying on pending confirmations"
            )
            if production_like:
                raise RuntimeError("Redis operational state is required in production/staging")
    elif production_like:
        raise RuntimeError("Redis operational state store is not configured")

    session_factory = bot_data.get("session_factory")
    facade = bot_data.get("facade")
    bot_token = str(bot_data.get("bot_token", "")).strip()
    if not callable(session_factory):
        raise RuntimeError("Database session factory is required for Telegram supervisors")
    if not isinstance(facade, AssistantFacade):
        raise RuntimeError("Assistant facade is required for Telegram supervisors")
    if not bot_token:
        raise RuntimeError("Telegram bot token is required for voice recovery")

    try:
        await asyncio.wait_for(
            _check_database_connection(session_factory),
            timeout=_DEPENDENCY_CHECK_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        raise RuntimeError("Database dependency check timed out") from exc
    except Exception as exc:
        raise RuntimeError("Database dependency check failed") from exc


async def _check_database_connection(session_factory: Any) -> None:
    async with session_factory() as session:
        await session.execute(sa.text("SELECT 1"))


async def _bounded_runtime_shutdown(application: Application, *, reason: str) -> None:
    try:
        await asyncio.wait_for(
            _shutdown_application_runtime(application),
            timeout=_APPLICATION_SHUTDOWN_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        LOGGER.error(
            "Telegram runtime %s exceeded the %.1fs deadline",
            reason,
            _APPLICATION_SHUTDOWN_TIMEOUT_SECONDS,
        )


async def _shutdown_application_runtime(application: Application) -> None:
    from app.workers.transcribe import stop_voice_maintenance_supervisor

    # Independent supervisors receive the stop signal together.  Resource
    # owners close only after both have reached a safe boundary or been
    # cancelled by their own bounded shutdown logic.
    await _gather_lifecycle_calls(
        ("dream processing supervisor", stop_dream_processing_supervisor(application)),
        ("voice maintenance supervisor", stop_voice_maintenance_supervisor(application)),
    )
    await _close_runtime_resources(application)


async def _close_runtime_resources(application: Application) -> None:
    bot_data = application.bot_data
    if bot_data.get(_RUNTIME_RESOURCES_CLOSED_KEY):
        return
    bot_data[_RUNTIME_RESOURCES_CLOSED_KEY] = True

    close_calls: list[tuple[str, Any]] = []
    facade = bot_data.get("facade")
    facade_shutdown = getattr(facade, "shutdown", None)
    if callable(facade_shutdown):
        close_calls.append(("assistant facade", facade_shutdown()))

    state_store = bot_data.get("operational_state_store")
    state_close = getattr(state_store, "aclose", None)
    if callable(state_close):
        close_calls.append(("operational state Redis", state_close()))

    await _gather_lifecycle_calls(*close_calls)


async def _gather_lifecycle_calls(*calls: tuple[str, Any]) -> None:
    if not calls:
        return

    labels = [label for label, _awaitable in calls]
    results = await asyncio.gather(
        *(awaitable for _label, awaitable in calls),
        return_exceptions=True,
    )
    for label, result in zip(labels, results, strict=True):
        if isinstance(result, BaseException):
            LOGGER.error(
                "%s failed during Telegram lifecycle transition",
                label,
                exc_info=(type(result), result, result.__traceback__),
            )


def build_application(
    facade: AssistantFacade,
    *,
    session_factory: object | None = None,
    voice_media_dir: str = "/tmp/dream_voice",
) -> Application:
    settings = get_settings()
    _validate_bot_settings(settings)

    application = (
        ApplicationBuilder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_stop(post_stop)
        .build()
    )
    application.bot_data["facade"] = facade
    application.bot_data["allowed_chat_id"] = settings.TELEGRAM_ALLOWED_CHAT_ID
    application.bot_data["session_factory"] = session_factory
    application.bot_data["voice_media_dir"] = voice_media_dir
    application.bot_data["bot_token"] = settings.TELEGRAM_BOT_TOKEN
    application.bot_data["mini_app_url"] = settings.TELEGRAM_MINI_APP_URL.strip()
    try:
        application.bot_data["operational_state_store"] = RedisOperationalStateStore.from_url(
            settings.REDIS_URL
        )
    except Exception:
        LOGGER.warning("Telegram operational state will use process memory only", exc_info=True)
        application.bot_data["operational_state_store"] = None

    application.add_handler(TypeHandler(Update, chat_guard), group=-1000)
    application.add_handler(CommandHandler("start", start_command_handler))
    application.add_handler(CommandHandler("help", help_command_handler))
    application.add_handler(CommandHandler("map", dream_memory_map_command_handler))
    application.add_handler(
        CallbackQueryHandler(
            add_note_callback_handler,
            pattern=f"^{ADD_NOTE_CALLBACK_PREFIX}",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            dream_full_text_callback_handler,
            pattern=f"^{FULL_DREAM_CALLBACK_PREFIX}",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            batch_note_callback_handler,
            pattern=f"^{BATCH_NOTE_CALLBACK_PREFIX}",
        )
    )
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    application.add_handler(MessageHandler(filters.VOICE, voice_message_handler))
    application.add_handler(
        MessageReactionHandler(
            handle_message_reaction,
            message_reaction_types=MessageReactionHandler.MESSAGE_REACTION_UPDATED,
        )
    )
    # PTB runs one matching handler per group in ascending order. This final
    # group wakes the durable outbox after capture-capable handlers finish.
    application.add_handler(TypeHandler(Update, dream_processing_wake_handler), group=1000)
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