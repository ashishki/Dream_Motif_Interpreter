"""Tests for feedback context injection into system prompt."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.chat import handle_chat_with_metadata
from app.assistant.facade import AssistantFacade
from app.assistant.prompts import SYSTEM_PROMPT, build_system_prompt
from app.services.feedback_service import FeedbackService


def test_build_system_prompt_no_feedback_returns_base_prompt() -> None:
    assert build_system_prompt(None) == SYSTEM_PROMPT
    assert build_system_prompt([]) == SYSTEM_PROMPT


def test_build_system_prompt_with_comment_includes_feedback_section() -> None:
    rows = [
        {"score": 2, "comment": "Too long", "created_at": datetime(2026, 4, 1)},
        {"score": 5, "comment": "Excellent", "created_at": datetime(2026, 4, 10)},
    ]
    result = build_system_prompt(rows)
    assert result.startswith(SYSTEM_PROMPT)
    assert "## Recent User Feedback" in result
    assert "score=2/5" in result
    assert '"Too long"' in result
    assert "score=5/5" in result
    assert '"Excellent"' in result


def test_build_system_prompt_low_score_no_comment() -> None:
    rows = [{"score": 1, "comment": None, "created_at": datetime(2026, 4, 5)}]
    result = build_system_prompt(rows)
    assert "score=1/5 (no comment)" in result


def test_build_system_prompt_rows_ordered_oldest_first() -> None:
    rows = [
        {"score": 3, "comment": "first", "created_at": datetime(2026, 4, 1)},
        {"score": 4, "comment": "last", "created_at": datetime(2026, 4, 15)},
    ]
    result = build_system_prompt(rows)
    assert result.index('"first"') < result.index('"last"')


@pytest.mark.asyncio
async def test_get_recent_for_context_returns_empty_list_when_no_rows() -> None:
    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    rows = await FeedbackService().get_recent_for_context(mock_session)
    assert rows == []


@pytest.mark.asyncio
async def test_handle_chat_with_metadata_uses_built_system_prompt() -> None:
    facade = AsyncMock(spec=AssistantFacade)
    final_response = MagicMock()
    final_response.stop_reason = "end_turn"
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "Answer"
    final_response.content = [text_block]

    mock_session = AsyncMock()
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    feedback_rows = [{"score": 2, "comment": "Too long", "created_at": datetime(2026, 4, 1)}]
    expected_prompt = build_system_prompt(feedback_rows)
    settings = SimpleNamespace(
        MOTIF_INDUCTION_ENABLED=True,
        RESEARCH_AUGMENTATION_ENABLED=True,
    )

    with (
        patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}),
        patch("app.assistant.chat.AsyncAnthropic") as mock_client_cls,
        patch("app.assistant.chat.load_history", new=AsyncMock(return_value=[])),
        patch.object(
            FeedbackService,
            "get_recent_for_context",
            new=AsyncMock(return_value=feedback_rows),
        ),
        patch("app.assistant.chat.get_settings", return_value=settings),
    ):
        client = AsyncMock()
        client.messages.create = AsyncMock(return_value=final_response)
        mock_client_cls.return_value = client

        result = await handle_chat_with_metadata(
            "hello",
            facade,
            session_factory=session_factory,
            chat_id=77,
        )

    assert result.text == "Answer"
    assert client.messages.create.await_args.kwargs["system"] == expected_prompt
