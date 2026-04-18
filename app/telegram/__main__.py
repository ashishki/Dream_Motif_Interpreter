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

if __name__ == "__main__":
    settings = get_settings()
    session_factory = get_session_factory()
    facade = AssistantFacade(
        session_factory=session_factory,
        rag_query_service=RagQueryService(session_factory=session_factory),
    )
    main(facade, session_factory=session_factory, voice_media_dir=settings.VOICE_MEDIA_DIR)
