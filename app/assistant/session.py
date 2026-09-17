"""Persistent session storage for the Telegram bot assistant.

One session per chat_id. Stores the recent conversation history as a JSON list
so the assistant maintains context across process restarts.
Session history is operational state — it is separate from the dream archive.
"""

from __future__ import annotations

import inspect
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.session import BotSession

LOGGER = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 20
HISTORY_TTL_DAYS = 7
HISTORY_TTL_SECONDS = HISTORY_TTL_DAYS * 24 * 60 * 60
PENDING_DREAM_TTL_MINUTES = 30
MAX_PENDING_DREAM_DRAFTS = 10_000
PENDING_INTERPRETATION_TTL_MINUTES = 30
MAX_PENDING_INTERPRETATION_REQUESTS = 10_000
RECENT_DREAM_SET_TTL_MINUTES = 120
MAX_RECENT_DREAM_SETS = 10_000
OPERATIONAL_STATE_KEY_PREFIX = "dream_motif:telegram_state"


@dataclass(slots=True)
class PendingDreamDraft:
    raw_text: str
    title: str | None
    dream_date: str | None
    source_message_id: int | None
    source_kind: Literal["text", "voice_transcript"]
    created_at: datetime


@dataclass(slots=True)
class PendingInterpretationRequest:
    dream_id: str
    prompt: str
    source_message_id: int | None
    created_at: datetime


@dataclass(slots=True)
class RecentDreamSet:
    query: str
    dream_ids: list[str]
    created_at: datetime


@dataclass(slots=True)
class DisplayedDreamRef:
    index: int
    dream_id: str
    date: str
    title: str


@dataclass(slots=True)
class DisplayedDreamSet:
    refs: list[DisplayedDreamRef]
    created_at: datetime


@dataclass(slots=True)
class PendingBatchDreamNote:
    note_text: str
    refs: list[DisplayedDreamRef]
    created_at: datetime


@dataclass(slots=True)
class PendingSingleDreamNote:
    note_text: str
    created_at: datetime


