from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from telegram import Message, Update, User

from app.assistant.chat import ChatResult
from app.assistant.facade import AssistantFacade, CreatedDreamItem
from app.assistant.session import (
    PendingDreamDraft,
    RedisOperationalStateStore,
    clear_pending_dream_draft,
    load_pending_dream_draft,
)
from app.shared.config import get_settings
from app.telegram.bot import build_application


FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "telegram_conversation_replays.json"
)
PROXY_ENV_KEYS = (
    "ALL_PROXY",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "all_proxy",
    "https_proxy",
    "http_proxy",
)


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, *, ex: int | None = None) -> None:
        del ex
        self.values[key] = value

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)

    async def ping(self) -> bool:
        return True


def _case(case_id: str) -> dict:
    cases = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return next(case for case in cases if case["id"] == case_id)


def _build_application(monkeypatch: pytest.MonkeyPatch) -> tuple[object, AsyncMock]:
    for key in PROXY_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TESTTOKEN")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_ID", "42")
    get_settings.cache_clear()

    facade = AsyncMock(spec=AssistantFacade)
    application = build_application(facade, session_factory=None)
    application.bot_data["operational_state_store"] = None
    # We exercise Application.process_update and the registered PTB filters, but
    # replace Telegram's network boundary. Initialization would call getMe.
    application.bot._bot_user = User(
        id=123456,
        first_name="Replay",
        is_bot=True,
        username="replay_bot",
    )
    application._initialized = True
    return application, facade


def _sent_message(application: object, message_id: int = 900) -> Message:
    return Message.de_json(
        {
            "message_id": message_id,
            "date": 1788048100,
            "chat": {"id": 42, "type": "private"},
            "text": "synthetic bot reply",
        },
        application.bot,
    )


@pytest.mark.asyncio
async def test_real_ptb_routing_replays_start_command(monkeypatch: pytest.MonkeyPatch) -> None:
    case = _case("start_discovers_primary_workflow")
    application, _facade = _build_application(monkeypatch)
    update = Update.de_json(case["update"], application.bot)
    send_message = AsyncMock(return_value=_sent_message(application))

    with patch.object(type(application.bot), "send_message", new=send_message):
        await application.process_update(update)

    assert send_message.await_count == 1
    assert case["reply_contains"] in send_message.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_real_ptb_routing_never_captures_negated_dream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case("negated_dream_is_not_captured")
    application, facade = _build_application(monkeypatch)
    update = Update.de_json(case["update"], application.bot)
    send_message = AsyncMock(return_value=_sent_message(application))
    send_action = AsyncMock(return_value=True)

    with (
        patch.object(type(application.bot), "send_message", new=send_message),
        patch.object(type(application.bot), "send_chat_action", new=send_action),
        patch(
            "app.telegram.handlers.handle_chat_with_metadata",
            new=AsyncMock(return_value=ChatResult("Понял.", [])),
        ),
    ):
        await application.process_update(update)

    facade.create_dream.assert_not_awaited()
    assert case["reply_contains"] in send_message.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_real_ptb_routing_splits_compound_capture_from_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case("compound_capture_keeps_question_out_of_archive")
    application, facade = _build_application(monkeypatch)
    dream_id = uuid.UUID("11111111-1111-4111-8111-111111111111")
    facade.create_dream.return_value = CreatedDreamItem(
        id=dream_id,
        date="2026-08-30",
        title="Мост",
        word_count=8,
        source_doc_id="telegram:42",
        created_at="2026-08-30T12:00:00+00:00",
        created=True,
        written_to_google_doc=False,
        semantic_index_status="pending",
        processing_status="pending",
        google_doc_write_status="pending",
    )
    update = Update.de_json(case["update"], application.bot)
    send_message = AsyncMock(
        side_effect=[_sent_message(application, 901), _sent_message(application, 902)]
    )
    send_action = AsyncMock(return_value=True)

    with (
        patch.object(type(application.bot), "send_message", new=send_message),
        patch.object(type(application.bot), "send_chat_action", new=send_action),
    ):
        await application.process_update(update)

    facade.create_dream.assert_awaited_once_with(
        case["captured_text"],
        chat_id=42,
        source_event_key="telegram:42:message:503",
    )
    assert send_message.await_count == 2
    assert "✅ Сон сохранён" in send_message.await_args_list[0].kwargs["text"]
    assert case["reply_contains"] in send_message.await_args_list[1].kwargs["text"]


