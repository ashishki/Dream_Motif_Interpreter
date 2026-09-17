from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Chat, MessageReactionUpdated, ReactionTypeEmoji, Update
from telegram.constants import ChatAction
from telegram.ext import ApplicationHandlerStop

from app.assistant.chat import ChatResult, DreamReference
from app.assistant.facade import AssistantFacade, DreamRecordingUnavailable
from app.assistant.session import (
    DisplayedDreamRef,
    DisplayedDreamSet,
    PendingDreamDraft,
    PendingInterpretationRequest,
    RedisOperationalStateStore,
    clear_displayed_dream_set,
    clear_pending_batch_dream_note,
    clear_pending_dream_draft,
    clear_pending_interpretation_request,
    clear_pending_single_dream_note,
    load_pending_batch_dream_note,
    load_pending_dream_draft,
    load_pending_single_dream_note,
    save_displayed_dream_message,
    save_displayed_dream_set,
    save_pending_batch_dream_note,
    save_pending_interpretation_request,
    save_pending_dream_draft,
    save_pending_single_dream_note,
)
from app.telegram.bot import handle_message_reaction, post_init, post_stop
from app.telegram.handlers import (
    ADD_NOTE_CALLBACK_PREFIX,
    FEEDBACK_PROMPT,
    FULL_DREAM_CALLBACK_PREFIX,
    MINI_APP_OPEN_BUTTON,
    MINI_APP_OPEN_MESSAGE,
    MINI_APP_UNCONFIGURED_MESSAGE,
    MAX_PENDING_FEEDBACK_REQUESTS,
    MISSING_DREAM_TEXT_REPLY,
    VOICE_PROCESSING_ACK,
    _extract_direct_note_text,
    _remember_feedback_request,
    _format_create_dream_reply,
    _split_telegram_text,
    chat_guard,
    dream_full_text_callback_handler,
    dream_memory_map_command_handler,
    help_command_handler,
    start_command_handler,
    text_message_handler,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.closed = False

    async def set(self, key: str, value: str, *, ex: int | None = None) -> None:
        del ex
        self.values[key] = value

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        self.closed = True


class _UnavailableRedis(_FakeRedis):
    async def ping(self) -> bool:
        return False


@pytest.mark.asyncio
async def test_post_init_fails_closed_when_redis_is_unavailable_in_production() -> None:
    application = SimpleNamespace(
        bot_data={
            "allowed_chat_id": 42,
            "operational_state_store": RedisOperationalStateStore(_UnavailableRedis()),
        }
    )

    with (
        patch(
            "app.telegram.bot.get_settings",
            return_value=SimpleNamespace(ENV="production"),
        ),
        pytest.raises(RuntimeError, match="Redis operational state is required"),
    ):
        await post_init(application)


@pytest.mark.asyncio
async def test_post_init_starts_voice_supervisor_when_initial_resume_fails() -> None:
    facade = MagicMock(spec=AssistantFacade)
    application = SimpleNamespace(
        bot_data={
            "allowed_chat_id": 42,
            "operational_state_store": RedisOperationalStateStore(_FakeRedis()),
            "session_factory": MagicMock(),
            "facade": facade,
            "bot_token": "TOKEN",
        }
    )

    with (
        patch(
            "app.telegram.bot.get_settings",
            return_value=SimpleNamespace(
                ENV="test",
                VOICE_RETENTION_SECONDS=3600,
                VOICE_TRANSCRIPT_RETENTION_SECONDS=604800,
                VOICE_MEDIA_DIR="/tmp/dream_voice",
            ),
        ),
        patch(
            "app.workers.transcribe.run_voice_retention_cycle",
            new=AsyncMock(return_value=(0, 0, 0)),
        ) as retention,
        patch(
            "app.workers.transcribe.resume_pending_voice_jobs",
            new=AsyncMock(side_effect=RuntimeError("temporary database outage")),
        ),
        patch("app.workers.transcribe.start_voice_maintenance_supervisor") as start_voice,
        patch("app.telegram.bot.start_dream_processing_supervisor"),
    ):
        await post_init(application)

    start_voice.assert_called_once_with(application)
    facade.start_background_workers.assert_awaited_once_with()
    retention.assert_awaited_once_with(application)


@pytest.mark.asyncio
async def test_post_init_validates_database_before_spawning_supervisors() -> None:
    redis = _FakeRedis()
    session = AsyncMock()
    session.execute.side_effect = RuntimeError("database unavailable")
    session_factory = MagicMock()
    session_factory.return_value.__aenter__.return_value = session
    facade = MagicMock(spec=AssistantFacade)
    application = SimpleNamespace(
        bot_data={
            "operational_state_store": RedisOperationalStateStore(redis),
            "session_factory": session_factory,
            "facade": facade,
            "bot_token": "TOKEN",
        }
    )

    with (
        patch("app.telegram.bot.get_settings", return_value=SimpleNamespace(ENV="test")),
        patch("app.workers.transcribe.start_voice_maintenance_supervisor") as start_voice,
        patch("app.telegram.bot.start_dream_processing_supervisor") as start_dream,
        pytest.raises(RuntimeError, match="Database dependency check failed"),
    ):
        await post_init(application)

    start_voice.assert_not_called()
    start_dream.assert_not_called()
    facade.start_background_workers.assert_not_awaited()
    facade.shutdown.assert_awaited_once_with()
    assert redis.closed is True


@pytest.mark.asyncio
async def test_partial_start_is_rolled_back_and_resources_are_closed() -> None:
    redis = _FakeRedis()
    facade = MagicMock(spec=AssistantFacade)
    application = SimpleNamespace(
        bot_data={
            "operational_state_store": RedisOperationalStateStore(redis),
            "session_factory": MagicMock(),
            "facade": facade,
            "bot_token": "TOKEN",
        }
    )

    with (
        patch("app.telegram.bot.get_settings", return_value=SimpleNamespace(ENV="test")),
        patch(
            "app.workers.transcribe.run_voice_retention_cycle",
            new=AsyncMock(return_value=(0, 0, 0)),
        ),
        patch(
            "app.workers.transcribe.resume_pending_voice_jobs",
            new=AsyncMock(return_value=0),
        ),
        patch("app.workers.transcribe.start_voice_maintenance_supervisor") as start_voice,
        patch(
            "app.telegram.bot.start_dream_processing_supervisor",
            side_effect=RuntimeError("dream supervisor failed"),
        ),
        patch(
            "app.workers.transcribe.stop_voice_maintenance_supervisor",
            new=AsyncMock(),
        ) as stop_voice,
        patch(
            "app.telegram.bot.stop_dream_processing_supervisor",
            new=AsyncMock(),
        ) as stop_dream,
        pytest.raises(RuntimeError, match="dream supervisor failed"),
    ):
        await post_init(application)

    start_voice.assert_called_once_with(application)
    stop_voice.assert_awaited_once_with(application)
    stop_dream.assert_awaited_once_with(application)
    facade.shutdown.assert_awaited_once_with()
    assert redis.closed is True


@pytest.mark.asyncio
async def test_post_stop_signals_supervisors_in_parallel_then_closes_resources() -> None:
    redis = _FakeRedis()
    facade = MagicMock(spec=AssistantFacade)
    application = SimpleNamespace(
        bot_data={
            "operational_state_store": RedisOperationalStateStore(redis),
            "facade": facade,
        }
    )
    dream_started = asyncio.Event()
    voice_started = asyncio.Event()
    release = asyncio.Event()

    async def stop_dream(_application: object) -> None:
        dream_started.set()
        await release.wait()

    async def stop_voice(_application: object) -> None:
        voice_started.set()
        await release.wait()

    with (
        patch("app.telegram.bot.stop_dream_processing_supervisor", new=stop_dream),
        patch("app.workers.transcribe.stop_voice_maintenance_supervisor", new=stop_voice),
    ):
        shutdown = asyncio.create_task(post_stop(application))
        await asyncio.wait_for(dream_started.wait(), timeout=0.2)
        await asyncio.wait_for(voice_started.wait(), timeout=0.2)
        facade.shutdown.assert_not_awaited()
        assert redis.closed is False
        release.set()
        await asyncio.wait_for(shutdown, timeout=0.2)

    facade.shutdown.assert_awaited_once_with()
    assert redis.closed is True


@pytest.mark.asyncio
async def test_chat_guard_blocks_unauthorized_chat_id() -> None:
    update = Update(update_id=1, message=SimpleNamespace(chat=SimpleNamespace(id=222)))
    context = SimpleNamespace(bot_data={"allowed_chat_id": 111})

    with pytest.raises(ApplicationHandlerStop):
        await chat_guard(update, context)


@pytest.mark.asyncio
async def test_chat_guard_allows_authorized_chat_id() -> None:
    update = Update(update_id=1, message=SimpleNamespace(chat=SimpleNamespace(id=111)))
    context = SimpleNamespace(bot_data={"allowed_chat_id": 111})

    await chat_guard(update, context)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "expected"),
    [
        (start_command_handler, "Мне приснилось"),
        (help_command_handler, "Найди сны про воду"),
    ],
)
async def test_start_and_help_explain_the_primary_workflow(handler, expected: str) -> None:
    update, message = _make_text_message_update("/command", chat_id=42)

    await handler(update, SimpleNamespace(bot_data={}))

    message.reply_text.assert_awaited_once()
    assert expected in message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_dream_memory_map_command_sends_telegram_web_app_button() -> None:
    update, message = _make_text_message_update("/map", chat_id=42)
    context = SimpleNamespace(bot_data={"mini_app_url": "https://example.com/dream-map"})

    await dream_memory_map_command_handler(update, context)

    message.reply_text.assert_awaited_once()
    args, kwargs = message.reply_text.await_args
    assert args == (MINI_APP_OPEN_MESSAGE,)
    button = kwargs["reply_markup"].inline_keyboard[0][0]
    assert button.text == MINI_APP_OPEN_BUTTON
    assert button.web_app.url == "https://example.com/dream-map"


