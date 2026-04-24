"""Persistent session storage for the Telegram bot assistant.

One session per chat_id. Stores the recent conversation history as a JSON list
so the assistant maintains context across process restarts.
Session history is operational state — it is separate from the dream archive.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.session import BotSession

LOGGER = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 20
HISTORY_TTL_DAYS = 7


async def load_history(
    session_factory: async_sessionmaker[AsyncSession],
    chat_id: int,
) -> list[dict[str, Any]]:
    """Return the stored conversation history for this chat, newest-last.

    Returns an empty list if no session exists or if the stored JSON is invalid.
    """
    async with session_factory() as session:
        row = await session.get(BotSession, chat_id)
        if row is None:
            return []
        updated = row.updated_at
        if updated is not None:
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            if datetime.now(tz=timezone.utc) - updated > timedelta(days=HISTORY_TTL_DAYS):
                LOGGER.info("Session history expired for chat_id=%s — resetting", chat_id)
                return []
        try:
            parsed = json.loads(row.history_json)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, TypeError):
            LOGGER.warning("Invalid session JSON for chat_id=%s — resetting", chat_id)
        return []


async def save_history(
    session_factory: async_sessionmaker[AsyncSession],
    chat_id: int,
    history: list[dict[str, Any]],
) -> None:
    """Upsert the conversation history for this chat.

    Trims to MAX_HISTORY_MESSAGES before saving (keeps newest messages).
    """
    trimmed = history[-MAX_HISTORY_MESSAGES:]
    history_json = json.dumps(trimmed)
    now = datetime.now(tz=timezone.utc)

    async with session_factory() as session:
        stmt = (
            insert(BotSession)
            .values(chat_id=chat_id, history_json=history_json, updated_at=now)
            .on_conflict_do_update(
                index_elements=[BotSession.chat_id],
                set_={"history_json": history_json, "updated_at": now},
            )
        )
        await session.execute(stmt)
        await session.commit()
