"""Bounded conversational tool-use loop for the dream archive assistant."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import re
from typing import Any

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.assistant.facade import AssistantFacade
from app.assistant.facade import _application_today
from app.assistant.prompts import SYSTEM_PROMPT, build_system_prompt
from app.assistant.session import load_history, save_history
from app.assistant.tools import build_tools, execute_tool
from app.services.feedback_service import FeedbackService
from app.shared.config import get_settings

LOGGER = logging.getLogger(__name__)

_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOOL_ROUNDS = 5
_FULL_DREAM_TEXT_TOOLS = {"get_dream", "search_dreams_by_title"}
_EXPLICIT_FULL_TEXT_MARKERS = (
    "полный текст",
    "полную запись",
    "весь текст",
    "всю запись",
    "full text",
    "complete text",
    "entire text",
    "whole text",
    "verbatim",
)
_COMPLETENESS_MARKERS = (
    "полностью",
    "целиком",
    "без сокращ",
    "не сокращ",
    "не обрез",
    "entire dream",
    "complete dream",
)
_DREAM_MARKERS = ("сон", "сна", "сновид", "запис", "dream")


@dataclass(slots=True)
class ChatResult:
    text: str
    tool_calls_made: list[str]


async def handle_chat(
    message_text: str,
    facade: AssistantFacade,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    chat_id: int | None = None,
) -> str:
    return (
        await handle_chat_with_metadata(
            message_text,
            facade,
            session_factory=session_factory,
            chat_id=chat_id,
        )
    ).text


async def handle_chat_with_metadata(
    message_text: str,
    facade: AssistantFacade,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    chat_id: int | None = None,
) -> ChatResult:
    """Process a user text message through the bounded tool-use loop.

    When session_factory and chat_id are provided, conversation history is
    loaded from and saved to the database so context survives restarts.
    Returns a plain text response suitable for sending back to the user.
    Never raises — errors are returned as user-facing strings.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        LOGGER.error("ANTHROPIC_API_KEY is not set — chat unavailable")
        return ChatResult(
            text="The assistant is not available: API key not configured.",
            tool_calls_made=[],
        )

    model = os.environ.get("ASSISTANT_MODEL", _DEFAULT_MODEL)
    client = AsyncAnthropic(api_key=api_key)
    settings = get_settings()

    history: list[dict[str, Any]] = []
    if session_factory is not None and chat_id is not None:
        try:
            history = await load_history(session_factory, chat_id)
        except Exception:
            LOGGER.warning("Failed to load session history for chat_id=%s", chat_id, exc_info=True)

    feedback_rows: list[dict] = []
    if session_factory is not None:
        try:
            async with session_factory() as fb_session:
                feedback_rows = await FeedbackService().get_recent_for_context(fb_session)
        except Exception:
            LOGGER.warning("Failed to load feedback context", exc_info=True)

    today = _application_today()
    date_header = f"Сегодня: {today.strftime('%d.%m.%y')} ({today.isoformat()}).\n\n"
    system_prompt = date_header + (
        build_system_prompt(feedback_rows) if feedback_rows else SYSTEM_PROMPT
    )
    messages: list[dict[str, Any]] = history + [{"role": "user", "content": message_text}]
    round_counter = 0
    last_text = ""
    tool_calls_made: list[str] = []
    _create_dream_called = False  # allow only one create_dream per user turn

    while True:
        try:
            response = await client.messages.create(
                model=model,
                system=system_prompt,
                max_tokens=1024,
                messages=messages,
                tools=build_tools(
                    motif_induction_enabled=settings.MOTIF_INDUCTION_ENABLED,
                    research_enabled=settings.RESEARCH_AUGMENTATION_ENABLED,
                ),
            )
        except Exception:
            LOGGER.exception("Claude chat request failed")
            return ChatResult(
                text="Something went wrong while contacting the assistant. Please try again.",
                tool_calls_made=tool_calls_made,
            )

        usage = response.usage
        LOGGER.info(
            "anthropic_usage chat_id=%s model=%s round=%s "
            "input_tokens=%s output_tokens=%s cache_read=%s cache_write=%s",
            chat_id,
            model,
            round_counter,
            usage.input_tokens,
            usage.output_tokens,
            getattr(usage, "cache_read_input_tokens", 0),
            getattr(usage, "cache_creation_input_tokens", 0),
        )

        current_text = _extract_text(response)
        if current_text:
            last_text = current_text

        if response.stop_reason != "tool_use":
            break

        tool_blocks = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
        tool_pairs: list[tuple[Any, str]] = []
        for block in tool_blocks:
            if block.name == "create_dream":
                if _create_dream_called:
                    LOGGER.warning(
                        "Blocked duplicate create_dream call in same turn chat_id=%s", chat_id
                    )
                    tool_pairs.append(
                        (
                            block,
                            "ERROR: create_dream called more than once in a single user turn. "
                            "Only one dream may be created per user message. "
                            "Do not call create_dream again for this request.",
                        )
                    )
                    continue
                _create_dream_called = True
            tool_calls_made.append(block.name)
            result = await execute_tool(
                block.name,
                block.input,
                facade,
                chat_id=chat_id,
                request_text=message_text,
            )
            tool_pairs.append((block, result))
            direct_response = _direct_full_dream_text_response(
                block.name,
                result,
                request_text=message_text,
            )
            if direct_response:
                LOGGER.info(
                    "direct_full_dream_text_response chat_id=%s tool=%s chars=%s",
                    chat_id,
                    block.name,
                    len(direct_response),
                )
                await _save_turn_history(
                    session_factory,
                    chat_id,
                    history,
                    message_text,
                    direct_response,
                )
                return ChatResult(text=direct_response, tool_calls_made=tool_calls_made)

        messages.append({"role": "assistant", "content": response.content})
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    }
                    for block, result in tool_pairs
                ],
            }
        )

        round_counter += 1
        if round_counter >= _MAX_TOOL_ROUNDS:
            LOGGER.warning("Tool-use loop guard fired after %s rounds", round_counter)
            break

    if not last_text:
        return ChatResult(text="No response from the assistant.", tool_calls_made=tool_calls_made)

    await _save_turn_history(session_factory, chat_id, history, message_text, last_text)

    return ChatResult(text=last_text, tool_calls_made=tool_calls_made)