@pytest.mark.asyncio
async def test_dream_memory_map_command_handles_missing_mini_app_url() -> None:
    update, message = _make_text_message_update("/map", chat_id=42)
    context = SimpleNamespace(bot_data={"mini_app_url": ""})

    await dream_memory_map_command_handler(update, context)

    message.reply_text.assert_awaited_once_with(MINI_APP_UNCONFIGURED_MESSAGE)


@pytest.mark.asyncio
async def test_dream_full_text_callback_sends_full_text() -> None:
    dream_id = "11111111-1111-4111-8111-111111111111"
    query_message = AsyncMock()
    query_message.reply_text = AsyncMock()
    query = AsyncMock()
    query.data = f"{FULL_DREAM_CALLBACK_PREFIX}{dream_id}"
    query.message = query_message
    update = MagicMock(spec=Update)
    update.callback_query = query
    facade = AsyncMock(spec=AssistantFacade)
    facade.get_dream = AsyncMock(
        return_value=SimpleNamespace(
            date="2026-06-05",
            title="Старый мост",
            raw_text="Полный текст сна.",
            notes=[],
        )
    )
    context = _make_text_context(facade, 42)

    await dream_full_text_callback_handler(update, context)

    query.answer.assert_awaited_once()
    facade.get_dream.assert_awaited_once()
    query_message.reply_text.assert_awaited_once_with(
        "2026-06-05, Старый мост\n\nПолный текст сна."
    )


# ---------------------------------------------------------------------------
# text_message_handler — assistant routing coverage (AC-2)
# ---------------------------------------------------------------------------


def _make_text_message_update(text: str, chat_id: int = 100) -> tuple[MagicMock, MagicMock]:
    message = AsyncMock()
    message.text = text
    message.reply_to_message = None
    message.reply_text = AsyncMock()

    chat = MagicMock()
    chat.id = chat_id

    update = MagicMock(spec=Update)
    update.effective_message = message
    update.effective_chat = chat
    return update, message


def _make_text_context(facade: AssistantFacade, chat_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        bot_data={"facade": facade, "session_factory": None, "allowed_chat_id": chat_id},
        bot=SimpleNamespace(send_chat_action=AsyncMock()),
    )


@pytest.fixture(autouse=True)
def _clear_pending_drafts() -> None:
    clear_pending_dream_draft(42)
    clear_pending_dream_draft(55)
    clear_pending_dream_draft(77)
    clear_pending_dream_draft(100)
    clear_displayed_dream_set(42)
    clear_pending_batch_dream_note(42)
    clear_pending_interpretation_request(42)
    clear_pending_interpretation_request(55)
    clear_pending_interpretation_request(77)
    clear_pending_interpretation_request(100)
    clear_pending_single_dream_note(42)
    yield
    clear_pending_dream_draft(42)
    clear_pending_dream_draft(55)
    clear_pending_dream_draft(77)
    clear_pending_dream_draft(100)
    clear_displayed_dream_set(42)
    clear_pending_batch_dream_note(42)
    clear_pending_interpretation_request(42)
    clear_pending_interpretation_request(55)
    clear_pending_interpretation_request(77)
    clear_pending_interpretation_request(100)
    clear_pending_single_dream_note(42)


@pytest.mark.asyncio
async def test_text_message_handler_routes_to_handle_chat() -> None:
    update, message = _make_text_message_update("what are my recent dreams?", chat_id=42)
    message.message_id = 91
    facade = AsyncMock(spec=AssistantFacade)
    context = _make_text_context(facade, 42)

    with patch(
        "app.telegram.handlers.handle_chat_with_metadata",
        new=AsyncMock(return_value=ChatResult("Here are your dreams.", [])),
    ) as mock_chat:
        await text_message_handler(update, context)

    mock_chat.assert_awaited_once_with(
        "what are my recent dreams?",
        facade,
        session_factory=None,
        chat_id=42,
        operational_state_store=None,
        source_event_key="telegram:42:message:91",
    )
    message.reply_text.assert_awaited_once_with("Here are your dreams.")


@pytest.mark.asyncio
async def test_text_message_handler_adds_reply_context_to_chat_request() -> None:
    update, message = _make_text_message_update("покажи полный текст", chat_id=42)
    message.reply_to_message = SimpleNamespace(text="1. 05.06.26, Старый мост")
    facade = AsyncMock(spec=AssistantFacade)
    context = _make_text_context(facade, 42)

    with patch(
        "app.telegram.handlers.handle_chat_with_metadata",
        new=AsyncMock(return_value=ChatResult("Уточните сон.", [])),
    ) as mock_chat:
        await text_message_handler(update, context)

    sent_text = mock_chat.await_args.args[0]
    assert "Контекст сообщения, на которое отвечает пользователь" in sent_text
    assert "1. 05.06.26, Старый мост" in sent_text
    assert "Новое сообщение пользователя:\nпокажи полный текст" in sent_text


@pytest.mark.asyncio
async def test_text_message_handler_adds_full_text_buttons_for_dream_mentions() -> None:
    dream_id = "11111111-1111-4111-8111-111111111111"
    update, message = _make_text_message_update("найди сон про мост", chat_id=42)
    facade = AsyncMock(spec=AssistantFacade)
    context = _make_text_context(facade, 42)

    with patch(
        "app.telegram.handlers.handle_chat_with_metadata",
        new=AsyncMock(
            return_value=ChatResult(
                "1. 05.06.26, Старый мост: я возвращаюсь к старому мосту.",
                ["search_dreams"],
                dream_ids=[dream_id],
            )
        ),
    ):
        await text_message_handler(update, context)

    kwargs = message.reply_text.await_args.kwargs
    button = kwargs["reply_markup"].inline_keyboard[0][0]
    assert button.text == "Полный текст"
    assert button.callback_data == f"{FULL_DREAM_CALLBACK_PREFIX}{dream_id}"


@pytest.mark.asyncio
async def test_text_message_handler_filters_full_text_buttons_to_visible_dreams() -> None:
    visible_ids = [
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        "33333333-3333-4333-8333-333333333333",
    ]
    hidden_ids = [
        "44444444-4444-4444-8444-444444444444",
        "55555555-5555-4555-8555-555555555555",
    ]
    update, message = _make_text_message_update("найди сны про работу", chat_id=42)
    facade = AsyncMock(spec=AssistantFacade)
    context = _make_text_context(facade, 42)

    with patch(
        "app.telegram.handlers.handle_chat_with_metadata",
        new=AsyncMock(
            return_value=ChatResult(
                "\n".join(
                    [
                        "1. 01.05.26, Офис: задачи распадаются.",
                        "2. 02.05.26, Руководитель: проверка работы.",
                        "3. 03.05.26, Документы: рабочие бумаги.",
                    ]
                ),
                ["search_dreams"],
                dream_ids=[*visible_ids, *hidden_ids],
                dream_refs=[
                    DreamReference(visible_ids[0], date="2026-05-01", title="Офис"),
                    DreamReference(visible_ids[1], date="2026-05-02", title="Руководитель"),
                    DreamReference(visible_ids[2], date="2026-05-03", title="Документы"),
                    DreamReference(hidden_ids[0], date="2026-05-04", title="Лестница"),
                    DreamReference(hidden_ids[1], date="2026-05-05", title="Поезд"),
                ],
            )
        ),
    ):
        await text_message_handler(update, context)

    keyboard = message.reply_text.await_args.kwargs["reply_markup"].inline_keyboard
    buttons = [row[0] for row in keyboard]
    assert [button.callback_data for button in buttons] == [
        f"{FULL_DREAM_CALLBACK_PREFIX}{dream_id}" for dream_id in visible_ids
    ]