class RedisOperationalStateStore:
    """Short-lived Telegram workflow state that survives bot restarts.

    Conversation history belongs in PostgreSQL, while reply targets and pending
    confirmations are deliberately short-lived.  Redis gives those references a
    TTL and avoids turning them into archive data.  Every operation is best
    effort: a Redis outage must not make dream capture unavailable.
    """

    def __init__(
        self, redis_client: Any, *, key_prefix: str = OPERATIONAL_STATE_KEY_PREFIX
    ) -> None:
        self._redis = redis_client
        self._key_prefix = key_prefix.rstrip(":")

    @classmethod
    def from_url(cls, redis_url: str) -> RedisOperationalStateStore:
        from redis import asyncio as aioredis

        return cls(aioredis.from_url(redis_url, decode_responses=True))

    async def save_displayed_set(self, chat_id: int, displayed: DisplayedDreamSet) -> None:
        await self._set(
            self._key(chat_id, "displayed", "latest"),
            _displayed_set_payload(displayed),
            ttl_seconds=RECENT_DREAM_SET_TTL_MINUTES * 60,
        )

    async def load_displayed_set(self, chat_id: int) -> DisplayedDreamSet | None:
        payload = await self._get(self._key(chat_id, "displayed", "latest"))
        return _displayed_set_from_payload(payload)

    async def check_available(self) -> bool:
        try:
            return bool(await self._redis.ping())
        except Exception:
            LOGGER.error(
                "Telegram operational state Redis is unavailable; restart-safe "
                "confirmations are degraded",
                exc_info=True,
            )
            return False

    async def aclose(self) -> None:
        """Close the owned Redis transport during Telegram application shutdown."""
        close = getattr(self._redis, "aclose", None)
        if close is None:
            close = getattr(self._redis, "close", None)
        if not callable(close):
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    async def save_pending_dream(
        self,
        chat_id: int,
        draft: PendingDreamDraft,
    ) -> None:
        await self._set(
            self._key(chat_id, "pending_dream"),
            {
                "raw_text": draft.raw_text,
                "title": draft.title,
                "dream_date": draft.dream_date,
                "source_message_id": draft.source_message_id,
                "source_kind": draft.source_kind,
                "created_at": draft.created_at.isoformat(),
            },
            ttl_seconds=PENDING_DREAM_TTL_MINUTES * 60,
        )

    async def load_pending_dream(self, chat_id: int) -> PendingDreamDraft | None:
        payload = await self._get(self._key(chat_id, "pending_dream"))
        if not isinstance(payload, dict):
            return None
        try:
            draft = PendingDreamDraft(
                raw_text=str(payload["raw_text"]).strip(),
                title=str(payload["title"]) if payload.get("title") is not None else None,
                dream_date=(
                    str(payload["dream_date"]) if payload.get("dream_date") is not None else None
                ),
                source_message_id=(
                    int(payload["source_message_id"])
                    if payload.get("source_message_id") is not None
                    else None
                ),
                source_kind=str(payload["source_kind"]),
                created_at=_parse_utc_datetime(payload["created_at"]),
            )
        except (KeyError, TypeError, ValueError):
            return None
        if draft.source_kind not in {"text", "voice_transcript"}:
            return None
        if datetime.now(tz=timezone.utc) - draft.created_at > timedelta(
            minutes=PENDING_DREAM_TTL_MINUTES
        ):
            return None
        return draft

    async def delete_pending_dream(self, chat_id: int) -> None:
        await self._delete(self._key(chat_id, "pending_dream"))

    async def save_pending_interpretation(
        self,
        chat_id: int,
        request: PendingInterpretationRequest,
    ) -> None:
        await self._set(
            self._key(chat_id, "pending_interpretation"),
            {
                "dream_id": request.dream_id,
                "prompt": request.prompt,
                "source_message_id": request.source_message_id,
                "created_at": request.created_at.isoformat(),
            },
            ttl_seconds=PENDING_INTERPRETATION_TTL_MINUTES * 60,
        )

    async def load_pending_interpretation(
        self,
        chat_id: int,
    ) -> PendingInterpretationRequest | None:
        payload = await self._get(self._key(chat_id, "pending_interpretation"))
        if not isinstance(payload, dict):
            return None
        try:
            request = PendingInterpretationRequest(
                dream_id=str(payload["dream_id"]),
                prompt=str(payload["prompt"]).strip(),
                source_message_id=(
                    int(payload["source_message_id"])
                    if payload.get("source_message_id") is not None
                    else None
                ),
                created_at=_parse_utc_datetime(payload["created_at"]),
            )
        except (KeyError, TypeError, ValueError):
            return None
        if datetime.now(tz=timezone.utc) - request.created_at > timedelta(
            minutes=PENDING_INTERPRETATION_TTL_MINUTES
        ):
            return None
        return request

    async def delete_pending_interpretation(self, chat_id: int) -> None:
        await self._delete(self._key(chat_id, "pending_interpretation"))

    async def save_displayed_message(
        self,
        chat_id: int,
        message_id: int,
        displayed: DisplayedDreamSet,
    ) -> None:
        await self._set(
            self._key(chat_id, "displayed_message", str(message_id)),
            _displayed_set_payload(displayed),
            ttl_seconds=RECENT_DREAM_SET_TTL_MINUTES * 60,
        )

    async def load_displayed_message(
        self,
        chat_id: int,
        message_id: int,
    ) -> DisplayedDreamSet | None:
        payload = await self._get(self._key(chat_id, "displayed_message", str(message_id)))
        return _displayed_set_from_payload(payload)

    async def save_pending_batch_note(
        self,
        chat_id: int,
        pending: PendingBatchDreamNote,
    ) -> None:
        await self._set(
            self._key(chat_id, "pending_batch_note"),
            {
                "note_text": pending.note_text,
                "refs": [_displayed_ref_payload(ref) for ref in pending.refs],
                "created_at": pending.created_at.isoformat(),
            },
            ttl_seconds=PENDING_INTERPRETATION_TTL_MINUTES * 60,
        )

    async def load_pending_batch_note(self, chat_id: int) -> PendingBatchDreamNote | None:
        payload = await self._get(self._key(chat_id, "pending_batch_note"))
        if not isinstance(payload, dict):
            return None
        try:
            refs = [_displayed_ref_from_payload(item) for item in payload.get("refs", [])]
            pending = PendingBatchDreamNote(
                note_text=str(payload["note_text"]).strip(),
                refs=[ref for ref in refs if ref is not None],
                created_at=_parse_utc_datetime(payload["created_at"]),
            )
        except (KeyError, TypeError, ValueError):
            return None
        if datetime.now(tz=timezone.utc) - pending.created_at > timedelta(
            minutes=PENDING_INTERPRETATION_TTL_MINUTES
        ):
            return None
        return pending

    async def delete_pending_batch_note(self, chat_id: int) -> None:
        await self._delete(self._key(chat_id, "pending_batch_note"))

    async def save_pending_single_note(
        self,
        chat_id: int,
        pending: PendingSingleDreamNote,
    ) -> None:
        await self._set(
            self._key(chat_id, "pending_single_note"),
            {
                "note_text": pending.note_text,
                "created_at": pending.created_at.isoformat(),
            },
            ttl_seconds=PENDING_INTERPRETATION_TTL_MINUTES * 60,
        )

    async def load_pending_single_note(self, chat_id: int) -> PendingSingleDreamNote | None:
        payload = await self._get(self._key(chat_id, "pending_single_note"))
        if not isinstance(payload, dict):
            return None
        try:
            pending = PendingSingleDreamNote(
                note_text=str(payload["note_text"]).strip(),
                created_at=_parse_utc_datetime(payload["created_at"]),
            )
        except (KeyError, TypeError, ValueError):
            return None
        if datetime.now(tz=timezone.utc) - pending.created_at > timedelta(
            minutes=PENDING_INTERPRETATION_TTL_MINUTES
        ):
            return None
        return pending

    async def delete_pending_single_note(self, chat_id: int) -> None:
        await self._delete(self._key(chat_id, "pending_single_note"))

    def _key(self, chat_id: int, *parts: str) -> str:
        return ":".join((self._key_prefix, str(chat_id), *parts))

    async def _set(self, key: str, payload: dict[str, Any], *, ttl_seconds: int) -> None:
        try:
            await self._redis.set(
                key,
                json.dumps(payload, ensure_ascii=False),
                ex=ttl_seconds,
            )
        except Exception:
            LOGGER.warning("Could not persist Telegram operational state", exc_info=True)

    async def _get(self, key: str) -> dict[str, Any] | None:
        try:
            raw = await self._redis.get(key)
        except Exception:
            LOGGER.warning("Could not load Telegram operational state", exc_info=True)
            return None
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            payload = json.loads(str(raw))
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    async def _delete(self, key: str) -> None:
        try:
            await self._redis.delete(key)
        except Exception:
            LOGGER.warning("Could not clear Telegram operational state", exc_info=True)


