from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Update
from telegram.ext import ApplicationHandlerStop

from app.assistant.chat import ChatResult
from app.assistant.facade import AssistantFacade
from app.telegram.handlers import FEEDBACK_PROMPT, chat_guard, text_message_handler


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


@pytest.mark.asyncio
async def test_text_message_handler_routes_to_handle_chat() -> None:
    update, message = _make_text_message_update("what are my recent dreams?", chat_id=42)
    facade = AsyncMock(spec=AssistantFacade)
    context = SimpleNamespace(
        bot_data={"facade": facade, "session_factory": None, "allowed_chat_id": 42}
    )

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


@pytest.mark.asyncio
async def test_text_message_handler_sends_handle_chat_response() -> None:
    update, message = _make_text_message_update("hello", chat_id=7)
    facade = AsyncMock(spec=AssistantFacade)
    context = SimpleNamespace(
        bot_data={"facade": facade, "session_factory": None, "allowed_chat_id": 7}
    )

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
    context = SimpleNamespace(
        bot_data={"facade": facade, "session_factory": None, "allowed_chat_id": 5}
    )

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