@pytest.mark.asyncio
async def test_text_message_handler_limits_full_text_buttons_to_numbered_visible_count() -> None:
    dream_ids = [
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        "33333333-3333-4333-8333-333333333333",
        "44444444-4444-4444-8444-444444444444",
        "55555555-5555-4555-8555-555555555555",
    ]
    update, message = _make_text_message_update("найди конкретный сон", chat_id=42)
    facade = AsyncMock(spec=AssistantFacade)
    context = _make_text_context(facade, 42)

    with patch(
        "app.telegram.handlers.handle_chat_with_metadata",
        new=AsyncMock(
            return_value=ChatResult(
                "1. Нашёл один подходящий сон: описание без точного заголовка.",
                ["search_dreams"],
                dream_ids=dream_ids,
                dream_refs=[
                    DreamReference(dream_ids[0], date="2026-05-01", title="Офис"),
                    DreamReference(dream_ids[1], date="2026-05-02", title="Руководитель"),
                    DreamReference(dream_ids[2], date="2026-05-03", title="Документы"),
                    DreamReference(dream_ids[3], date="2026-05-04", title="Лестница"),
                    DreamReference(dream_ids[4], date="2026-05-05", title="Поезд"),
                ],
            )
        ),
    ):
        await text_message_handler(update, context)

    keyboard = message.reply_text.await_args.kwargs["reply_markup"].inline_keyboard
    assert len(keyboard) == 1
    assert keyboard[0][0].callback_data == f"{FULL_DREAM_CALLBACK_PREFIX}{dream_ids[0]}"


@pytest.mark.asyncio
async def test_text_message_handler_uses_numbered_count_when_only_some_titles_match() -> None:
    dream_ids = [
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        "33333333-3333-4333-8333-333333333333",
    ]
    update, message = _make_text_message_update("найди сны про работу", chat_id=42)
    facade = AsyncMock(spec=AssistantFacade)
    context = _make_text_context(facade, 42)

    with patch(
        "app.telegram.handlers.handle_chat_with_metadata",
        new=AsyncMock(
            return_value=ChatResult(
                "\n".join(
                    [
                        "1. 01.05.26, Офис: рабочий сюжет.",
                        "2. 02.05.26, сон про начальника и задачу.",
                        "3. 03.05.26, сон про документы.",
                    ]
                ),
                ["search_dreams"],
                dream_ids=dream_ids,
                dream_refs=[
                    DreamReference(dream_ids[0], date="2026-05-01", title="Офис"),
                    DreamReference(dream_ids[1], date="2026-05-02", title="Руководитель"),
                    DreamReference(dream_ids[2], date="2026-05-03", title="Документы"),
                ],
            )
        ),
    ):
        await text_message_handler(update, context)

    keyboard = message.reply_text.await_args.kwargs["reply_markup"].inline_keyboard
    buttons = [row[0] for row in keyboard]
    assert [button.callback_data for button in buttons] == [
        f"{FULL_DREAM_CALLBACK_PREFIX}{dream_id}" for dream_id in dream_ids
    ]


@pytest.mark.asyncio
async def test_text_message_handler_confirms_batch_note_for_numbered_search_results() -> None:
    dream_ids = [
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        "33333333-3333-4333-8333-333333333333",
        "44444444-4444-4444-8444-444444444444",
    ]
    facade = AsyncMock(spec=AssistantFacade)
    facade.add_dream_note = AsyncMock(return_value=(True, "Заметка добавлена под нужным сном."))
    context = _make_text_context(facade, 42)

    search_update, search_message = _make_text_message_update(
        "Найди сны про эмоции к матери",
        chat_id=42,
    )
    with patch(
        "app.telegram.handlers.handle_chat_with_metadata",
        new=AsyncMock(
            return_value=ChatResult(
                "\n".join(
                    [
                        "1. 16.07.26, Граница между эмоцией и ответственностью",
                        "2. 16.02.23, Задний двор",
                        "3. 14.06.26, Спор с мамой и непримиримость",
                        "4. 06.05.26, о себя даче моему",
                    ]
                ),
                ["search_dreams"],
                dream_ids=dream_ids,
                dream_refs=[
                    DreamReference(dream_ids[0], date="2026-07-16", title="Граница"),
                    DreamReference(dream_ids[1], date="2023-02-16", title="Задний двор"),
                    DreamReference(
                        dream_ids[2],
                        date="2026-06-14",
                        title="Спор с мамой и непримиримость",
                    ),
                    DreamReference(dream_ids[3], date="2026-05-06", title="о себя даче моему"),
                ],
            )
        ),
    ):
        await text_message_handler(search_update, context)

    search_message.reply_text.assert_awaited_once()

    note_update, note_message = _make_text_message_update(
        'Добавь одинаковую заметку к снам 2,3 и 4: "проявление негативных эмоций по отношению к матери"',
        chat_id=42,
    )
    with patch("app.telegram.handlers.handle_chat_with_metadata", new=AsyncMock()) as mock_chat:
        await text_message_handler(note_update, context)

    mock_chat.assert_not_awaited()
    pending = load_pending_batch_dream_note(42)
    assert pending is not None
    assert [ref.index for ref in pending.refs] == [2, 3, 4]
    preview = note_message.reply_text.await_args.args[0]
    assert "Я понял так" in preview
    assert "2. 2023-02-16, «Задний двор»" in preview
    assert "Добавляю?" in preview
    reply_markup = note_message.reply_text.await_args.kwargs["reply_markup"]
    assert reply_markup.inline_keyboard[0][0].text == "Да, добавить"

    confirm_update, confirm_message = _make_text_message_update("да", chat_id=42)
    await text_message_handler(confirm_update, context)

    assert facade.add_dream_note.await_count == 3
    assert [
        str(call.kwargs["dream_id"]) for call in facade.add_dream_note.await_args_list
    ] == dream_ids[1:]
    assert {call.args[0] for call in facade.add_dream_note.await_args_list} == {
        "проявление негативных эмоций по отношению к матери"
    }
    confirm_message.reply_text.assert_awaited_once_with(
        "Готово. Заметка для всех выбранных снов (3) надёжно сохранена.\n"
        "Заметка добавлена под нужным сном."
    )


@pytest.mark.asyncio
async def test_batch_note_selection_and_confirmation_survive_restarts() -> None:
    dream_ids = [
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
    ]
    state_store = RedisOperationalStateStore(_FakeRedis(), key_prefix="test:telegram")
    await state_store.save_displayed_set(
        42,
        DisplayedDreamSet(
            refs=[
                DisplayedDreamRef(1, dream_ids[0], "2026-08-29", "Озеро"),
                DisplayedDreamRef(2, dream_ids[1], "2026-08-30", "Река"),
            ],
            created_at=datetime.now(timezone.utc),
        ),
    )
    clear_displayed_dream_set(42)
    facade = AsyncMock(spec=AssistantFacade)
    facade.add_dream_note = AsyncMock(return_value=(True, "Заметка добавлена под нужным сном."))
    context = _make_text_context(facade, 42)
    context.bot_data["operational_state_store"] = state_store

    note_update, _note_message = _make_text_message_update(
        "Добавь заметку ко всем найденным: повторяющийся водный мотив",
        chat_id=42,
    )
    await text_message_handler(note_update, context)
    clear_pending_batch_dream_note(42)

    confirm_update, confirm_message = _make_text_message_update("да", chat_id=42)
    await text_message_handler(confirm_update, context)

    assert [
        str(call.kwargs["dream_id"]) for call in facade.add_dream_note.await_args_list
    ] == dream_ids
    confirm_message.reply_text.assert_awaited_once_with(
        "Готово. Заметка для всех выбранных снов (2) надёжно сохранена.\n"
        "Заметка добавлена под нужным сном."
    )


