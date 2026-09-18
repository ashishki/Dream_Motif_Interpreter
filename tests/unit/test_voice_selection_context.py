"""Voice selection publication is downstream of delivery, not generation."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.assistant.chat import ChatResult, DreamReference
from app.assistant.session import (
    RedisOperationalStateStore,
    DisplayedDreamSet,
    DisplayedDreamRef,
    save_displayed_dream_set,
    load_displayed_dream_set,
    load_displayed_dream_message,
    load_pending_single_dream_note,
)
from app.assistant import session as sessions
from app.workers.transcribe import (
    _stage_voice_selection,
    _publish_voice_selection,
    _build_voice_reply,
    deliver_pending_voice_reply,
)

A, B = (str(uuid.UUID(int=n)) for n in (301, 302))
REPLY = "1. 01.01.26 Мост\n2. 02.01.26 Сад"


class MemoryRedis:
    def __init__(self):
        self.values = {}

    async def set(self, key, value, ex=None):
        assert ex == 7200
        self.values[key] = value

    async def get(self, key):
        return self.values.get(key)

    async def delete(self, key):
        self.values.pop(key, None)


def result(preserve=False):
    refs = [DreamReference(A, "2026-01-01", "Мост"), DreamReference(B, "2026-01-02", "Сад")]
    return ChatResult(
        REPLY,
        ["search_dreams"],
        dream_refs=refs,
        selection_refs=None if preserve else refs,
        preserve_selection=preserve,
    )


def event():
    return NS(
        id=uuid.uuid4(),
        status="reply_pending",
        chat_id=704,
        telegram_message_id=77,
        reply_text=REPLY,
        reply_chunks_delivered=0,
        delivery_attempt_count=0,
    )


@pytest.fixture(autouse=True)
def reset():
    sessions.clear_displayed_dream_set(704)
    sessions.clear_pending_single_dream_note(704)
    yield
    sessions.clear_displayed_dream_set(704)
    sessions.clear_pending_single_dream_note(704)


@pytest.mark.asyncio
async def test_generated_voice_context_is_not_current_before_delivery_and_survives_cache_restart():
    redis = MemoryRedis()
    store = RedisOperationalStateStore(redis)
    await _stage_voice_selection(store, 704, 77, result())
    assert load_displayed_dream_set(704) is None
    assert REPLY not in repr(redis.values)
    sessions._displayed_dream_sets.clear()
    recovered = RedisOperationalStateStore(redis)
    with (
        patch("app.workers.transcribe.get_voice_media_event", new=AsyncMock(return_value=event())),
        patch("app.workers.transcribe._send_telegram_message", new=AsyncMock(return_value=800)),
        patch("app.workers.transcribe.store_voice_delivery_progress", new=AsyncMock()) as cursor,
        patch("app.workers.transcribe.mark_voice_reply_delivered", new=AsyncMock()) as delivered,
    ):
        assert await deliver_pending_voice_reply(
            event_id=uuid.uuid4(),
            chat_id=704,
            telegram_bot_token="test-token",
            session_factory=MagicMock(),
            state_store=recovered,
        )
    cursor.assert_awaited_once()
    delivered.assert_awaited_once()
    assert [r.dream_id for r in load_displayed_dream_set(704).refs] == [A, B]
    assert [r.dream_id for r in load_displayed_dream_message(704, 800).refs] == [A, B]
    assert not any("voice_selection" in key for key in redis.values)


@pytest.mark.asyncio
async def test_failed_voice_send_does_not_publish_selection_or_consume_pending_metadata():
    redis = MemoryRedis()
    store = RedisOperationalStateStore(redis)
    await _stage_voice_selection(store, 704, 77, result())
    with (
        patch("app.workers.transcribe.get_voice_media_event", new=AsyncMock(return_value=event())),
        patch(
            "app.workers.transcribe._send_telegram_message",
            new=AsyncMock(side_effect=RuntimeError("synthetic timeout")),
        ),
        patch("app.workers.transcribe.mark_voice_reply_delivered", new=AsyncMock()) as delivered,
    ):
        assert not await deliver_pending_voice_reply(
            event_id=uuid.uuid4(),
            chat_id=704,
            telegram_bot_token="test-token",
            session_factory=MagicMock(),
            state_store=store,
        )
    delivered.assert_not_awaited()
    assert load_displayed_dream_set(704) is None
    assert any("voice_selection" in key for key in redis.values)


@pytest.mark.asyncio
async def test_voice_metadata_is_bound_to_exact_staged_reply():
    store = RedisOperationalStateStore(MemoryRedis())
    await _stage_voice_selection(store, 704, 77, result())
    await _publish_voice_selection(store, event(), "a different reply", 800)
    assert load_displayed_dream_set(704) is None


@pytest.mark.asyncio
async def test_expired_voice_metadata_does_not_restore_old_selection():
    store = RedisOperationalStateStore(MemoryRedis())
    displayed = DisplayedDreamSet(
        refs=[DisplayedDreamRef(1, A, "", "Мост")],
        created_at=datetime.now(timezone.utc) - timedelta(hours=3),
    )
    digest = hashlib.sha256(REPLY.encode()).hexdigest()
    await store.save_voice_selection(
        704, 77, displayed=displayed, reply_digest=digest, preserve=False
    )
    assert await store.load_voice_selection(704, 77, reply_digest=digest) is None


@pytest.mark.asyncio
async def test_voice_analysis_preserves_existing_selection_identity():
    store = RedisOperationalStateStore(MemoryRedis())
    selected = save_displayed_dream_set(704, refs=[DisplayedDreamRef(1, B, "", "Сад")])
    await _stage_voice_selection(store, 704, 77, result(preserve=True))
    await _publish_voice_selection(store, event(), REPLY, 800)
    assert load_displayed_dream_set(704).selection_id == selected.selection_id


@pytest.mark.asyncio
async def test_voice_code_targets_one_displayed_dream_without_using_llm():
    save_displayed_dream_set(704, refs=[DisplayedDreamRef(1, B, "", "Сад")])
    facade = AsyncMock()
    facade.add_dream_note.return_value = (True, "Сохранено")
    with patch("app.workers.transcribe.handle_chat_with_metadata", new=AsyncMock()) as llm:
        reply = await _build_voice_reply(
            "Добавь код: возвращение", chat_id=704, session_factory=MagicMock(), facade=facade
        )
    assert reply == "Сохранено"
    facade.add_dream_note.assert_awaited_once_with(
        "#возвращение", dream_id=uuid.UUID(B), chat_id=704
    )
    llm.assert_not_awaited()


@pytest.mark.asyncio
async def test_ambiguous_voice_code_waits_for_target_and_does_not_write():
    save_displayed_dream_set(
        704,
        refs=[DisplayedDreamRef(i, identity, "", "Сон") for i, identity in enumerate([A, B], 1)],
    )
    facade = AsyncMock()
    reply = await _build_voice_reply(
        "Добавь код: возвращение", chat_id=704, session_factory=MagicMock(), facade=facade
    )
    facade.add_dream_note.assert_not_awaited()
    assert "К какому" in reply
    assert load_pending_single_dream_note(704).note_text == "#возвращение"
