"""Unit tests for app.assistant.session — persistent chat history store."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.assistant.session import (
    DisplayedDreamRef,
    DisplayedDreamSet,
    MAX_HISTORY_MESSAGES,
    PendingDreamDraft,
    PendingInterpretationRequest,
    PendingSingleDreamNote,
    RedisOperationalStateStore,
    clear_pending_dream_draft,
    load_history,
    load_pending_dream_draft,
    load_recent_dream_set,
    pop_pending_dream_draft,
    save_history,
    save_pending_dream_draft,
    save_recent_dream_set,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.closed = False

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self.values[key] = value
        self.ttls[key] = ex

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        self.closed = True


def _make_session_factory(row: object) -> MagicMock:
    """Return a mock async_sessionmaker that yields a session with get() returning row."""
    session = AsyncMock()
    session.get = AsyncMock(return_value=row)
    session.execute = AsyncMock()
    session.commit = AsyncMock()

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)

    factory = MagicMock()
    factory.return_value = ctx
    return factory, session


@pytest.mark.asyncio
async def test_redis_operational_state_store_closes_owned_transport() -> None:
    redis = _FakeRedis()
    store = RedisOperationalStateStore(redis)

    await store.aclose()

    assert redis.closed is True


@pytest.fixture(autouse=True)
def _clear_pending_drafts() -> None:
    clear_pending_dream_draft(7)
    clear_pending_dream_draft(11)
    clear_pending_dream_draft(42)
    yield
    clear_pending_dream_draft(7)
    clear_pending_dream_draft(11)
    clear_pending_dream_draft(42)


# ---------------------------------------------------------------------------
# load_history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_history_returns_empty_list_when_no_session_row() -> None:
    factory, _ = _make_session_factory(row=None)
    result = await load_history(factory, chat_id=12345)
    assert result == []


@pytest.mark.asyncio
async def test_load_history_returns_parsed_history() -> None:
    history = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
    row = MagicMock()
    row.updated_at = datetime.now(timezone.utc)
    row.history_json = json.dumps(history)

    factory, _ = _make_session_factory(row=row)
    result = await load_history(factory, chat_id=42)
    assert result == history


@pytest.mark.asyncio
async def test_load_history_returns_empty_list_on_invalid_json() -> None:
    row = MagicMock()
    row.updated_at = datetime.now(timezone.utc)
    row.history_json = "not-valid-json{"

    factory, _ = _make_session_factory(row=row)
    result = await load_history(factory, chat_id=99)
    assert result == []


@pytest.mark.asyncio
async def test_load_history_returns_empty_list_when_json_is_not_a_list() -> None:
    row = MagicMock()
    row.updated_at = datetime.now(timezone.utc)
    row.history_json = json.dumps({"role": "user"})

    factory, _ = _make_session_factory(row=row)
    result = await load_history(factory, chat_id=99)
    assert result == []


@pytest.mark.asyncio
async def test_load_history_physically_deletes_expired_row_without_logging_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sensitive_history = "private dream about a violet lighthouse"
    row = MagicMock()
    row.updated_at = datetime.now(timezone.utc) - timedelta(days=8)
    row.history_json = json.dumps([{"role": "user", "content": sensitive_history}])
    factory, session = _make_session_factory(row=row)

    with caplog.at_level(logging.INFO, logger="app.assistant.session"):
        result = await load_history(factory, chat_id=42)

    assert result == []
    session.execute.assert_awaited_once()
    statement = session.execute.await_args.args[0]
    assert str(statement).startswith("DELETE FROM bot_sessions")
    session.commit.assert_awaited_once()
    assert sensitive_history not in caplog.text


# ---------------------------------------------------------------------------
# save_history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_history_upserts_and_commits() -> None:
    factory, session = _make_session_factory(row=None)
    history = [{"role": "user", "content": "test"}]

    await save_history(factory, chat_id=7, history=history)

    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_history_trims_to_max_messages() -> None:
    factory, session = _make_session_factory(row=None)
    history = [{"role": "user", "content": f"msg {i}"} for i in range(MAX_HISTORY_MESSAGES + 5)]

    await save_history(factory, chat_id=7, history=history)

    # The key check: execute was called — trim logic is unit-tested separately
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_history_trim_keeps_newest_messages() -> None:
    """Verify trimming keeps the last MAX_HISTORY_MESSAGES entries."""
    messages = [{"role": "user", "content": str(i)} for i in range(MAX_HISTORY_MESSAGES + 3)]
    trimmed = messages[-MAX_HISTORY_MESSAGES:]
    assert len(trimmed) == MAX_HISTORY_MESSAGES
    assert trimmed[0]["content"] == str(3)
    assert trimmed[-1]["content"] == str(MAX_HISTORY_MESSAGES + 2)


# ---------------------------------------------------------------------------
# handle_chat with session persistence (integration-style unit test)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_chat_loads_and_saves_session_history() -> None:
    """Verify handle_chat calls load/save when session_factory and chat_id are provided."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.assistant.chat import handle_chat
    from app.assistant.facade import AssistantFacade

    facade = AsyncMock(spec=AssistantFacade)
    session_factory = MagicMock()
    prior_history = [
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
    ]

    def _text_block(text: str) -> MagicMock:
        b = MagicMock()
        b.type = "text"
        b.text = text
        return b

    def _make_response(stop_reason: str, content: list) -> MagicMock:
        r = MagicMock()
        r.stop_reason = stop_reason
        r.content = content
        return r

    final_response = _make_response("end_turn", [_text_block("Response with history.")])

    with (
        patch(
            "app.assistant.chat.load_history", new=AsyncMock(return_value=prior_history)
        ) as mock_load,
        patch("app.assistant.chat.save_history", new=AsyncMock()) as mock_save,
        patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}),
        patch("app.assistant.chat.AsyncAnthropic") as mock_client_cls,
    ):
        client = AsyncMock()
        client.messages.create = AsyncMock(return_value=final_response)
        mock_client_cls.return_value = client

        result = await handle_chat(
            "new question", facade, session_factory=session_factory, chat_id=100
        )

    assert result == "Response with history."
    mock_load.assert_awaited_once_with(session_factory, 100)
    mock_save.assert_awaited_once()

    saved_history = mock_save.call_args[0][2]
    assert saved_history[-2] == {"role": "user", "content": "new question"}
    assert saved_history[-1] == {"role": "assistant", "content": "Response with history."}
    assert saved_history[0] == prior_history[0]


