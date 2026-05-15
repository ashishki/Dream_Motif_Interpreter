from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Chat, MessageReactionUpdated, ReactionTypeEmoji, Update
from telegram.constants import ChatAction
from telegram.ext import ApplicationHandlerStop

from app.assistant.chat import ChatResult
from app.assistant.facade import AssistantFacade
from app.assistant.session import (
    clear_pending_dream_draft,
    clear_pending_interpretation_request,
    load_pending_dream_draft,
    save_pending_interpretation_request,
    save_pending_dream_draft,
)
from app.telegram.bot import handle_message_reaction
from app.telegram.handlers import (
    FEEDBACK_PROMPT,
    MAX_PENDING_FEEDBACK_REQUESTS,
    VOICE_PROCESSING_ACK,
    _extract_direct_note_text,
    _remember_feedback_request,
    _format_create_dream_reply,
    _split_telegram_text,
    chat_guard,
    text_message_handler,
)


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
    clear_pending_interpretation_request(42)
    clear_pending_interpretation_request(55)
    clear_pending_interpretation_request(77)
    clear_pending_interpretation_request(100)
    yield
    clear_pending_dream_draft(42)
    clear_pending_dream_draft(55)
    clear_pending_dream_draft(77)
    clear_pending_dream_draft(100)
    clear_pending_interpretation_request(42)
    clear_pending_interpretation_request(55)
    clear_pending_interpretation_request(77)
    clear_pending_interpretation_request(100)


@pytest.mark.asyncio
async def test_text_message_handler_routes_to_handle_chat() -> None:
    update, message = _make_text_message_update("what are my recent dreams?", chat_id=42)
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
    )
    message.reply_text.assert_awaited_once_with("Here are your dreams.")


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

    message.reply_text.assert_awaited_once_with("Thanks, noted.")


def test_split_telegram_text_keeps_long_responses_under_limit() -> None:
    text = ("word " * 1700) + "\nfinal line"

    chunks = _split_telegram_text(text)

    assert len(chunks) >= 3
    assert all(len(chunk) <= 3900 for chunk in chunks)
    assert "".join(chunks) == text


@pytest.mark.asyncio
async def test_text_message_handler_saves_short_natural_dream_without_confirmation() -> None:
    update, message = _make_text_message_update("сегодня мне приснилось рыба", chat_id=42)
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
    facade.create_dream.assert_awaited_once_with("сегодня мне приснилось рыба", chat_id=42)
    message.reply_text.assert_awaited_once_with("Сон сохранён и добавлен в документ")
    assert load_pending_dream_draft(42) is None


@pytest.mark.asyncio
async def test_text_message_handler_direct_note_bypasses_chat_loop() -> None:
    update, message = _make_text_message_update("заметка: красная дверь важна", chat_id=42)
    facade = AsyncMock(spec=AssistantFacade)
    facade.add_dream_note = AsyncMock(return_value=(True, "Заметка добавлена под нужным сном."))
    context = _make_text_context(facade, 42)

    with patch("app.telegram.handlers.handle_chat_with_metadata", new=AsyncMock()) as mock_chat:
        await text_message_handler(update, context)

    mock_chat.assert_not_awaited()
    facade.add_dream_note.assert_awaited_once_with("красная дверь важна", chat_id=42)
    message.reply_text.assert_awaited_once_with("Заметка добавлена под нужным сном.")


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
        ("add note to the latest dream: red door felt important", "red door felt important"),
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
    )
    confirm_message.reply_text.assert_awaited_once_with("Сон сохранён и добавлен в документ")
    assert load_pending_dream_draft(42) is None


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

    assert _format_create_dream_reply(created) == "Сон сохранён и добавлен в документ"


def test_format_create_dream_reply_does_not_claim_doc_write_on_failure() -> None:
    created = SimpleNamespace(
        created=True,
        written_to_google_doc=False,
        written_to_doc_name="Dream Archive",
    )

    assert _format_create_dream_reply(created) == (
        "Сон сохранён в архиве. "
        "Чтобы повторить запись в Google Doc, скажите «повтори запись в Google Doc»."
    )


def test_format_create_dream_reply_does_not_claim_duplicate_doc_write() -> None:
    created = SimpleNamespace(
        created=False,
        written_to_google_doc=True,
        written_to_doc_name="Dream Archive",
    )

    assert (
        _format_create_dream_reply(created)
        == "Эта запись уже есть в архиве. В Google Doc повторно не записываю."
    )


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
