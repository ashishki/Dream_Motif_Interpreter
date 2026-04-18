from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.assistant.chat import ChatResult
from app.assistant.facade import AssistantFacade
from app.services.feedback_service import FeedbackService
from app.telegram.handlers import text_message_handler


class StubSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.committed = False

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.committed = True


class StubSessionFactory:
    def __init__(self, session: StubSession) -> None:
        self.session = session

    def __call__(self) -> "StubSessionFactory":
        return self

    async def __aenter__(self) -> StubSession:
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


def _make_update(
    text: str,
    *,
    chat_id: int = 77,
    sent_message_id: int = 9001,
    reply_to_message_id: int | None = None,
) -> tuple[MagicMock, AsyncMock]:
    message = AsyncMock()
    message.text = text
    message.reply_text = AsyncMock(return_value=SimpleNamespace(message_id=sent_message_id))
    if reply_to_message_id is not None:
        message.reply_to_message = SimpleNamespace(message_id=reply_to_message_id)
    else:
        message.reply_to_message = None

    update = MagicMock()
    update.effective_message = message
    update.effective_chat = SimpleNamespace(id=chat_id)
    return update, message


def _make_context(session_factory: object | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        bot_data={
            "facade": AsyncMock(spec=AssistantFacade),
            "session_factory": session_factory,
            "allowed_chat_id": 77,
        }
    )


@pytest.mark.asyncio
async def test_digit_message_after_substantive_response_records_feedback() -> None:
    session = StubSession()
    context = _make_context(StubSessionFactory(session))
    update1, message1 = _make_update("hello")
    update2, message2 = _make_update("3")

    with (
        patch(
            "app.telegram.handlers.handle_chat_with_metadata",
            new=AsyncMock(return_value=ChatResult("Detailed interpretation", ["search_dreams"])),
        ),
        patch.object(FeedbackService, "record", new=AsyncMock()) as mock_record,
    ):
        await text_message_handler(update1, context)
        await text_message_handler(update2, context)

    mock_record.assert_awaited_once()
    _, score, feedback_context, record_session = mock_record.await_args.args
    assert score == 3
    assert feedback_context == {
        "message_id": 9001,
        "response_summary": "Detailed interpretation",
        "tool_calls_made": ["search_dreams"],
    }
    assert record_session is session
    assert session.committed is True
    message1.reply_text.assert_awaited_once_with(
        "Detailed interpretation\n\nReply to this message to rate (1–5), or add a comment after the digit."
    )
    message2.reply_text.assert_awaited_once_with("Thanks, noted.")


@pytest.mark.asyncio
async def test_digit_outside_range_is_not_treated_as_rating() -> None:
    session = StubSession()
    context = _make_context(StubSessionFactory(session))
    update1, _ = _make_update("hello")
    update2, message2 = _make_update("6", sent_message_id=9002)

    with (
        patch(
            "app.telegram.handlers.handle_chat_with_metadata",
            new=AsyncMock(
                side_effect=[
                    ChatResult("First substantive reply", []),
                    ChatResult("Second substantive reply", []),
                ]
            ),
        ) as mock_chat,
        patch.object(FeedbackService, "record", new=AsyncMock()) as mock_record,
    ):
        await text_message_handler(update1, context)
        await text_message_handler(update2, context)

    assert mock_chat.await_count == 2
    mock_record.assert_not_awaited()
    assert session.committed is False
    message2.reply_text.assert_awaited_once_with(
        "Second substantive reply\n\nReply to this message to rate (1–5), or add a comment after the digit."
    )


@pytest.mark.asyncio
async def test_message_with_digits_and_other_characters_is_not_treated_as_rating() -> None:
    session = StubSession()
    context = _make_context(StubSessionFactory(session))
    update1, _ = _make_update("hello")
    update2, message2 = _make_update("ok 3", sent_message_id=9002)

    with (
        patch(
            "app.telegram.handlers.handle_chat_with_metadata",
            new=AsyncMock(
                side_effect=[
                    ChatResult("First substantive reply", []),
                    ChatResult("Mixed text handled normally", []),
                ]
            ),
        ) as mock_chat,
        patch.object(FeedbackService, "record", new=AsyncMock()) as mock_record,
    ):
        await text_message_handler(update1, context)
        await text_message_handler(update2, context)

    assert mock_chat.await_count == 2
    mock_record.assert_not_awaited()
    assert session.committed is False
    message2.reply_text.assert_awaited_once_with(
        "Mixed text handled normally\n\nReply to this message to rate (1–5), or add a comment after the digit."
    )


@pytest.mark.asyncio
async def test_digit_message_before_any_substantive_response_is_not_treated_as_rating() -> None:
    session = StubSession()
    context = _make_context(StubSessionFactory(session))
    update, message = _make_update("3")

    with (
        patch(
            "app.telegram.handlers.handle_chat_with_metadata",
            new=AsyncMock(return_value=ChatResult("Digit treated as normal input", [])),
        ) as mock_chat,
        patch.object(FeedbackService, "record", new=AsyncMock()) as mock_record,
    ):
        await text_message_handler(update, context)

    mock_chat.assert_awaited_once()
    mock_record.assert_not_awaited()
    assert session.committed is False
    message.reply_text.assert_awaited_once_with(
        "Digit treated as normal input\n\nReply to this message to rate (1–5), or add a comment after the digit."
    )