@pytest.mark.asyncio
async def test_partial_batch_failure_retains_state_and_retry_is_safe() -> None:
    refs = [
        DisplayedDreamRef(1, "11111111-1111-4111-8111-111111111111", "2026-08-29", "Озеро"),
        DisplayedDreamRef(2, "22222222-2222-4222-8222-222222222222", "2026-08-30", "Река"),
    ]
    state_store = RedisOperationalStateStore(_FakeRedis(), key_prefix="test:telegram")
    pending = save_pending_batch_dream_note(42, note_text="водный мотив", refs=refs)
    await state_store.save_pending_batch_note(42, pending)
    facade = AsyncMock(spec=AssistantFacade)
    facade.add_dream_note = AsyncMock(
        side_effect=[
            (True, "queued"),
            (False, "database unavailable"),
        ]
    )
    context = _make_text_context(facade, 42)
    context.bot_data["operational_state_store"] = state_store

    first_update, first_message = _make_text_message_update("да", chat_id=42)
    await text_message_handler(first_update, context)

    assert load_pending_batch_dream_note(42) is not None
    assert await state_store.load_pending_batch_note(42) is not None
    first_reply = first_message.reply_text.await_args.args[0]
    assert "Надёжно сохранено 1 из 2" in first_reply
    assert "не продублируются" in first_reply

    # Simulate a process restart. The durable first note is replay-safe and the
    # Redis intent restores the complete batch for a second attempt.
    clear_pending_batch_dream_note(42)
    facade.add_dream_note.reset_mock()
    facade.add_dream_note.side_effect = [(True, "already exists"), (True, "queued")]
    retry_update, retry_message = _make_text_message_update("да", chat_id=42)
    await text_message_handler(retry_update, context)

    assert facade.add_dream_note.await_count == 2
    assert load_pending_batch_dream_note(42) is None
    assert await state_store.load_pending_batch_note(42) is None
    assert "надёжно сохранена" in retry_message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_batch_note_confirmation_preserves_mixed_durable_job_statuses() -> None:
    refs = [
        DisplayedDreamRef(1, "11111111-1111-4111-8111-111111111111", "2026-08-29", "Озеро"),
        DisplayedDreamRef(2, "22222222-2222-4222-8222-222222222222", "2026-08-30", "Река"),
    ]
    save_pending_batch_dream_note(42, note_text="водный мотив", refs=refs)
    facade = AsyncMock(spec=AssistantFacade)
    facade.add_dream_note = AsyncMock(
        side_effect=[
            (True, "Заметка сохранена; обработка стоит в очереди."),
            (True, "Заметка уже сохранена; доставка в Google Docs требует явного повтора."),
        ]
    )
    context = _make_text_context(facade, 42)

    update, message = _make_text_message_update("да", chat_id=42)
    await text_message_handler(update, context)

    reply = message.reply_text.await_args.args[0]
    assert "1. «Озеро»: Заметка сохранена; обработка стоит в очереди." in reply
    assert "2. «Река»: Заметка уже сохранена" in reply
    assert "требует явного повтора" in reply
    assert load_pending_batch_dream_note(42) is None


@pytest.mark.asyncio
async def test_text_message_handler_confirms_batch_note_for_all_displayed_results() -> None:
    dream_ids = [
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
    ]
    facade = AsyncMock(spec=AssistantFacade)
    facade.add_dream_note = AsyncMock(return_value=(True, "Заметка добавлена под нужным сном."))
    context = _make_text_context(facade, 42)

    search_update, _search_message = _make_text_message_update("Найди сны про воду", chat_id=42)
    with patch(
        "app.telegram.handlers.handle_chat_with_metadata",
        new=AsyncMock(
            return_value=ChatResult(
                "1. 01.05.26, Озеро\n2. 02.05.26, Река",
                ["search_dreams"],
                dream_ids=dream_ids,
                dream_refs=[
                    DreamReference(dream_ids[0], date="2026-05-01", title="Озеро"),
                    DreamReference(dream_ids[1], date="2026-05-02", title="Река"),
                ],
            )
        ),
    ):
        await text_message_handler(search_update, context)

    note_update, note_message = _make_text_message_update(
        "Добавь заметку ко всем найденным: повторяющийся водный мотив",
        chat_id=42,
    )
    await text_message_handler(note_update, context)

    pending = load_pending_batch_dream_note(42)
    assert pending is not None
    assert [ref.index for ref in pending.refs] == [1, 2]
    assert "к 2 снам" in note_message.reply_text.await_args.args[0]


def test_voice_processing_ack_is_russian() -> None:
    assert VOICE_PROCESSING_ACK == "Обрабатываю голосовое сообщение..."


def test_feedback_prompt_is_short_numeric_reply_prompt() -> None:
    assert FEEDBACK_PROMPT == "Ответьте 1–5, можно с коротким комментарием."


@pytest.mark.asyncio
async def test_text_message_handler_can_append_feedback_prompt_when_enabled() -> None:
    update, message = _make_text_message_update("what are my recent dreams?", chat_id=42)
    facade = AsyncMock(spec=AssistantFacade)
    context = _make_text_context(facade, 42)
    context.bot_data["numeric_feedback_enabled"] = True

    with patch(
        "app.telegram.handlers.handle_chat_with_metadata",
        new=AsyncMock(return_value=ChatResult("Here are your dreams.", [])),
    ):
        await text_message_handler(update, context)

    message.reply_text.assert_awaited_once_with(f"Here are your dreams.\n\n{FEEDBACK_PROMPT}")


def test_pending_feedback_requests_are_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.telegram.handlers.MAX_PENDING_FEEDBACK_REQUESTS",
        2,
    )
    pending: dict[str, dict[str, object]] = {}
    bot_msg_ids: dict[str, int] = {}

    _remember_feedback_request(
        pending,
        bot_msg_ids,
        chat_key="1",
        message_id=101,
        response_text="first",
        tool_calls_made=[],
    )
    _remember_feedback_request(
        pending,
        bot_msg_ids,
        chat_key="2",
        message_id=102,
        response_text="second",
        tool_calls_made=[],
    )
    _remember_feedback_request(
        pending,
        bot_msg_ids,
        chat_key="3",
        message_id=103,
        response_text="third",
        tool_calls_made=[],
    )

    assert MAX_PENDING_FEEDBACK_REQUESTS == 10_000
    assert list(pending) == ["2", "3"]
    assert bot_msg_ids == {"2": 102, "3": 103}


@pytest.mark.asyncio
async def test_text_message_handler_sends_handle_chat_response() -> None:
    update, message = _make_text_message_update("hello", chat_id=7)
    facade = AsyncMock(spec=AssistantFacade)
    context = _make_text_context(facade, 7)

    with patch(
        "app.telegram.handlers.handle_chat_with_metadata",
        new=AsyncMock(return_value=ChatResult("pong", [])),
    ):
        await text_message_handler(update, context)

    message.reply_text.assert_awaited_once_with("pong")


# ---------------------------------------------------------------------------
# text_message_handler — insufficient-evidence path (AC-3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_text_message_handler_sends_insufficient_evidence_reply() -> None:
    """When the archive has no evidence, handle_chat returns an appropriate message
    that is forwarded verbatim to the Telegram user."""
    update, message = _make_text_message_update("did I dream about dragons?", chat_id=5)
    facade = AsyncMock(spec=AssistantFacade)
    context = _make_text_context(facade, 5)

    insufficient_reply = "The archive contains no evidence of dragon dreams."
    with patch(
        "app.telegram.handlers.handle_chat_with_metadata",
        new=AsyncMock(return_value=ChatResult(insufficient_reply, [])),
    ):
        await text_message_handler(update, context)

    message.reply_text.assert_awaited_once_with(insufficient_reply)


@pytest.mark.asyncio
async def test_text_message_handler_skips_empty_message() -> None:
    """A message with no text should not trigger handle_chat."""
    update = MagicMock(spec=Update)
    update.effective_message = MagicMock()
    update.effective_message.text = None
    update.effective_message.reply_text = AsyncMock()

    facade = AsyncMock(spec=AssistantFacade)
    context = SimpleNamespace(bot_data={"facade": facade, "session_factory": None})

    with patch("app.telegram.handlers.handle_chat_with_metadata", new=AsyncMock()) as mock_chat:
        await text_message_handler(update, context)

    mock_chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_text_message_handler_sends_typing_before_handle_chat() -> None:
    update, message = _make_text_message_update("hello", chat_id=55)
    facade = AsyncMock(spec=AssistantFacade)
    context = _make_text_context(facade, 55)

    async def _chat_side_effect(*args, **kwargs) -> ChatResult:
        del args, kwargs
        context.bot.send_chat_action.assert_awaited_once_with(
            chat_id=55,
            action=ChatAction.TYPING,
        )
        return ChatResult("pong", [])

    with patch(
        "app.telegram.handlers.handle_chat_with_metadata",
        new=AsyncMock(side_effect=_chat_side_effect),
    ) as mock_chat:
        await text_message_handler(update, context)

    mock_chat.assert_awaited_once()
    message.reply_text.assert_awaited_once_with("pong")


