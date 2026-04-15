"""Unit tests for the bounded chat/tool-use loop in app.assistant.chat."""
from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.assistant.chat import handle_chat, _extract_text
from app.assistant.facade import (
    AssistantFacade,
    SearchResult,
    SearchResultItem,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_facade(**kwargs: object) -> AssistantFacade:
    """Build a minimal AssistantFacade-shaped mock."""
    facade = AsyncMock(spec=AssistantFacade)
    for attr, value in kwargs.items():
        setattr(facade, attr, value)
    return facade


def _text_block(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _tool_use_block(name: str, tool_id: str, input_: dict) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.id = tool_id
    block.input = input_
    return block


def _make_response(stop_reason: str, content: list) -> MagicMock:
    resp = MagicMock()
    resp.stop_reason = stop_reason
    resp.content = content
    return resp


# ---------------------------------------------------------------------------
# _extract_text
# ---------------------------------------------------------------------------


def test_extract_text_returns_concatenated_text_blocks() -> None:
    resp = _make_response("end_turn", [_text_block("Hello "), _text_block("world")])
    assert _extract_text(resp) == "Hello world"


def test_extract_text_skips_non_text_blocks() -> None:
    resp = _make_response("tool_use", [_tool_use_block("search_dreams", "t1", {}), _text_block("hi")])
    assert _extract_text(resp) == "hi"


# ---------------------------------------------------------------------------
# handle_chat — no API key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_chat_returns_error_when_no_api_key() -> None:
    facade = _make_facade()
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}):
        result = await handle_chat("hello", facade)
    assert "not available" in result.lower() or "api key" in result.lower()


# ---------------------------------------------------------------------------
# handle_chat — end_turn (no tool use)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_chat_returns_assistant_text_on_end_turn() -> None:
    facade = _make_facade()
    final_response = _make_response("end_turn", [_text_block("Here is your answer.")])

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        with patch("app.assistant.chat.AsyncAnthropic") as mock_client_cls:
            client = AsyncMock()
            client.messages.create = AsyncMock(return_value=final_response)
            mock_client_cls.return_value = client

            result = await handle_chat("what are my recent dreams?", facade)

    assert result == "Here is your answer."


# ---------------------------------------------------------------------------
# handle_chat — single tool-use round then end_turn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_chat_executes_search_tool_and_returns_final_text() -> None:
    dream_id = uuid.uuid4()
    facade = AsyncMock(spec=AssistantFacade)
    facade.search_dreams = AsyncMock(
        return_value=SearchResult(
            items=[
                SearchResultItem(
                    dream_id=dream_id,
                    date=date(2024, 3, 1),
                    chunk_text="I was flying over a city.",
                    relevance_score=0.85,
                    matched_fragments=[],
                )
            ]
        )
    )

    tool_response = _make_response(
        "tool_use",
        [_tool_use_block("search_dreams", "t1", {"query": "flying"})],
    )
    final_response = _make_response("end_turn", [_text_block("Found a flying dream from 2024-03-01.")])

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        with patch("app.assistant.chat.AsyncAnthropic") as mock_client_cls:
            client = AsyncMock()
            client.messages.create = AsyncMock(side_effect=[tool_response, final_response])
            mock_client_cls.return_value = client

            result = await handle_chat("find flying dreams", facade)

    assert "flying" in result.lower() or "2024" in result
    facade.search_dreams.assert_awaited_once_with("flying")


# ---------------------------------------------------------------------------
# handle_chat — insufficient evidence path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_chat_propagates_insufficient_evidence_through_tool_result() -> None:
    facade = AsyncMock(spec=AssistantFacade)
    facade.search_dreams = AsyncMock(
        return_value=SearchResult(items=[], insufficient_reason="no similar dreams found")
    )

    tool_response = _make_response(
        "tool_use",
        [_tool_use_block("search_dreams", "t2", {"query": "unicorn riding"})],
    )
    final_response = _make_response(
        "end_turn", [_text_block("The archive has no evidence of unicorn dreams.")]
    )

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        with patch("app.assistant.chat.AsyncAnthropic") as mock_client_cls:
            client = AsyncMock()
            client.messages.create = AsyncMock(side_effect=[tool_response, final_response])
            mock_client_cls.return_value = client

            result = await handle_chat("did I dream about unicorns?", facade)

    assert "no evidence" in result.lower() or "archive" in result.lower()


# ---------------------------------------------------------------------------
# handle_chat — Claude API error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_chat_returns_error_string_when_claude_raises() -> None:
    facade = _make_facade()

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        with patch("app.assistant.chat.AsyncAnthropic") as mock_client_cls:
            client = AsyncMock()
            client.messages.create = AsyncMock(side_effect=RuntimeError("timeout"))
            mock_client_cls.return_value = client

            result = await handle_chat("hello", facade)

    assert "something went wrong" in result.lower() or "error" in result.lower()


# ---------------------------------------------------------------------------
# handle_chat — tool loop guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_chat_stops_after_max_tool_rounds() -> None:
    facade = AsyncMock(spec=AssistantFacade)
    facade.list_recent_dreams = AsyncMock(return_value=[])

    always_tool = _make_response(
        "tool_use",
        [_tool_use_block("list_recent_dreams", "t3", {})],
    )
    # Claude keeps returning tool_use — the loop guard must fire at MAX_TOOL_ROUNDS
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        with patch("app.assistant.chat.AsyncAnthropic") as mock_client_cls:
            client = AsyncMock()
            client.messages.create = AsyncMock(return_value=always_tool)
            mock_client_cls.return_value = client

            result = await handle_chat("list dreams", facade)

    # The guard fires and we fall through; last_text was empty so we get the fallback
    assert isinstance(result, str)
