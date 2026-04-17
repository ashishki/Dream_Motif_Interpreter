"""Bounded conversational tool-use loop for the dream archive assistant."""
from __future__ import annotations

import logging
import os
from typing import Any

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.assistant.facade import AssistantFacade
from app.assistant.prompts import SYSTEM_PROMPT
from app.assistant.session import load_history, save_history
from app.assistant.tools import build_tools, execute_tool
from app.shared.config import get_settings

LOGGER = logging.getLogger(__name__)

_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOOL_ROUNDS = 5


async def handle_chat(
    message_text: str,
    facade: AssistantFacade,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    chat_id: int | None = None,
) -> str:
    """Process a user text message through the bounded tool-use loop.

    When session_factory and chat_id are provided, conversation history is
    loaded from and saved to the database so context survives restarts.
    Returns a plain text response suitable for sending back to the user.
    Never raises — errors are returned as user-facing strings.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        LOGGER.error("ANTHROPIC_API_KEY is not set — chat unavailable")
        return "The assistant is not available: API key not configured."

    model = os.environ.get("ASSISTANT_MODEL", _DEFAULT_MODEL)
    client = AsyncAnthropic(api_key=api_key)
    settings = get_settings()

    history: list[dict[str, Any]] = []
    if session_factory is not None and chat_id is not None:
        try:
            history = await load_history(session_factory, chat_id)
        except Exception:
            LOGGER.warning("Failed to load session history for chat_id=%s", chat_id, exc_info=True)

    messages: list[dict[str, Any]] = history + [{"role": "user", "content": message_text}]
    round_counter = 0
    last_text = ""

    while True:
        try:
            response = await client.messages.create(
                model=model,
                system=SYSTEM_PROMPT,
                max_tokens=1024,
                messages=messages,
                tools=build_tools(
                    motif_induction_enabled=settings.MOTIF_INDUCTION_ENABLED,
                    research_enabled=settings.RESEARCH_AUGMENTATION_ENABLED,
                ),
            )
        except Exception:
            LOGGER.exception("Claude chat request failed")
            return "Something went wrong while contacting the assistant. Please try again."

        current_text = _extract_text(response)
        if current_text:
            last_text = current_text

        if response.stop_reason != "tool_use":
            break

        tool_blocks = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
        tool_results: list[str] = []
        for block in tool_blocks:
            result = await execute_tool(block.name, block.input, facade)
            tool_results.append(result)

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
                    for block, result in zip(tool_blocks, tool_results, strict=True)
                ],
            }
        )

        round_counter += 1
        if round_counter >= _MAX_TOOL_ROUNDS:
            LOGGER.warning("Tool-use loop guard fired after %s rounds", round_counter)
            break

    if not last_text:
        return "No response from the assistant."

    if session_factory is not None and chat_id is not None:
        new_history = history + [
            {"role": "user", "content": message_text},
            {"role": "assistant", "content": last_text},
        ]
        try:
            await save_history(session_factory, chat_id, new_history)
        except Exception:
            LOGGER.warning("Failed to save session history for chat_id=%s", chat_id, exc_info=True)

    return last_text


def _extract_text(response: Any) -> str:
    parts: list[str] = []
    for block in response.content:
        if getattr(block, "type", None) == "text" and getattr(block, "text", ""):
            parts.append(block.text)
    return "".join(parts).strip()