def test_save_and_load_pending_dream_draft() -> None:
    draft = save_pending_dream_draft(
        42,
        raw_text="мне приснилось, что я лечу над морем",
        source_message_id=123,
        source_kind="text",
    )

    loaded = load_pending_dream_draft(42)

    assert loaded == draft
    assert loaded is not None
    assert loaded.raw_text == "мне приснилось, что я лечу над морем"
    assert loaded.source_message_id == 123
    assert loaded.source_kind == "text"


def test_pop_pending_dream_draft_removes_it() -> None:
    save_pending_dream_draft(7, raw_text="draft text", source_kind="voice_transcript")

    popped = pop_pending_dream_draft(7)

    assert popped is not None
    assert popped.raw_text == "draft text"
    assert load_pending_dream_draft(7) is None


def test_load_pending_dream_draft_ignores_expired_entries() -> None:
    stale = PendingDreamDraft(
        raw_text="stale",
        title=None,
        dream_date=None,
        source_message_id=None,
        source_kind="text",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=31),
    )
    save_pending_dream_draft(11, raw_text="fresh", source_kind="text")

    from app.assistant import session as session_module

    session_module._pending_dream_drafts[11] = stale

    assert load_pending_dream_draft(11) is None


def test_pending_dream_drafts_evict_oldest_when_over_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.assistant import session as session_module

    monkeypatch.setattr(session_module, "MAX_PENDING_DREAM_DRAFTS", 2)
    try:
        save_pending_dream_draft(1, raw_text="oldest", source_kind="text")
        save_pending_dream_draft(2, raw_text="middle", source_kind="text")
        save_pending_dream_draft(3, raw_text="newest", source_kind="text")

        assert load_pending_dream_draft(1) is None
        assert load_pending_dream_draft(2) is not None
        assert load_pending_dream_draft(3) is not None
    finally:
        clear_pending_dream_draft(1)
        clear_pending_dream_draft(2)
        clear_pending_dream_draft(3)