@pytest.mark.asyncio
async def test_text_message_handler_acks_feedback_when_commit_fails() -> None:
    class _FailingFeedbackSession:
        def add(self, value: object) -> None:
            del value

        async def commit(self) -> None:
            raise RuntimeError("db unavailable")

    class _FailingFeedbackSessionFactory:
        def __call__(self) -> "_FailingFeedbackSessionFactory":
            return self

        async def __aenter__(self) -> _FailingFeedbackSession:
            return _FailingFeedbackSession()

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    update, message = _make_text_message_update("5", chat_id=42)
    message.reply_to_message = SimpleNamespace(message_id=901)
    facade = AsyncMock(spec=AssistantFacade)
    context = SimpleNamespace(
        bot_data={
            "facade": facade,
            "session_factory": _FailingFeedbackSessionFactory(),
            "allowed_chat_id": 42,
            "_feedback_pending_by_chat": {
                "42": {
                    "message_id": 901,
                    "response_summary": "answer",
                    "tool_calls_made": [],
                }
            },
            "_bot_message_ids_by_chat": {"42": 901},
            "numeric_feedback_enabled": True,
        },
        bot=SimpleNamespace(send_chat_action=AsyncMock()),
    )

    await text_message_handler(update, context)

    message.reply_text.assert_awaited_once_with("Спасибо, записал.")


def test_split_telegram_text_keeps_long_responses_under_limit() -> None:
    text = ("word " * 1700) + "\nfinal line"

    chunks = _split_telegram_text(text)

    assert len(chunks) >= 3
    assert all(len(chunk) <= 3900 for chunk in chunks)
    assert "".join(chunks) == text


@pytest.mark.asyncio
async def test_text_message_handler_saves_short_natural_dream_without_confirmation() -> None:
    update, message = _make_text_message_update("сегодня мне приснилось рыба", chat_id=42)
    message.message_id = 92
    created = SimpleNamespace(
        created=True,
        written_to_google_doc=True,
        written_to_doc_name="Dream Archive",
    )
    facade = AsyncMock(spec=AssistantFacade)
    facade.create_dream = AsyncMock(return_value=created)
    context = _make_text_context(facade, 42)

    with patch("app.telegram.handlers.handle_chat_with_metadata", new=AsyncMock()) as mock_chat:
        await text_message_handler(update, context)

    mock_chat.assert_not_awaited()
    facade.create_dream.assert_awaited_once_with(
        "сегодня мне приснилось рыба",
        chat_id=42,
        source_event_key="telegram:42:message:92",
    )
    context.bot.send_chat_action.assert_awaited()
    message.reply_text.assert_awaited_once()
    confirmation = message.reply_text.await_args.args[0]
    assert "✅ Сон сохранён" in confirmation
    assert "Архив: сохранено" in confirmation
    assert "Google Docs: добавлено" in confirmation
    assert load_pending_dream_draft(42) is None


@pytest.mark.asyncio
async def test_natural_dream_with_meta_question_saves_only_dream_and_surfaces_question() -> None:
    dream_id = uuid.UUID("11111111-1111-4111-8111-111111111111")
    update, message = _make_text_message_update(
        "Мне приснилось, что я иду по мосту. Что это значит?",
        chat_id=42,
    )
    message.reply_text.return_value = SimpleNamespace(message_id=901)
    facade = AsyncMock(spec=AssistantFacade)
    facade.create_dream = AsyncMock(
        return_value=SimpleNamespace(
            id=dream_id,
            created=True,
            date="2026-08-30",
            title="Мост",
            written_to_google_doc=False,
            semantic_index_status="pending",
            processing_status="pending",
            google_doc_write_status="pending",
        )
    )
    context = _make_text_context(facade, 42)

    await text_message_handler(update, context)

    facade.create_dream.assert_awaited_once_with(
        "Мне приснилось, что я иду по мосту.",
        chat_id=42,
    )
    assert message.reply_text.await_count == 2
    card_call = message.reply_text.await_args_list[0]
    assert "30.08.26 · «Мост»" in card_call.args[0]
    assert "Обработка: в очереди" in card_call.args[0]
    assert "Google Docs: ожидает" in card_call.args[0]
    buttons = card_call.kwargs["reply_markup"].inline_keyboard[0]
    assert [button.callback_data for button in buttons] == [
        f"{FULL_DREAM_CALLBACK_PREFIX}{dream_id}",
        f"{ADD_NOTE_CALLBACK_PREFIX}{dream_id}",
    ]
    assert "Вопрос заметил" in message.reply_text.await_args_list[1].args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "В терапии я сказал: мне приснился мост.",
        "Мне приснился мост, но не сохраняй этот сон.",
    ],
)
async def test_natural_capture_requires_opening_at_start_and_respects_negation(text: str) -> None:
    update, _message = _make_text_message_update(text, chat_id=42)
    facade = AsyncMock(spec=AssistantFacade)
    context = _make_text_context(facade, 42)

    with patch(
        "app.telegram.handlers.handle_chat_with_metadata",
        new=AsyncMock(return_value=ChatResult("Понял.", [])),
    ) as mock_chat:
        await text_message_handler(update, context)

    facade.create_dream.assert_not_awaited()
    mock_chat.assert_awaited_once()


@pytest.mark.asyncio
async def test_text_message_handler_saves_explicit_dream_command_without_chat_loop() -> None:
    update, message = _make_text_message_update(
        "Можешь записать сон текстом. Сегодня мне приснилось, что я ищу друзей в городе.",
        chat_id=42,
    )
    message.message_id = 93
    created = SimpleNamespace(
        created=True,
        written_to_google_doc=True,
        written_to_doc_name="Dream Archive",
    )
    facade = AsyncMock(spec=AssistantFacade)
    facade.create_dream = AsyncMock(return_value=created)
    context = _make_text_context(facade, 42)

    with patch("app.telegram.handlers.handle_chat_with_metadata", new=AsyncMock()) as mock_chat:
        await text_message_handler(update, context)

    mock_chat.assert_not_awaited()
    facade.create_dream.assert_awaited_once_with(
        "Можешь записать сон текстом. Сегодня мне приснилось, что я ищу друзей в городе.",
        chat_id=42,
        source_event_key="telegram:42:message:93",
    )
    message.reply_text.assert_awaited_once()
    confirmation = message.reply_text.await_args.args[0]
    assert "✅ Сон сохранён" in confirmation
    assert "я ищу друзей в городе" in confirmation
    assert "Google Docs: добавлено" in confirmation
    assert load_pending_dream_draft(42) is None


@pytest.mark.asyncio
async def test_text_message_handler_reports_embedding_limit_for_direct_dream_save() -> None:
    update, message = _make_text_message_update(
        "Запиши сон: мне приснилось море и мост.",
        chat_id=42,
    )
    facade = AsyncMock(spec=AssistantFacade)
    facade.create_dream = AsyncMock(side_effect=DreamRecordingUnavailable("embeddings недоступны"))
    context = _make_text_context(facade, 42)

    with patch("app.telegram.handlers.handle_chat_with_metadata", new=AsyncMock()) as mock_chat:
        await text_message_handler(update, context)

    mock_chat.assert_not_awaited()
    facade.create_dream.assert_awaited_once_with(
        "Запиши сон: мне приснилось море и мост.",
        chat_id=42,
    )
    message.reply_text.assert_awaited_once_with("embeddings недоступны")


@pytest.mark.asyncio
async def test_text_message_handler_asks_for_text_on_empty_explicit_dream_command() -> None:
    update, message = _make_text_message_update("Запиши сон текстом", chat_id=42)
    facade = AsyncMock(spec=AssistantFacade)
    facade.create_dream = AsyncMock()
    context = _make_text_context(facade, 42)

    with patch("app.telegram.handlers.handle_chat_with_metadata", new=AsyncMock()) as mock_chat:
        await text_message_handler(update, context)

    mock_chat.assert_not_awaited()
    facade.create_dream.assert_not_awaited()
    message.reply_text.assert_awaited_once_with(MISSING_DREAM_TEXT_REPLY)