@pytest.mark.asyncio
async def test_feedback_service_record_rejects_invalid_score() -> None:
    session = StubSession()

    with pytest.raises(ValueError):
        await FeedbackService().record("77", 6, {"message_id": 1}, session)


@pytest.mark.asyncio
async def test_valid_digit_capture_replies_with_acknowledgement() -> None:
    session = StubSession()
    context = _make_context(StubSessionFactory(session))
    update1, _ = _make_update("hello")
    update2, message2 = _make_update("5")

    with (
        patch(
            "app.telegram.handlers.handle_chat_with_metadata",
            new=AsyncMock(return_value=ChatResult("Substantive reply", [])),
        ),
        patch.object(FeedbackService, "record", new=AsyncMock()),
    ):
        await text_message_handler(update1, context)
        await text_message_handler(update2, context)

    message2.reply_text.assert_awaited_once_with("Thanks, noted.")


@pytest.mark.asyncio
async def test_reply_to_bot_message_with_digit_records_feedback() -> None:
    session = StubSession()
    context = _make_context(StubSessionFactory(session))
    update1, _ = _make_update("hello", sent_message_id=9001)
    update2, message2 = _make_update("4", reply_to_message_id=9001)

    with (
        patch(
            "app.telegram.handlers.handle_chat_with_metadata",
            new=AsyncMock(return_value=ChatResult("Detailed interpretation", ["search_dreams"])),
        ),
        patch.object(FeedbackService, "record", new=AsyncMock()) as mock_record,
    ):
        await text_message_handler(update1, context)
        await text_message_handler(update2, context)

    mock_record.assert_awaited_once()
    _, score, feedback_context, record_session = mock_record.await_args.args
    assert score == 4
    assert feedback_context == {
        "message_id": 9001,
        "response_summary": "Detailed interpretation",
        "tool_calls_made": ["search_dreams"],
    }
    assert record_session is session
    assert mock_record.await_args.kwargs == {"comment": None}
    assert session.committed is True
    message2.reply_text.assert_awaited_once_with("Thanks, noted.")


@pytest.mark.asyncio
async def test_reply_to_bot_message_with_digit_and_comment_records_feedback_with_comment() -> None:
    session = StubSession()
    context = _make_context(StubSessionFactory(session))
    update1, _ = _make_update("hello", sent_message_id=9001)
    update2, message2 = _make_update("5 Great!", reply_to_message_id=9001)

    with (
        patch(
            "app.telegram.handlers.handle_chat_with_metadata",
            new=AsyncMock(return_value=ChatResult("Detailed interpretation", ["search_dreams"])),
        ),
        patch.object(FeedbackService, "record", new=AsyncMock()) as mock_record,
    ):
        await text_message_handler(update1, context)
        await text_message_handler(update2, context)

    mock_record.assert_awaited_once()
    _, score, feedback_context, record_session = mock_record.await_args.args
    assert score == 5
    assert feedback_context == {
        "message_id": 9001,
        "response_summary": "Detailed interpretation",
        "tool_calls_made": ["search_dreams"],
    }
    assert record_session is session
    assert mock_record.await_args.kwargs == {"comment": "Great!"}
    assert session.committed is True
    message2.reply_text.assert_awaited_once_with("Thanks, noted.")


@pytest.mark.asyncio
async def test_reply_to_bot_message_with_text_only_treated_as_chat() -> None:
    session = StubSession()
    context = _make_context(StubSessionFactory(session))
    update1, _ = _make_update("hello", sent_message_id=9001)
    update2, message2 = _make_update("nice", sent_message_id=9002, reply_to_message_id=9001)

    with (
        patch(
            "app.telegram.handlers.handle_chat_with_metadata",
            new=AsyncMock(
                side_effect=[
                    ChatResult("First substantive reply", []),
                    ChatResult("Text-only reply handled as chat", []),
                ]
            ),
        ) as mock_chat,
        patch.object(FeedbackService, "record", new=AsyncMock()) as mock_record,
    ):
        await text_message_handler(update1, context)
        await text_message_handler(update2, context)

    assert mock_chat.await_count == 2
    mock_record.assert_not_awaited()
    assert session.committed is False
    message2.reply_text.assert_awaited_once_with(
        "Text-only reply handled as chat\n\nReply to this message to rate (1–5), or add a comment after the digit."
    )


@pytest.mark.asyncio
async def test_reply_to_different_message_id_treated_as_chat() -> None:
    session = StubSession()
    context = _make_context(StubSessionFactory(session))
    update1, _ = _make_update("hello", sent_message_id=9001)
    update2, message2 = _make_update("4", sent_message_id=9002, reply_to_message_id=9999)

    with (
        patch(
            "app.telegram.handlers.handle_chat_with_metadata",
            new=AsyncMock(
                side_effect=[
                    ChatResult("First substantive reply", []),
                    ChatResult("Different reply target handled as chat", []),
                ]
            ),
        ) as mock_chat,
        patch.object(FeedbackService, "record", new=AsyncMock()) as mock_record,
    ):
        await text_message_handler(update1, context)
        await text_message_handler(update2, context)

    assert mock_chat.await_count == 2
    mock_record.assert_not_awaited()
    assert session.committed is False
    message2.reply_text.assert_awaited_once_with(
        "Different reply target handled as chat\n\nReply to this message to rate (1–5), or add a comment after the digit."
    )