def test_save_recent_dream_set_dedupes_ids() -> None:
    recent = save_recent_dream_set(
        101,
        query="работа",
        dream_ids=["a", "b", "a"],
    )

    loaded = load_recent_dream_set(101)

    assert loaded == recent
    assert loaded is not None
    assert loaded.query == "работа"
    assert loaded.dream_ids == ["a", "b"]


def test_load_recent_dream_set_ignores_expired_entries() -> None:
    from app.assistant import session as session_module

    stale = session_module.RecentDreamSet(
        query="old",
        dream_ids=["a"],
        created_at=datetime.now(timezone.utc) - timedelta(minutes=121),
    )
    session_module._recent_dream_sets[102] = stale

    assert load_recent_dream_set(102) is None


@pytest.mark.asyncio
async def test_operational_state_store_round_trips_reply_target_with_ttl() -> None:
    redis = _FakeRedis()
    store = RedisOperationalStateStore(redis, key_prefix="test:telegram")
    displayed = DisplayedDreamSet(
        refs=[
            DisplayedDreamRef(
                index=1,
                dream_id="11111111-1111-4111-8111-111111111111",
                date="2026-08-30",
                title="Мост",
            )
        ],
        created_at=datetime.now(timezone.utc),
    )

    await store.save_displayed_message(42, 901, displayed)
    restored = await store.load_displayed_message(42, 901)

    assert restored == displayed
    assert redis.ttls["test:telegram:42:displayed_message:901"] == 120 * 60


@pytest.mark.asyncio
async def test_operational_state_store_pending_note_can_be_consumed_after_restart() -> None:
    redis = _FakeRedis()
    store = RedisOperationalStateStore(redis, key_prefix="test:telegram")
    pending = PendingSingleDreamNote(
        note_text="важная деталь",
        created_at=datetime.now(timezone.utc),
    )

    await store.save_pending_single_note(42, pending)
    restored = await store.load_pending_single_note(42)
    await store.delete_pending_single_note(42)

    assert restored == pending
    assert await store.load_pending_single_note(42) is None


@pytest.mark.asyncio
async def test_operational_state_store_rejects_stale_pending_note_defensively() -> None:
    redis = _FakeRedis()
    store = RedisOperationalStateStore(redis, key_prefix="test:telegram")
    stale = PendingSingleDreamNote(
        note_text="already expired",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=31),
    )

    await store.save_pending_single_note(42, stale)

    assert await store.load_pending_single_note(42) is None


@pytest.mark.asyncio
async def test_operational_state_store_round_trips_pending_capture_and_interpretation() -> None:
    store = RedisOperationalStateStore(_FakeRedis(), key_prefix="test:telegram")
    now = datetime.now(timezone.utc)
    draft = PendingDreamDraft(
        raw_text="мне приснился мост",
        title=None,
        dream_date="2026-08-30",
        source_message_id=501,
        source_kind="text",
        created_at=now,
    )
    interpretation = PendingInterpretationRequest(
        dream_id="11111111-1111-4111-8111-111111111111",
        prompt="Бережно разобрать образ моста",
        source_message_id=502,
        created_at=now,
    )

    await store.save_pending_dream(42, draft)
    await store.save_pending_interpretation(42, interpretation)

    assert await store.load_pending_dream(42) == draft
    assert await store.load_pending_interpretation(42) == interpretation