@pytest.mark.asyncio
async def test_text_message_handler_blocks_false_save_confirmation_without_create_tool() -> None:
    update, message = _make_text_message_update("Это новый сон", chat_id=42)
    facade = AsyncMock(spec=AssistantFacade)
    context = _make_text_context(facade, 42)

    with patch(
        "app.telegram.handlers.handle_chat_with_metadata",
        new=AsyncMock(return_value=ChatResult("Сон сохранён и добавлен в документ", [])),
    ):
        await text_message_handler(update, context)

    message.reply_text.assert_awaited_once_with(MISSING_DREAM_TEXT_REPLY)


@pytest.mark.asyncio
async def test_text_message_handler_direct_note_bypasses_chat_loop() -> None:
    update, message = _make_text_message_update("заметка: красная дверь важна", chat_id=42)
    facade = AsyncMock(spec=AssistantFacade)
    facade.add_dream_note = AsyncMock(return_value=(True, "Заметка добавлена под нужным сном."))
    context = _make_text_context(facade, 42)

    with patch("app.telegram.handlers.handle_chat_with_metadata", new=AsyncMock()) as mock_chat:
        await text_message_handler(update, context)

    mock_chat.assert_not_awaited()
    facade.add_dream_note.assert_awaited_once_with(
        "красная дверь важна",
        dream_id=None,
        chat_id=42,
    )
    message.reply_text.assert_awaited_once_with("Заметка добавлена под нужным сном.")


@pytest.mark.asyncio
async def test_text_message_handler_direct_note_targets_replied_dream_message() -> None:
    dream_id = "11111111-1111-4111-8111-111111111111"
    update, message = _make_text_message_update(
        "Добавь заметку к этому сну: красная дверь важна",
        chat_id=42,
    )
    message.reply_to_message = SimpleNamespace(
        message_id=777,
        text="02.08.26 - Включение света в чужой системе",
    )
    save_displayed_dream_message(
        42,
        message_id=777,
        refs=[
            DisplayedDreamRef(
                index=1,
                dream_id=dream_id,
                date="2026-08-02",
                title="Включение света в чужой системе",
            )
        ],
    )
    facade = AsyncMock(spec=AssistantFacade)
    facade.add_dream_note = AsyncMock(return_value=(True, "Заметка добавлена под нужным сном."))
    context = _make_text_context(facade, 42)

    with patch("app.telegram.handlers.handle_chat_with_metadata", new=AsyncMock()) as mock_chat:
        await text_message_handler(update, context)

    mock_chat.assert_not_awaited()
    facade.add_dream_note.assert_awaited_once_with(
        "красная дверь важна",
        dream_id=uuid.UUID(dream_id),
        chat_id=42,
    )
    message.reply_text.assert_awaited_once_with("Заметка добавлена под нужным сном.")


@pytest.mark.asyncio
async def test_reply_note_uses_redis_target_after_process_restart() -> None:
    dream_id = "11111111-1111-4111-8111-111111111111"
    state_store = RedisOperationalStateStore(_FakeRedis(), key_prefix="test:telegram")
    await state_store.save_displayed_message(
        42,
        777,
        DisplayedDreamSet(
            refs=[
                DisplayedDreamRef(
                    index=1,
                    dream_id=dream_id,
                    date="2026-08-02",
                    title="Сон после рестарта",
                )
            ],
            created_at=datetime.now(timezone.utc),
        ),
    )
    clear_displayed_dream_set(42)
    update, message = _make_text_message_update(
        "Добавь заметку к этому сну: важная деталь",
        chat_id=42,
    )
    message.reply_to_message = SimpleNamespace(message_id=777, text="Карточка сна")
    facade = AsyncMock(spec=AssistantFacade)
    facade.add_dream_note = AsyncMock(return_value=(True, "Заметка добавлена под нужным сном."))
    context = _make_text_context(facade, 42)
    context.bot_data["operational_state_store"] = state_store

    await text_message_handler(update, context)

    facade.add_dream_note.assert_awaited_once_with(
        "важная деталь",
        dream_id=uuid.UUID(dream_id),
        chat_id=42,
    )


@pytest.mark.asyncio
async def test_unknown_replied_message_never_falls_back_to_latest_dream() -> None:
    update, message = _make_text_message_update(
        "Добавь заметку к этому сну: важная деталь",
        chat_id=42,
    )
    message.reply_to_message = SimpleNamespace(message_id=999, text="Неизвестное сообщение")
    save_displayed_dream_set(
        42,
        refs=[
            DisplayedDreamRef(
                index=1,
                dream_id="22222222-2222-4222-8222-222222222222",
                date="2026-08-03",
                title="Другой последний сон",
            )
        ],
    )
    facade = AsyncMock(spec=AssistantFacade)
    facade.add_dream_note = AsyncMock()
    context = _make_text_context(facade, 42)

    await text_message_handler(update, context)

    facade.add_dream_note.assert_not_awaited()
    assert "к какому сну" in message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_text_message_handler_direct_note_targets_single_latest_mentioned_dream() -> None:
    dream_id = "22222222-2222-4222-8222-222222222222"
    update, message = _make_text_message_update(
        "Добавь заметку к этому сну: красная дверь важна",
        chat_id=42,
    )
    save_displayed_dream_set(
        42,
        refs=[
            DisplayedDreamRef(
                index=1,
                dream_id=dream_id,
                date="2026-08-02",
                title="Включение света в чужой системе",
            )
        ],
    )
    facade = AsyncMock(spec=AssistantFacade)
    facade.add_dream_note = AsyncMock(return_value=(True, "Заметка добавлена под нужным сном."))
    context = _make_text_context(facade, 42)

    with patch("app.telegram.handlers.handle_chat_with_metadata", new=AsyncMock()) as mock_chat:
        await text_message_handler(update, context)

    mock_chat.assert_not_awaited()
    facade.add_dream_note.assert_awaited_once_with(
        "красная дверь важна",
        dream_id=uuid.UUID(dream_id),
        chat_id=42,
    )
    message.reply_text.assert_awaited_once_with("Заметка добавлена под нужным сном.")


@pytest.mark.asyncio
async def test_text_message_handler_direct_note_does_not_fallback_on_ambiguous_this_dream() -> None:
    update, message = _make_text_message_update(
        "Добавь заметку к этому сну: красная дверь важна",
        chat_id=42,
    )
    save_displayed_dream_set(
        42,
        refs=[
            DisplayedDreamRef(
                index=1,
                dream_id="11111111-1111-4111-8111-111111111111",
                date="2026-08-02",
                title="Первый сон",
            ),
            DisplayedDreamRef(
                index=2,
                dream_id="22222222-2222-4222-8222-222222222222",
                date="2026-08-03",
                title="Второй сон",
            ),
        ],
    )
    facade = AsyncMock(spec=AssistantFacade)
    facade.add_dream_note = AsyncMock()
    context = _make_text_context(facade, 42)

    with patch("app.telegram.handlers.handle_chat_with_metadata", new=AsyncMock()) as mock_chat:
        await text_message_handler(update, context)

    mock_chat.assert_not_awaited()
    facade.add_dream_note.assert_not_awaited()
    message.reply_text.assert_awaited_once()
    assert "к какому сну" in message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_text_message_handler_remembers_created_dream_confirmation_for_reply_note() -> None:
    dream_id = "11111111-1111-4111-8111-111111111111"
    create_update, create_message = _make_text_message_update(
        "Запиши сон: мы прощаемся на станции метро",
        chat_id=42,
    )
    create_message.reply_text.return_value = SimpleNamespace(message_id=901)
    created = SimpleNamespace(
        id=uuid.UUID(dream_id),
        date="2026-08-23",
        title="Прощание с Лизой на станции метро",
        written_to_google_doc=True,
    )
    facade = AsyncMock(spec=AssistantFacade)
    facade.create_dream = AsyncMock(return_value=created)
    facade.add_dream_note = AsyncMock(return_value=(True, "Заметка добавлена под нужным сном."))
    context = _make_text_context(facade, 42)

    await text_message_handler(create_update, context)

    note_update, note_message = _make_text_message_update(
        "Добавь заметку к этому сну: #Лиза #анима #одноклассники",
        chat_id=42,
    )
    note_message.reply_to_message = SimpleNamespace(
        message_id=901,
        text="Сон сохранён и добавлен в документ",
    )
    with patch("app.telegram.handlers.handle_chat_with_metadata", new=AsyncMock()) as mock_chat:
        await text_message_handler(note_update, context)

    mock_chat.assert_not_awaited()
    facade.add_dream_note.assert_awaited_once_with(
        "#Лиза #анима #одноклассники",
        dream_id=uuid.UUID(dream_id),
        chat_id=42,
    )
    note_message.reply_text.assert_awaited_once_with("Заметка добавлена под нужным сном.")


