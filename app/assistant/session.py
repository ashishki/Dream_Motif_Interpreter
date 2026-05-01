"""Persistent session storage for the Telegram bot assistant.

One session per chat_id. Stores the recent conversation history as a JSON list
so the assistant maintains context across process restarts.
Session history is operational state — it is separate from the dream archive.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.session import BotSession

LOGGER = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 20
HISTORY_TTL_DAYS = 7
PENDING_DREAM_TTL_MINUTES = 30
MAX_PENDING_DREAM_DRAFTS = 10_000


@dataclass(slots=True)
class PendingDreamDraft:
    raw_text: str
    title: str | None
    dream_date: str | None
    source_message_id: int | None
    source_kind: Literal["text", "voice_transcript"]
    created_at: datetime


_pending_dream_drafts: dict[int, PendingDreamDraft] = {}


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


def save_pending_dream_draft(
    chat_id: int,
    *,
    raw_text: str,
    title: str | None = None,
    dream_date: str | None = None,
    source_message_id: int | None = None,
    source_kind: Literal["text", "voice_transcript"] = "text",
) -> PendingDreamDraft:
    """Store an ephemeral pending dream draft for later yes/no confirmation."""
    _evict_expired_pending_dream_drafts()
    draft = PendingDreamDraft(
        raw_text=raw_text.strip(),
        title=title,
        dream_date=dream_date,
        source_message_id=source_message_id,
        source_kind=source_kind,
        created_at=datetime.now(tz=timezone.utc),
    )
    _pending_dream_drafts[chat_id] = draft
    _evict_excess_pending_dream_drafts()
    return draft


def load_pending_dream_draft(chat_id: int) -> PendingDreamDraft | None:
    """Return the current pending dream draft for chat_id, if still fresh."""
    _evict_expired_pending_dream_drafts()
    return _pending_dream_drafts.get(chat_id)


def pop_pending_dream_draft(chat_id: int) -> PendingDreamDraft | None:
    """Return and remove the current pending dream draft for chat_id."""
    _evict_expired_pending_dream_drafts()
    return _pending_dream_drafts.pop(chat_id, None)


def clear_pending_dream_draft(chat_id: int) -> None:
    """Remove any pending dream draft for chat_id."""
    _pending_dream_drafts.pop(chat_id, None)


def _evict_expired_pending_dream_drafts(*, now: datetime | None = None) -> None:
    current = now or datetime.now(tz=timezone.utc)
    ttl = timedelta(minutes=PENDING_DREAM_TTL_MINUTES)
    expired_chat_ids = [
        chat_id
        for chat_id, draft in _pending_dream_drafts.items()
        if current - draft.created_at > ttl
    ]
    for chat_id in expired_chat_ids:
        _pending_dream_drafts.pop(chat_id, None)


def _evict_excess_pending_dream_drafts() -> None:
    excess = len(_pending_dream_drafts) - MAX_PENDING_DREAM_DRAFTS
    if excess <= 0:
        return
    oldest_chat_ids = sorted(
        _pending_dream_drafts,
        key=lambda chat_id: _pending_dream_drafts[chat_id].created_at,
    )[:excess]
    for chat_id in oldest_chat_ids:
        _pending_dream_drafts.pop(chat_id, None)