def _extract_text(response: Any) -> str:
    parts: list[str] = []
    for block in response.content:
        if getattr(block, "type", None) == "text" and getattr(block, "text", ""):
            parts.append(block.text)
    return "".join(parts).strip()


async def _save_turn_history(
    session_factory: async_sessionmaker[AsyncSession] | None,
    chat_id: int | None,
    history: list[dict[str, Any]],
    message_text: str,
    assistant_text: str,
) -> None:
    if session_factory is None or chat_id is None:
        return

    new_history = history + [
        {"role": "user", "content": message_text},
        {"role": "assistant", "content": assistant_text},
    ]
    try:
        await save_history(session_factory, chat_id, new_history)
    except Exception:
        LOGGER.warning("Failed to save session history for chat_id=%s", chat_id, exc_info=True)


def _direct_full_dream_text_response(
    tool_name: str,
    tool_result: str,
    *,
    request_text: str,
) -> str | None:
    if tool_name not in _FULL_DREAM_TEXT_TOOLS:
        return None
    if not _is_full_dream_text_request(request_text):
        return None
    return _format_full_dream_text_reply(tool_result)


def _is_full_dream_text_request(request_text: str) -> bool:
    text = request_text.casefold()
    if any(marker in text for marker in _EXPLICIT_FULL_TEXT_MARKERS):
        return True
    has_full_text_marker = any(marker in text for marker in _COMPLETENESS_MARKERS)
    has_dream_marker = any(marker in text for marker in _DREAM_MARKERS)
    return has_full_text_marker and has_dream_marker


def _format_full_dream_text_reply(tool_result: str) -> str | None:
    text_match = re.search(r"(?m)^Text: ?", tool_result)
    if not text_match:
        return None

    dream_text, notes = _split_dream_text_and_notes(tool_result[text_match.end() :])
    dream_text = dream_text.rstrip()
    if not dream_text.strip():
        return None

    title = _extract_tool_field(tool_result, "Title")
    date_value = _format_tool_date(_extract_tool_field(tool_result, "Date"))

    header_parts = [part for part in (date_value, title) if part and part != "unknown"]
    response_parts: list[str] = []
    if header_parts:
        response_parts.append(", ".join(header_parts))
    response_parts.append(dream_text)
    if notes:
        response_parts.append(f"Заметки:\n{notes}")
    return "\n\n".join(response_parts)


def _split_dream_text_and_notes(text_with_optional_notes: str) -> tuple[str, str]:
    if "\nNotes:\n" not in text_with_optional_notes:
        return text_with_optional_notes, ""

    dream_text, notes_text = text_with_optional_notes.rsplit("\nNotes:\n", 1)
    note_lines = [line.strip() for line in notes_text.splitlines() if line.strip()]
    if not note_lines or any(not line.startswith("- ") for line in note_lines):
        return text_with_optional_notes, ""

    notes = "\n".join(line[2:].strip() for line in note_lines)
    return dream_text, notes


def _extract_tool_field(tool_result: str, field_name: str) -> str:
    match = re.search(rf"(?m)^{re.escape(field_name)}: (.*)$", tool_result)
    if not match:
        return ""
    value = match.group(1).strip()
    return "" if value in {"", "None"} else value


def _format_tool_date(date_value: str) -> str:
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", date_value)
    if not match:
        return date_value
    year, month, day = match.groups()
    return f"{day}.{month}.{year[2:]}"