@pytest.mark.asyncio
async def test_text_message_handler_applies_pending_single_note_to_replied_dream() -> None:
    dream_id = "11111111-1111-4111-8111-111111111111"
    update, message = _make_text_message_update(
        "Добавь заметку к этому сну: #Лиза #анима #одноклассники",
        chat_id=42,
    )
    save_displayed_dream_set(
        42,
        refs=[
            DisplayedDreamRef(
                index=1,
                dream_id="22222222-2222-4222-8222-222222222222",
                date="2026-08-22",
                title="Первый сон",
            ),
            DisplayedDreamRef(
                index=2,
                dream_id=dream_id,
                date="2026-08-23",
                title="Прощание с Лизой на станции метро",
            ),
        ],
    )
    facade = AsyncMock(spec=AssistantFacade)
    facade.add_dream_note = AsyncMock(return_value=(True, "Заметка добавлена под нужным сном."))
    context = _make_text_context(facade, 42)

    await text_message_handler(update, context)

    assert load_pending_single_dream_note(42) is not None
    follow_update, follow_message = _make_text_message_update("К этому", chat_id=42)
    follow_message.reply_to_message = SimpleNamespace(message_id=902)
    save_displayed_dream_message(
        42,
        message_id=902,
        refs=[
            DisplayedDreamRef(
                index=1,
                dream_id=dream_id,
                date="2026-08-23",
                title="Прощание с Лизой на станции метро",
            )
        ],
    )

    with patch("app.telegram.handlers.handle_chat_with_metadata", new=AsyncMock()) as mock_chat:
        await text_message_handler(follow_update, context)

    mock_chat.assert_not_awaited()
    facade.add_dream_note.assert_awaited_once_with(
        "#Лиза #анима #одноклассники",
        dream_id=uuid.UUID(dream_id),
        chat_id=42,
    )
    assert load_pending_single_dream_note(42) is None
    follow_message.reply_text.assert_awaited_once_with("Заметка добавлена под нужным сном.")


@pytest.mark.asyncio
async def test_pending_single_failure_retains_redis_state_until_safe_retry() -> None:
    dream_id = "11111111-1111-4111-8111-111111111111"
    state_store = RedisOperationalStateStore(_FakeRedis(), key_prefix="test:telegram")
    pending = save_pending_single_dream_note(42, note_text="важная деталь")
    await state_store.save_pending_single_note(42, pending)
    save_displayed_dream_message(
        42,
        message_id=902,
        refs=[DisplayedDreamRef(1, dream_id, "2026-08-23", "Сон")],
    )
    facade = AsyncMock(spec=AssistantFacade)
    facade.add_dream_note = AsyncMock(return_value=(False, "database unavailable"))
    context = _make_text_context(facade, 42)
    context.bot_data["operational_state_store"] = state_store

    first_update, first_message = _make_text_message_update("К этому", chat_id=42)
    first_message.reply_to_message = SimpleNamespace(message_id=902)
    await text_message_handler(first_update, context)

    assert load_pending_single_dream_note(42) is not None
    assert await state_store.load_pending_single_note(42) is not None
    assert "сохранён для повтора" in first_message.reply_text.await_args.args[0]

    clear_pending_single_dream_note(42)
    facade.add_dream_note.return_value = (True, "queued")
    retry_update, retry_message = _make_text_message_update("К этому", chat_id=42)
    retry_message.reply_to_message = SimpleNamespace(message_id=902)
    await text_message_handler(retry_update, context)

    assert load_pending_single_dream_note(42) is None
    assert await state_store.load_pending_single_note(42) is None
    retry_message.reply_text.assert_awaited_once_with("queued")


@pytest.mark.asyncio
async def test_text_message_handler_bare_context_reference_does_not_create_dream() -> None:
    update, message = _make_text_message_update("К этому", chat_id=42)
    facade = AsyncMock(spec=AssistantFacade)
    context = _make_text_context(facade, 42)

    with patch("app.telegram.handlers.handle_chat_with_metadata", new=AsyncMock()) as mock_chat:
        await text_message_handler(update, context)

    mock_chat.assert_not_awaited()
    facade.create_dream.assert_not_awaited()
    message.reply_text.assert_awaited_once()
    assert "что именно сделать" in message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_text_message_handler_runs_pending_interpretation_after_approval() -> None:
    update, message = _make_text_message_update("да", chat_id=42)
    dream_id = "11111111-1111-4111-8111-111111111111"
    save_pending_interpretation_request(
        42,
        dream_id=dream_id,
        prompt="approved prompt",
    )
    facade = AsyncMock(spec=AssistantFacade)
    facade.interpret_dream_with_prompt = AsyncMock(
        return_value=SimpleNamespace(text="Осторожная интерпретация.")
    )
    context = _make_text_context(facade, 42)

    with patch("app.telegram.handlers.handle_chat_with_metadata", new=AsyncMock()) as mock_chat:
        await text_message_handler(update, context)

    mock_chat.assert_not_awaited()
    facade.interpret_dream_with_prompt.assert_awaited_once()
    assert str(facade.interpret_dream_with_prompt.call_args.kwargs["dream_id"]) == dream_id
    assert facade.interpret_dream_with_prompt.call_args.kwargs["prompt"] == "approved prompt"
    message.reply_text.assert_awaited_once_with("Осторожная интерпретация.")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("заметка: красная дверь важна", "красная дверь важна"),
        (
            "Добавь заметку к последнему сну, что в нём был сексуальный подтекст",
            "в нём был сексуальный подтекст",
        ),
        (
            "Добавь еще заметку к последнему сну: во сне была дача",
            "во сне была дача",
        ),
        ("Добавь заметку к этому сну: во сне была дача", "во сне была дача"),
        ("Добавь заметку к нему: во сне была дача", "во сне была дача"),
        ("add note to the latest dream: red door felt important", "red door felt important"),
        ("add note to this dream: red door felt important", "red door felt important"),
    ],
)
def test_extract_direct_note_text_from_command_phrases(text: str, expected: str) -> None:
    assert _extract_direct_note_text(text) == expected


@pytest.mark.asyncio
async def test_text_message_handler_yes_saves_pending_dream() -> None:
    confirm_update, confirm_message = _make_text_message_update("да", chat_id=42)
    created = SimpleNamespace(
        created=True,
        written_to_google_doc=True,
        written_to_doc_name="Dream Archive",
    )
    facade = AsyncMock(spec=AssistantFacade)
    facade.create_dream = AsyncMock(return_value=created)
    context = _make_text_context(facade, 42)
    save_pending_dream_draft(
        42,
        raw_text="сегодня мне приснилось, что я иду по мосту над морем",
        title=None,
        dream_date=None,
        source_message_id=123,
        source_kind="text",
    )

    await text_message_handler(confirm_update, context)

    facade.create_dream.assert_awaited_once_with(
        "сегодня мне приснилось, что я иду по мосту над морем",
        title=None,
        dream_date=None,
        chat_id=42,
        source_event_key="telegram:42:message:123",
    )
    confirm_message.reply_text.assert_awaited_once()
    confirmation = confirm_message.reply_text.await_args.args[0]
    assert "✅ Сон сохранён" in confirmation
    assert "я иду по мосту над морем" in confirmation
    assert load_pending_dream_draft(42) is None