@pytest.mark.asyncio
async def test_real_ptb_routing_saves_transcribed_voice_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case("reply_to_transcribed_voice_saves_archive_text")
    application, facade = _build_application(monkeypatch)
    session_factory = object()
    application.bot_data["session_factory"] = session_factory
    dream_id = uuid.UUID("22222222-2222-4222-8222-222222222222")
    facade.create_dream.return_value = CreatedDreamItem(
        id=dream_id,
        date="2026-09-01",
        title="Стеклянная лестница",
        word_count=6,
        source_doc_id="telegram:42",
        created_at="2026-09-01T12:00:00+00:00",
        created=True,
        written_to_google_doc=False,
        semantic_index_status="pending",
        processing_status="pending",
        google_doc_write_status="pending",
    )
    update = Update.de_json(case["update"], application.bot)
    send_message = AsyncMock(return_value=_sent_message(application))
    send_action = AsyncMock(return_value=True)
    transcript_lookup = AsyncMock(return_value=("transcribed", case["captured_text"]))

    with (
        patch.object(type(application.bot), "send_message", new=send_message),
        patch.object(type(application.bot), "send_chat_action", new=send_action),
        patch(
            "app.telegram.handlers.get_voice_transcript_for_message",
            new=transcript_lookup,
        ),
    ):
        await application.process_update(update)

    transcript_lookup.assert_awaited_once_with(
        session_factory,
        chat_id=42,
        telegram_message_id=704,
    )
    facade.create_dream.assert_awaited_once_with(
        case["captured_text"],
        chat_id=42,
        source_event_key=case["source_event_key"],
    )
    assert send_message.await_count == 1
    assert case["reply_contains"] in send_message.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_real_ptb_routing_keeps_same_text_messages_distinct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case("same_text_distinct_messages_keep_distinct_source_events")
    application, facade = _build_application(monkeypatch)
    facade.create_dream.side_effect = [
        CreatedDreamItem(
            id=uuid.UUID("33333333-3333-4333-8333-333333333333"),
            date="2026-09-01",
            title="Синий ключ",
            word_count=6,
            source_doc_id="telegram:42",
            created_at="2026-09-01T12:01:00+00:00",
            created=True,
            written_to_google_doc=False,
            semantic_index_status="pending",
            processing_status="pending",
            google_doc_write_status="pending",
        ),
        CreatedDreamItem(
            id=uuid.UUID("44444444-4444-4444-8444-444444444444"),
            date="2026-09-01",
            title="Синий ключ",
            word_count=6,
            source_doc_id="telegram:42",
            created_at="2026-09-01T12:02:00+00:00",
            created=True,
            written_to_google_doc=False,
            semantic_index_status="pending",
            processing_status="pending",
            google_doc_write_status="pending",
        ),
    ]
    send_message = AsyncMock(
        side_effect=[_sent_message(application, 921), _sent_message(application, 922)]
    )
    send_action = AsyncMock(return_value=True)

    with (
        patch.object(type(application.bot), "send_message", new=send_message),
        patch.object(type(application.bot), "send_chat_action", new=send_action),
    ):
        for update_payload in case["updates"]:
            await application.process_update(Update.de_json(update_payload, application.bot))

    assert facade.create_dream.await_count == 2
    for index, create_call in enumerate(facade.create_dream.await_args_list):
        assert create_call.args == (case["captured_text"],)
        assert create_call.kwargs == {
            "chat_id": 42,
            "source_event_key": case["source_event_keys"][index],
        }
    assert send_message.await_count == 2
    assert all(
        case["reply_contains"] in send_call.kwargs["text"]
        for send_call in send_message.await_args_list
    )


