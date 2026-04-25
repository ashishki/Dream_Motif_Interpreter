"""Entrypoint for the Telegram bot process.

Domain service construction (which requires domain imports) lives here,
outside app/telegram/bot.py, so the telegram package itself does not
import from app.retrieval or other domain modules directly.

Run with:
    python3 -m app.telegram
"""

from __future__ import annotations

from app.assistant.facade import AssistantFacade
from app.retrieval.query import RagQueryService
from app.shared.config import get_settings
from app.shared.database import get_session_factory
from app.telegram.bot import main


def _build_sync_enqueuer(session_factory):
    try:
        from redis import asyncio as aioredis

        from app.api.dreams import LocalAsyncJobEnqueuer

        settings = get_settings()
        redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        return LocalAsyncJobEnqueuer(
            redis_client=redis_client,
            session_factory=session_factory,
        )
    except Exception:
        return None


if __name__ == "__main__":
    settings = get_settings()
    session_factory = get_session_factory()
    sync_enqueuer = _build_sync_enqueuer(session_factory)
    facade = AssistantFacade(
        session_factory=session_factory,
        rag_query_service=RagQueryService(session_factory=session_factory),
        sync_job_enqueuer=sync_enqueuer,
    )
    main(facade, session_factory=session_factory, voice_media_dir=settings.VOICE_MEDIA_DIR)