def _displayed_ref_payload(ref: DisplayedDreamRef) -> dict[str, Any]:
    return {
        "index": ref.index,
        "dream_id": ref.dream_id,
        "date": ref.date,
        "title": ref.title,
    }


def _displayed_ref_from_payload(payload: Any) -> DisplayedDreamRef | None:
    if not isinstance(payload, dict):
        return None
    try:
        return DisplayedDreamRef(
            index=int(payload["index"]),
            dream_id=str(payload["dream_id"]),
            date=str(payload.get("date", "")),
            title=str(payload.get("title", "")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _displayed_set_payload(displayed: DisplayedDreamSet) -> dict[str, Any]:
    return {
        "refs": [_displayed_ref_payload(ref) for ref in displayed.refs],
        "created_at": displayed.created_at.isoformat(),
    }


def _displayed_set_from_payload(payload: Any) -> DisplayedDreamSet | None:
    if not isinstance(payload, dict):
        return None
    try:
        refs = [_displayed_ref_from_payload(item) for item in payload.get("refs", [])]
        displayed = DisplayedDreamSet(
            refs=[ref for ref in refs if ref is not None],
            created_at=_parse_utc_datetime(payload["created_at"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
    if datetime.now(tz=timezone.utc) - displayed.created_at > timedelta(
        minutes=RECENT_DREAM_SET_TTL_MINUTES
    ):
        return None
    return displayed


def _parse_utc_datetime(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


_pending_dream_drafts: dict[int, PendingDreamDraft] = {}
_pending_interpretation_requests: dict[int, PendingInterpretationRequest] = {}
_recent_dream_sets: dict[int, RecentDreamSet] = {}
_displayed_dream_sets: dict[int, DisplayedDreamSet] = {}
_displayed_dream_messages: dict[tuple[int, int], DisplayedDreamSet] = {}
_pending_batch_dream_notes: dict[int, PendingBatchDreamNote] = {}
_pending_single_dream_notes: dict[int, PendingSingleDreamNote] = {}


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
            cutoff = datetime.now(tz=timezone.utc) - timedelta(seconds=HISTORY_TTL_SECONDS)
            if updated < cutoff:
                # Delete with the observed timestamp in the predicate.  A concurrent
                # save may refresh this chat between the read and delete; in that
                # case the new history must survive instead of being removed by a
                # stale reader.
                await session.execute(
                    delete(BotSession).where(
                        BotSession.chat_id == chat_id,
                        BotSession.updated_at == updated,
                        BotSession.updated_at < cutoff,
                    )
                )
                await session.commit()
                LOGGER.info("Expired session history removed")
                return []
        try:
            parsed = json.loads(row.history_json)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, TypeError):
            LOGGER.warning("Invalid session JSON encountered; resetting session history")
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


def save_pending_interpretation_request(
    chat_id: int,
    *,
    dream_id: str,
    prompt: str,
    source_message_id: int | None = None,
) -> PendingInterpretationRequest:
    """Store an ephemeral pending interpretation request for yes/no confirmation."""
    _evict_expired_pending_interpretation_requests()
    request = PendingInterpretationRequest(
        dream_id=dream_id,
        prompt=prompt.strip(),
        source_message_id=source_message_id,
        created_at=datetime.now(tz=timezone.utc),
    )
    _pending_interpretation_requests[chat_id] = request
    _evict_excess_pending_interpretation_requests()
    return request


def load_pending_interpretation_request(chat_id: int) -> PendingInterpretationRequest | None:
    """Return the current pending interpretation request for chat_id, if still fresh."""
    _evict_expired_pending_interpretation_requests()
    return _pending_interpretation_requests.get(chat_id)


def pop_pending_interpretation_request(chat_id: int) -> PendingInterpretationRequest | None:
    """Return and remove the current pending interpretation request for chat_id."""
    _evict_expired_pending_interpretation_requests()
    return _pending_interpretation_requests.pop(chat_id, None)


def clear_pending_interpretation_request(chat_id: int) -> None:
    """Remove any pending interpretation request for chat_id."""
    _pending_interpretation_requests.pop(chat_id, None)


def save_recent_dream_set(chat_id: int, *, query: str, dream_ids: list[str]) -> RecentDreamSet:
    """Store the most recent archive search result IDs for follow-up analysis."""
    _evict_expired_recent_dream_sets()
    recent = RecentDreamSet(
        query=query.strip(),
        dream_ids=list(dict.fromkeys(dream_ids)),
        created_at=datetime.now(tz=timezone.utc),
    )
    _recent_dream_sets[chat_id] = recent
    _evict_excess_recent_dream_sets()
    return recent


def load_recent_dream_set(chat_id: int) -> RecentDreamSet | None:
    """Return the recent dream set for chat_id, if still fresh."""
    _evict_expired_recent_dream_sets()
    return _recent_dream_sets.get(chat_id)


def save_displayed_dream_set(
    chat_id: int,
    *,
    refs: list[DisplayedDreamRef],
) -> DisplayedDreamSet:
    """Store the dream list exactly as it was shown to the user."""
    _evict_expired_displayed_dream_sets()
    displayed = DisplayedDreamSet(
        refs=list(refs),
        created_at=datetime.now(tz=timezone.utc),
    )
    _displayed_dream_sets[chat_id] = displayed
    _evict_excess_displayed_dream_sets()
    return displayed


def save_displayed_dream_message(
    chat_id: int,
    *,
    message_id: int,
    refs: list[DisplayedDreamRef],
) -> DisplayedDreamSet:
    """Store dream refs shown in a specific Telegram message for reply context."""
    _evict_expired_displayed_dream_sets()
    displayed = DisplayedDreamSet(
        refs=list(refs),
        created_at=datetime.now(tz=timezone.utc),
    )
    _displayed_dream_messages[(chat_id, message_id)] = displayed
    _evict_excess_displayed_dream_sets()
    return displayed


def load_displayed_dream_set(chat_id: int) -> DisplayedDreamSet | None:
    """Return the last displayed dream list for chat_id, if still fresh."""
    _evict_expired_displayed_dream_sets()
    return _displayed_dream_sets.get(chat_id)


def load_displayed_dream_message(chat_id: int, message_id: int) -> DisplayedDreamSet | None:
    """Return dream refs shown in a specific Telegram message, if still fresh."""
    _evict_expired_displayed_dream_sets()
    return _displayed_dream_messages.get((chat_id, message_id))


def clear_displayed_dream_set(chat_id: int) -> None:
    """Remove the last displayed dream list for chat_id."""
    _displayed_dream_sets.pop(chat_id, None)
    for key in [key for key in _displayed_dream_messages if key[0] == chat_id]:
        _displayed_dream_messages.pop(key, None)


def save_pending_batch_dream_note(
    chat_id: int,
    *,
    note_text: str,
    refs: list[DisplayedDreamRef],
) -> PendingBatchDreamNote:
    """Store a pending multi-dream note until the user confirms it."""
    _evict_expired_pending_batch_dream_notes()
    pending = PendingBatchDreamNote(
        note_text=note_text.strip(),
        refs=list(refs),
        created_at=datetime.now(tz=timezone.utc),
    )
    _pending_batch_dream_notes[chat_id] = pending
    _evict_excess_pending_batch_dream_notes()
    return pending


def load_pending_batch_dream_note(chat_id: int) -> PendingBatchDreamNote | None:
    """Return the pending multi-dream note for chat_id, if still fresh."""
    _evict_expired_pending_batch_dream_notes()
    return _pending_batch_dream_notes.get(chat_id)


def pop_pending_batch_dream_note(chat_id: int) -> PendingBatchDreamNote | None:
    """Return and remove the pending multi-dream note for chat_id."""
    _evict_expired_pending_batch_dream_notes()
    return _pending_batch_dream_notes.pop(chat_id, None)


def clear_pending_batch_dream_note(chat_id: int) -> None:
    """Remove any pending multi-dream note for chat_id."""
    _pending_batch_dream_notes.pop(chat_id, None)


def save_pending_single_dream_note(chat_id: int, *, note_text: str) -> PendingSingleDreamNote:
    """Store a note while waiting for the user to point at one dream."""
    _evict_expired_pending_single_dream_notes()
    pending = PendingSingleDreamNote(
        note_text=note_text.strip(),
        created_at=datetime.now(tz=timezone.utc),
    )
    _pending_single_dream_notes[chat_id] = pending
    _evict_excess_pending_single_dream_notes()
    return pending


def load_pending_single_dream_note(chat_id: int) -> PendingSingleDreamNote | None:
    """Return a pending one-dream note for chat_id, if still fresh."""
    _evict_expired_pending_single_dream_notes()
    return _pending_single_dream_notes.get(chat_id)


def pop_pending_single_dream_note(chat_id: int) -> PendingSingleDreamNote | None:
    """Return and remove a pending one-dream note."""
    _evict_expired_pending_single_dream_notes()
    return _pending_single_dream_notes.pop(chat_id, None)


def clear_pending_single_dream_note(chat_id: int) -> None:
    """Remove any pending one-dream note for chat_id."""
    _pending_single_dream_notes.pop(chat_id, None)


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


def _evict_expired_pending_interpretation_requests(*, now: datetime | None = None) -> None:
    current = now or datetime.now(tz=timezone.utc)
    ttl = timedelta(minutes=PENDING_INTERPRETATION_TTL_MINUTES)
    expired_chat_ids = [
        chat_id
        for chat_id, request in _pending_interpretation_requests.items()
        if current - request.created_at > ttl
    ]
    for chat_id in expired_chat_ids:
        _pending_interpretation_requests.pop(chat_id, None)


def _evict_expired_recent_dream_sets(*, now: datetime | None = None) -> None:
    current = now or datetime.now(tz=timezone.utc)
    ttl = timedelta(minutes=RECENT_DREAM_SET_TTL_MINUTES)
    expired_chat_ids = [
        chat_id
        for chat_id, recent in _recent_dream_sets.items()
        if current - recent.created_at > ttl
    ]
    for chat_id in expired_chat_ids:
        _recent_dream_sets.pop(chat_id, None)


def _evict_expired_displayed_dream_sets(*, now: datetime | None = None) -> None:
    current = now or datetime.now(tz=timezone.utc)
    ttl = timedelta(minutes=RECENT_DREAM_SET_TTL_MINUTES)
    expired_chat_ids = [
        chat_id
        for chat_id, displayed in _displayed_dream_sets.items()
        if current - displayed.created_at > ttl
    ]
    for chat_id in expired_chat_ids:
        _displayed_dream_sets.pop(chat_id, None)
    expired_message_keys = [
        key
        for key, displayed in _displayed_dream_messages.items()
        if current - displayed.created_at > ttl
    ]
    for key in expired_message_keys:
        _displayed_dream_messages.pop(key, None)


def _evict_expired_pending_batch_dream_notes(*, now: datetime | None = None) -> None:
    current = now or datetime.now(tz=timezone.utc)
    ttl = timedelta(minutes=PENDING_INTERPRETATION_TTL_MINUTES)
    expired_chat_ids = [
        chat_id
        for chat_id, pending in _pending_batch_dream_notes.items()
        if current - pending.created_at > ttl
    ]
    for chat_id in expired_chat_ids:
        _pending_batch_dream_notes.pop(chat_id, None)


def _evict_expired_pending_single_dream_notes(*, now: datetime | None = None) -> None:
    current = now or datetime.now(tz=timezone.utc)
    ttl = timedelta(minutes=PENDING_INTERPRETATION_TTL_MINUTES)
    expired_chat_ids = [
        chat_id
        for chat_id, pending in _pending_single_dream_notes.items()
        if current - pending.created_at > ttl
    ]
    for chat_id in expired_chat_ids:
        _pending_single_dream_notes.pop(chat_id, None)


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


def _evict_excess_pending_interpretation_requests() -> None:
    excess = len(_pending_interpretation_requests) - MAX_PENDING_INTERPRETATION_REQUESTS
    if excess <= 0:
        return
    oldest_chat_ids = sorted(
        _pending_interpretation_requests,
        key=lambda chat_id: _pending_interpretation_requests[chat_id].created_at,
    )[:excess]
    for chat_id in oldest_chat_ids:
        _pending_interpretation_requests.pop(chat_id, None)


def _evict_excess_recent_dream_sets() -> None:
    excess = len(_recent_dream_sets) - MAX_RECENT_DREAM_SETS
    if excess <= 0:
        return
    oldest_chat_ids = sorted(
        _recent_dream_sets,
        key=lambda chat_id: _recent_dream_sets[chat_id].created_at,
    )[:excess]
    for chat_id in oldest_chat_ids:
        _recent_dream_sets.pop(chat_id, None)


def _evict_excess_displayed_dream_sets() -> None:
    excess = len(_displayed_dream_sets) + len(_displayed_dream_messages) - MAX_RECENT_DREAM_SETS
    if excess <= 0:
        return
    candidates = [
        ("chat", chat_id, displayed.created_at)
        for chat_id, displayed in _displayed_dream_sets.items()
    ] + [
        ("message", key, displayed.created_at)
        for key, displayed in _displayed_dream_messages.items()
    ]
    for kind, key, _created_at in sorted(candidates, key=lambda item: item[2])[:excess]:
        if kind == "chat":
            _displayed_dream_sets.pop(key, None)
        else:
            _displayed_dream_messages.pop(key, None)


def _evict_excess_pending_batch_dream_notes() -> None:
    excess = len(_pending_batch_dream_notes) - MAX_PENDING_INTERPRETATION_REQUESTS
    if excess <= 0:
        return
    oldest_chat_ids = sorted(
        _pending_batch_dream_notes,
        key=lambda chat_id: _pending_batch_dream_notes[chat_id].created_at,
    )[:excess]
    for chat_id in oldest_chat_ids:
        _pending_batch_dream_notes.pop(chat_id, None)


def _evict_excess_pending_single_dream_notes() -> None:
    excess = len(_pending_single_dream_notes) - MAX_PENDING_INTERPRETATION_REQUESTS
    if excess <= 0:
        return
    oldest_chat_ids = sorted(
        _pending_single_dream_notes,
        key=lambda chat_id: _pending_single_dream_notes[chat_id].created_at,
    )[:excess]
    for chat_id in oldest_chat_ids:
        _pending_single_dream_notes.pop(chat_id, None)