@pytest.mark.asyncio
async def test_real_ptb_routing_confirms_persisted_pending_dream_after_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case("persisted_pending_dream_confirmation_saves_after_restart")
    pending = case["pending_dream"]
    state_store = RedisOperationalStateStore(_FakeRedis(), key_prefix="test:telegram-replay")
    await state_store.save_pending_dream(
        42,
        PendingDreamDraft(
            raw_text=pending["raw_text"],
            title=pending["title"],
            dream_date=pending["dream_date"],
            source_message_id=pending["source_message_id"],
            source_kind=pending["source_kind"],
            created_at=datetime.now(timezone.utc),
        ),
    )
    clear_pending_dream_draft(42)
    application, facade = _build_application(monkeypatch)
    application.bot_data["operational_state_store"] = state_store
    facade.create_dream.return_value = CreatedDreamItem(
        id=uuid.UUID("55555555-5555-4555-8555-555555555555"),
        date="2026-09-01",
        title="Зелёная лампа",
        word_count=9,
        source_doc_id="telegram:42",
        created_at="2026-09-01T12:03:00+00:00",
        created=True,
        written_to_google_doc=False,
        semantic_index_status="pending",
        processing_status="pending",
        google_doc_write_status="pending",
    )
    update = Update.de_json(case["update"], application.bot)
    send_message = AsyncMock(return_value=_sent_message(application))

    with patch.object(type(application.bot), "send_message", new=send_message):
        await application.process_update(update)

    facade.create_dream.assert_awaited_once_with(
        pending["raw_text"],
        title=pending["title"],
        dream_date=None,
        chat_id=42,
        source_event_key=case["source_event_key"],
    )
    assert load_pending_dream_draft(42) is None
    assert await state_store.load_pending_dream(42) is None
    assert send_message.await_count == 1
    assert case["reply_contains"] in send_message.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_real_ptb_routing_rejects_persisted_pending_dream_after_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case("persisted_pending_dream_rejection_clears_after_restart")
    pending = case["pending_dream"]
    state_store = RedisOperationalStateStore(_FakeRedis(), key_prefix="test:telegram-replay")
    await state_store.save_pending_dream(
        42,
        PendingDreamDraft(
            raw_text=pending["raw_text"],
            title=pending["title"],
            dream_date=pending["dream_date"],
            source_message_id=pending["source_message_id"],
            source_kind=pending["source_kind"],
            created_at=datetime.now(timezone.utc),
        ),
    )
    clear_pending_dream_draft(42)
    application, facade = _build_application(monkeypatch)
    application.bot_data["operational_state_store"] = state_store
    update = Update.de_json(case["update"], application.bot)
    send_message = AsyncMock(return_value=_sent_message(application))

    with patch.object(type(application.bot), "send_message", new=send_message):
        await application.process_update(update)

    facade.create_dream.assert_not_awaited()
    assert load_pending_dream_draft(42) is None
    assert await state_store.load_pending_dream(42) is None
    assert send_message.await_count == 1
    assert case["reply_contains"] in send_message.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_real_ptb_routing_rejects_unbound_confirmation_after_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case("unbound_confirmation_reply_does_not_save_after_restart")
    state_store = RedisOperationalStateStore(_FakeRedis(), key_prefix="test:telegram-replay")
    clear_pending_dream_draft(42)
    application, facade = _build_application(monkeypatch)
    application.bot_data["operational_state_store"] = state_store
    update = Update.de_json(case["update"], application.bot)
    send_message = AsyncMock(return_value=_sent_message(application))
    chat_handler = AsyncMock(return_value=ChatResult("fallback", []))

    with (
        patch.object(type(application.bot), "send_message", new=send_message),
        patch("app.telegram.handlers.handle_chat_with_metadata", new=chat_handler),
    ):
        await application.process_update(update)

    facade.create_dream.assert_not_awaited()
    chat_handler.assert_not_awaited()
    assert load_pending_dream_draft(42) is None
    assert await state_store.load_pending_dream(42) is None
    assert send_message.await_count == 1
    assert case["reply_contains"] in send_message.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_real_ptb_guard_blocks_unauthorized_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case("start_discovers_primary_workflow")
    case["update"]["message"]["chat"]["id"] = 999
    case["update"]["message"]["from"]["id"] = 999
    application, _facade = _build_application(monkeypatch)
    update = Update.de_json(case["update"], application.bot)
    send_message = AsyncMock(return_value=_sent_message(application))

    with patch.object(type(application.bot), "send_message", new=send_message):
        await application.process_update(update)

    send_message.assert_not_awaited()
