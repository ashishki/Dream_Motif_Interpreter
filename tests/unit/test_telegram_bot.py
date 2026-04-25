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
from app.telegram.bot import handle_message_reaction
from app.telegram.handlers import (
    FEEDBACK_PROMPT,
    VOICE_PROCESSING_ACK,
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
    message.reply_text.assert_awaited_once_with(f"Here are your dreams.\n\n{FEEDBACK_PROMPT}")


def test_voice_processing_ack_is_russian() -> None:
    assert VOICE_PROCESSING_ACK == "Обрабатываю голосовое сообщение..."


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

    message.reply_text.assert_awaited_once_with(f"pong\n\n{FEEDBACK_PROMPT}")


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

    message.reply_text.assert_awaited_once_with(f"{insufficient_reply}\n\n{FEEDBACK_PROMPT}")


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
    message.reply_text.assert_awaited_once_with(f"pong\n\n{FEEDBACK_PROMPT}")


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