@pytest.mark.asyncio
async def test_pending_dream_confirmation_survives_process_restart() -> None:
    state_store = RedisOperationalStateStore(_FakeRedis(), key_prefix="test:telegram")
    await state_store.save_pending_dream(
        42,
        PendingDreamDraft(
            raw_text="мне приснился мост",
            title=None,
            dream_date=None,
            source_message_id=123,
            source_kind="text",
            created_at=datetime.now(timezone.utc),
        ),
    )
    clear_pending_dream_draft(42)
    update, message = _make_text_message_update("да", chat_id=42)
    facade = AsyncMock(spec=AssistantFacade)
    facade.create_dream = AsyncMock(
        return_value=SimpleNamespace(created=True, written_to_google_doc=True)
    )
    context = _make_text_context(facade, 42)
    context.bot_data["operational_state_store"] = state_store

    await text_message_handler(update, context)

    facade.create_dream.assert_awaited_once_with(
        "мне приснился мост",
        title=None,
        dream_date=None,
        chat_id=42,
        source_event_key="telegram:42:message:123",
    )
    assert await state_store.load_pending_dream(42) is None
    assert "Сон сохранён" in message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_direct_save_clears_stale_persisted_confirmation() -> None:
    state_store = RedisOperationalStateStore(_FakeRedis(), key_prefix="test:telegram")
    await state_store.save_pending_dream(
        42,
        PendingDreamDraft(
            raw_text="старый черновик сна",
            title=None,
            dream_date=None,
            source_message_id=120,
            source_kind="text",
            created_at=datetime.now(timezone.utc),
        ),
    )
    update, _message = _make_text_message_update(
        "сегодня мне приснилось, что я иду по новому мосту",
        chat_id=42,
    )
    facade = AsyncMock(spec=AssistantFacade)
    facade.create_dream.return_value = SimpleNamespace(
        created=True,
        written_to_google_doc=False,
        processing_status="pending",
        semantic_index_status="pending",
        google_doc_write_status="pending",
    )
    context = _make_text_context(facade, 42)
    context.bot_data["operational_state_store"] = state_store

    await text_message_handler(update, context)
    clear_pending_dream_draft(42)  # Simulate the next process reading only Redis.

    assert await state_store.load_pending_dream(42) is None


@pytest.mark.asyncio
async def test_pending_interpretation_confirmation_survives_process_restart() -> None:
    dream_id = "11111111-1111-4111-8111-111111111111"
    state_store = RedisOperationalStateStore(_FakeRedis(), key_prefix="test:telegram")
    await state_store.save_pending_interpretation(
        42,
        PendingInterpretationRequest(
            dream_id=dream_id,
            prompt="Бережно разобрать образ моста",
            source_message_id=124,
            created_at=datetime.now(timezone.utc),
        ),
    )
    clear_pending_interpretation_request(42)
    update, message = _make_text_message_update("да", chat_id=42)
    facade = AsyncMock(spec=AssistantFacade)
    facade.interpret_dream_with_prompt = AsyncMock(
        return_value=SimpleNamespace(text="Осторожная гипотеза.")
    )
    context = _make_text_context(facade, 42)
    context.bot_data["operational_state_store"] = state_store

    await text_message_handler(update, context)

    facade.interpret_dream_with_prompt.assert_awaited_once_with(
        dream_id=uuid.UUID(dream_id),
        prompt="Бережно разобрать образ моста",
    )
    assert await state_store.load_pending_interpretation(42) is None
    message.reply_text.assert_awaited_once_with("Осторожная гипотеза.")


@pytest.mark.asyncio
async def test_failed_pending_dream_save_preserves_draft_for_retry() -> None:
    confirm_update, confirm_message = _make_text_message_update("да", chat_id=42)
    facade = AsyncMock(spec=AssistantFacade)
    facade.create_dream = AsyncMock(side_effect=DreamRecordingUnavailable("embeddings недоступны"))
    context = _make_text_context(facade, 42)
    save_pending_dream_draft(
        42,
        raw_text="сегодня мне приснилось, что я иду по мосту над морем",
        title=None,
        dream_date=None,
        source_message_id=123,
        source_kind="text",
    )

    await text_message_handler(confirm_update, context)

    confirm_message.reply_text.assert_awaited_once_with("embeddings недоступны")
    retained = load_pending_dream_draft(42)
    assert retained is not None
    assert retained.raw_text == "сегодня мне приснилось, что я иду по мосту над морем"


@pytest.mark.asyncio
async def test_text_message_handler_no_clears_pending_dream() -> None:
    decline_update, decline_message = _make_text_message_update("нет", chat_id=42)
    facade = AsyncMock(spec=AssistantFacade)
    context = _make_text_context(facade, 42)
    save_pending_dream_draft(
        42,
        raw_text="сегодня мне приснилось, что я иду по мосту над морем",
        title=None,
        dream_date=None,
        source_message_id=123,
        source_kind="text",
    )

    await text_message_handler(decline_update, context)

    facade.create_dream.assert_not_awaited()
    decline_message.reply_text.assert_awaited_once_with("Хорошо, не сохраняю.")
    assert load_pending_dream_draft(42) is None


def test_format_create_dream_reply_hides_doc_label_on_success() -> None:
    created = SimpleNamespace(
        created=True,
        written_to_google_doc=True,
        written_to_doc_name="...O1rHIxHs",
    )

    reply = _format_create_dream_reply(created)
    assert "✅ Сон сохранён" in reply
    assert "Архив: сохранено" in reply
    assert "Google Docs: добавлено" in reply
    assert "...O1rHIxHs" not in reply


def test_format_create_dream_reply_does_not_claim_doc_write_on_failure() -> None:
    created = SimpleNamespace(
        created=True,
        written_to_google_doc=False,
        written_to_doc_name="Dream Archive",
    )

    reply = _format_create_dream_reply(created)
    assert "Архив: сохранено" in reply
    assert "Google Docs: нужен повтор" in reply
    assert "повтори запись в Google Doc" in reply


def test_format_create_dream_reply_confirms_duplicate_doc_rewrite() -> None:
    created = SimpleNamespace(
        created=False,
        written_to_google_doc=True,
        written_to_doc_name="Dream Archive",
    )

    reply = _format_create_dream_reply(created)
    assert "уже был в архиве" in reply
    assert "Архив: без дубля" in reply
    assert "Google Docs: добавлено" in reply


class _ReactionSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.executed: list[object] = []
        self.committed = False

    def add(self, value: object) -> None:
        self.added.append(value)

    async def execute(self, statement: object) -> None:
        self.executed.append(statement)

    async def commit(self) -> None:
        self.committed = True


class _ReactionSessionFactory:
    def __init__(self, session: _ReactionSession) -> None:
        self.session = session

    def __call__(self) -> "_ReactionSessionFactory":
        return self

    async def __aenter__(self) -> _ReactionSession:
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


@pytest.mark.asyncio
async def test_handle_message_reaction_persists_new_reaction() -> None:
    session = _ReactionSession()
    update = Update(
        update_id=1,
        message_reaction=MessageReactionUpdated(
            chat=Chat(id=77, type="private"),
            message_id=501,
            date=datetime.now(timezone.utc),
            old_reaction=[],
            new_reaction=[ReactionTypeEmoji("🔥")],
        ),
    )
    context = SimpleNamespace(bot_data={"session_factory": _ReactionSessionFactory(session)})

    await handle_message_reaction(update, context)

    assert len(session.added) == 1
    reaction = session.added[0]
    assert reaction.message_id == 501
    assert reaction.chat_id == 77
    assert reaction.emoji == "🔥"
    assert session.committed is True


@pytest.mark.asyncio
async def test_handle_message_reaction_marks_reaction_removed() -> None:
    session = _ReactionSession()
    update = Update(
        update_id=1,
        message_reaction=MessageReactionUpdated(
            chat=Chat(id=88, type="private"),
            message_id=701,
            date=datetime.now(timezone.utc),
            old_reaction=[ReactionTypeEmoji("👍")],
            new_reaction=[],
        ),
    )
    context = SimpleNamespace(bot_data={"session_factory": _ReactionSessionFactory(session)})

    await handle_message_reaction(update, context)

    assert len(session.executed) == 1
    compiled = str(session.executed[0])
    params = session.executed[0].compile().params
    assert "UPDATE message_reactions" in compiled
    assert "removed_at" in compiled
    assert params["message_id_1"] == 701
    assert params["chat_id_1"] == 88
    assert session.committed is True


@pytest.mark.asyncio
async def test_handle_message_reaction_replaces_old_reaction_with_new_one() -> None:
    session = _ReactionSession()
    update = Update(
        update_id=1,
        message_reaction=MessageReactionUpdated(
            chat=Chat(id=91, type="private"),
            message_id=801,
            date=datetime.now(timezone.utc),
            old_reaction=[ReactionTypeEmoji("👎")],
            new_reaction=[ReactionTypeEmoji("👍")],
        ),
    )
    context = SimpleNamespace(bot_data={"session_factory": _ReactionSessionFactory(session)})

    await handle_message_reaction(update, context)

    assert len(session.added) == 1
    assert session.added[0].emoji == "👍"
    assert len(session.executed) == 1
    compiled = str(session.executed[0])
    assert "UPDATE message_reactions" in compiled
    assert session.committed is True
