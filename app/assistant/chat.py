"""Bounded conversational tool-use loop for the dream archive assistant."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import re
import uuid
from typing import Any

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.assistant.facade import AssistantFacade
from app.assistant.facade import _application_today
from app.assistant.prompts import SYSTEM_PROMPT, build_system_prompt
from app.assistant.session import (
    load_history,
    load_recent_dream_set,
    save_history,
    save_recent_dream_set,
)
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
_DREAM_SET_PATTERN_SYSTEM_PROMPT = (
    "You analyse patterns across a selected set of dream texts. "
    "Answer in Russian. Use only the supplied dream texts. "
    "Do not say you only see search results: the full texts are supplied. "
    "Give concrete shared patterns and cite which dreams support each pattern by date/title. "
    "Keep hypotheses cautious and distinguish observation from interpretation. "
    "Use plain text without markdown."
)


@dataclass(slots=True)
class ChatResult:
    text: str
    tool_calls_made: list[str]


@dataclass(slots=True)
class _DirectChatResult:
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
    history: list[dict[str, Any]] = []
    if session_factory is not None and chat_id is not None:
        try:
            history = await load_history(session_factory, chat_id)
        except Exception:
            LOGGER.warning("Failed to load session history for chat_id=%s", chat_id, exc_info=True)

    try:
        direct_result = await _try_direct_full_text_request(message_text, facade)
    except Exception:
        LOGGER.warning("Direct full-text lookup failed; falling back to LLM", exc_info=True)
        direct_result = None
    if direct_result is not None:
        LOGGER.info(
            "pre_llm_full_dream_text_response chat_id=%s chars=%s",
            chat_id,
            len(direct_result.text),
        )
        await _save_turn_history(
            session_factory,
            chat_id,
            history,
            message_text,
            direct_result.text,
        )
        return ChatResult(
            text=direct_result.text,
            tool_calls_made=direct_result.tool_calls_made,
        )

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

    try:
        pattern_result = await _try_direct_dream_set_pattern_analysis(
            message_text,
            facade,
            history=history,
            chat_id=chat_id,
            client=client,
            model=model,
        )
    except Exception:
        LOGGER.warning(
            "Direct dream-set pattern analysis failed; falling back to LLM", exc_info=True
        )
        pattern_result = None
    if pattern_result is not None:
        await _save_turn_history(
            session_factory,
            chat_id,
            history,
            message_text,
            pattern_result.text,
        )
        return ChatResult(
            text=pattern_result.text,
            tool_calls_made=pattern_result.tool_calls_made,
        )

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
            _remember_search_result_set(chat_id, block.name, block.input, result)
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


def _remember_search_result_set(
    chat_id: int | None,
    tool_name: str,
    tool_input: Any,
    tool_result: str,
) -> None:
    if chat_id is None or tool_name not in {"search_dreams", "search_dreams_exact"}:
        return

    dream_ids = re.findall(
        r"(?m)^\s*result_id:\s*([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\s*$",
        tool_result,
    )
    if not dream_ids:
        return
    query = ""
    if isinstance(tool_input, dict):
        query = str(tool_input.get("query", "")).strip()
    save_recent_dream_set(chat_id, query=query, dream_ids=dream_ids)


async def _try_direct_dream_set_pattern_analysis(
    message_text: str,
    facade: AssistantFacade,
    *,
    history: list[dict[str, Any]],
    chat_id: int | None,
    client: AsyncAnthropic,
    model: str,
) -> ChatResult | None:
    if not _is_dream_set_pattern_request(message_text):
        return None

    query = _extract_pattern_query(message_text) or _extract_pattern_query_from_history(history)
    dream_ids: list[uuid.UUID] = []
    tool_calls = ["analyze_dream_set_patterns"]

    recent = load_recent_dream_set(chat_id) if chat_id is not None else None
    if (
        recent is not None
        and recent.dream_ids
        and _should_use_recent_dream_set(message_text, query, recent.query)
    ):
        query = query or recent.query
        dream_ids = _coerce_uuid_list(recent.dream_ids)

    if not dream_ids:
        if not query:
            return ChatResult(
                text=(
                    "Я не вижу в текущем контексте, какую подборку снов анализировать. "
                    "Напиши тему одним словом или повтори подборку, и я сразу разберу все найденные сны."
                ),
                tool_calls_made=tool_calls,
            )
        search_result = await facade.search_dreams(query)
        tool_calls.append("search_dreams")
        if search_result.insufficient_reason is not None or not search_result.items:
            return ChatResult(
                text=f"По теме «{query}» не нашёл достаточно снов для анализа паттернов.",
                tool_calls_made=tool_calls,
            )
        dream_ids = []
        seen: set[uuid.UUID] = set()
        for item in search_result.items:
            if item.dream_id in seen:
                continue
            seen.add(item.dream_id)
            dream_ids.append(item.dream_id)
        if chat_id is not None:
            save_recent_dream_set(
                chat_id,
                query=query,
                dream_ids=[str(dream_id) for dream_id in dream_ids],
            )

    details = []
    for dream_id in dream_ids[:20]:
        detail = await facade.get_dream(dream_id)
        if detail is not None:
            details.append(detail)
    tool_calls.append("get_dream")

    if not details:
        return ChatResult(
            text="Нашёл подборку, но не смог загрузить полные тексты этих снов.",
            tool_calls_made=tool_calls,
        )

    response = await client.messages.create(
        model=model,
        system=_DREAM_SET_PATTERN_SYSTEM_PROMPT,
        max_tokens=2200,
        messages=[
            {
                "role": "user",
                "content": _build_dream_set_pattern_prompt(
                    message_text,
                    query=query or "последняя подборка",
                    details=details,
                ),
            }
        ],
    )
    text = _extract_text(response)
    if not text:
        return ChatResult(
            text="Не получилось сформировать анализ паттернов по этой подборке.",
            tool_calls_made=tool_calls,
        )
    LOGGER.info(
        "direct_dream_set_pattern_analysis chat_id=%s query=%r dreams=%s chars=%s",
        chat_id,
        query,
        len(details),
        len(text),
    )
    return ChatResult(text=text, tool_calls_made=tool_calls)


def _is_dream_set_pattern_request(message_text: str) -> bool:
    text = message_text.casefold()
    has_pattern = any(
        marker in text
        for marker in ("паттерн", "закономер", "общие мотив", "общий мотив", "повторя")
    )
    has_set_context = any(
        marker in text
        for marker in (
            "подбор",
            "спис",
            "этих с",
            "эти с",
            "в снах",
            "снов",
            "по теме",
            "фигурирует",
            "связанных",
        )
    )
    return has_pattern and has_set_context


def _extract_pattern_query(message_text: str) -> str | None:
    text = message_text.strip()
    patterns = (
        r"(?is)(?:по теме|на тему|теме)\s+(?P<query>[^.?!,\n]+)",
        r"(?is)(?:фигурирует|связанных с|связанные с|про|о|об)\s+(?P<query>[^.?!,\n]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _clean_pattern_query(match.group("query"))
    if re.search(r"(?i)\bработ[ауыое]?\b", text):
        return "работа"
    return None


def _extract_pattern_query_from_history(history: list[dict[str, Any]]) -> str | None:
    for item in reversed(history[-8:]):
        if item.get("role") != "user":
            continue
        content = item.get("content")
        if isinstance(content, str):
            query = _extract_pattern_query(content)
            if query:
                return query
    return None


def _clean_pattern_query(value: str) -> str | None:
    query = value.strip().strip("\"'«»“”")
    query = re.sub(
        r"(?is)\b(?:найди|общие|паттерны|паттерн|мотивы|мотив|сны|снов|подборк[аиу]?|которых|где|есть)\b",
        " ",
        query,
    )
    query = re.sub(r"\s+", " ", query).strip(" \t\r\n:;,.!?–—-")
    return query or None


def _should_use_recent_dream_set(message_text: str, query: str | None, recent_query: str) -> bool:
    text = message_text.casefold()
    if any(marker in text for marker in ("подбор", "спис", "этих", "эти ", "последн")):
        return True
    if not query:
        return True
    return (
        query.casefold() in recent_query.casefold() or recent_query.casefold() in query.casefold()
    )


def _coerce_uuid_list(values: list[str]) -> list[uuid.UUID]:
    dream_ids: list[uuid.UUID] = []
    for value in values:
        try:
            dream_ids.append(uuid.UUID(str(value)))
        except ValueError:
            continue
    return dream_ids


def _build_dream_set_pattern_prompt(
    user_request: str,
    *,
    query: str,
    details: list[Any],
) -> str:
    sections = [
        f"Запрос пользователя: {user_request}",
        f"Тема/подборка: {query}",
        f"Количество снов: {len(details)}",
        "",
        "Проанализируй все тексты ниже и найди общие паттерны, в которых проявляется тема.",
        "Для каждого паттерна укажи 2-5 сна, на которых он основан.",
        "Не предлагай варианты дальнейшей работы, сразу делай анализ.",
        "",
    ]
    for index, detail in enumerate(details, start=1):
        date_value = _format_tool_date(str(getattr(detail, "date", "") or "unknown"))
        title = str(getattr(detail, "title", "") or "без названия")
        raw_text = str(getattr(detail, "raw_text", "") or "")
        sections.extend(
            [
                f"Сон {index}: {date_value}, {title}",
                raw_text,
                "",
            ]
        )
    return "\n".join(sections)


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


async def _try_direct_full_text_request(
    message_text: str,
    facade: AssistantFacade,
) -> _DirectChatResult | None:
    query = _extract_full_text_query(message_text)
    if not query:
        return None

    title_matches = await facade.search_dreams_by_title(query, limit=10)
    if len(title_matches) == 1:
        detail = await facade.get_dream(title_matches[0].dream_id)
        if detail is None:
            return _DirectChatResult(
                text=(
                    "Нашёл сон по названию, но не смог загрузить полный текст из архива. "
                    "Попробуй уточнить дату или название."
                ),
                tool_calls_made=["search_dreams_by_title", "get_dream"],
            )
        return _DirectChatResult(
            text=_format_full_dream_detail_reply(detail),
            tool_calls_made=["search_dreams_by_title", "get_dream"],
        )
    if len(title_matches) > 1:
        return _DirectChatResult(
            text=_format_ambiguous_full_text_matches(query, title_matches),
            tool_calls_made=["search_dreams_by_title"],
        )

    search_result = await facade.search_dreams(query)
    if search_result.insufficient_reason is not None or not search_result.items:
        return _DirectChatResult(
            text=(
                f"Не нашёл в архиве однозначный сон по запросу «{query}». "
                "Укажи, пожалуйста, точное название или дату."
            ),
            tool_calls_made=["search_dreams_by_title", "search_dreams"],
        )

    unique_ids = []
    seen_ids = set()
    for item in search_result.items:
        if item.dream_id in seen_ids:
            continue
        seen_ids.add(item.dream_id)
        unique_ids.append(item.dream_id)

    if len(unique_ids) == 1:
        detail = await facade.get_dream(unique_ids[0])
        if detail is None:
            return _DirectChatResult(
                text=(
                    "Нашёл похожий сон, но не смог загрузить полный текст из архива. "
                    "Попробуй уточнить дату или название."
                ),
                tool_calls_made=["search_dreams_by_title", "search_dreams", "get_dream"],
            )
        return _DirectChatResult(
            text=_format_full_dream_detail_reply(detail),
            tool_calls_made=["search_dreams_by_title", "search_dreams", "get_dream"],
        )

    return _DirectChatResult(
        text=_format_ambiguous_full_text_search_results(query, search_result.items),
        tool_calls_made=["search_dreams_by_title", "search_dreams"],
    )


def _extract_full_text_query(message_text: str) -> str | None:
    if not _is_full_dream_text_request(message_text):
        return None

    patterns = (
        r"(?is)^\s*(?:приведи|пришли|покажи|дай|напиши|выведи|отправь|скинь)?"
        r"\s*(?:мне|пожалуйста)?\s*(?:полный|весь)\s+текст"
        r"\s*(?:сна|сон|записи)?\s*(?:про|о|по|под названием|с названием)?"
        r"\s*[:\"'«»—–-]?\s*(?P<query>.+?)\s*$",
        r"(?is)^\s*(?:приведи|пришли|покажи|дай|напиши|выведи|отправь|скинь)?"
        r"\s*(?:мне|пожалуйста)?\s*полную\s+запись"
        r"\s*(?:сна|сон)?\s*(?:про|о|по|под названием|с названием)?"
        r"\s*[:\"'«»—–-]?\s*(?P<query>.+?)\s*$",
        r"(?is)^\s*(?:приведи|пришли|покажи|дай|напиши|выведи|отправь|скинь)?"
        r"\s*(?:мне|пожалуйста)?\s*(?:сон|запись)?\s*(?:целиком|полностью|без сокращений)"
        r"\s*(?:про|о|по|под названием|с названием)?\s*[:\"'«»—–-]?\s*(?P<query>.+?)\s*$",
        r"(?is)^\s*(?:show|send|give|print)?\s*(?:me)?\s*(?:the)?\s*"
        r"(?:full|complete|entire|whole|verbatim)\s+(?:text\s+)?(?:of\s+)?(?:the\s+)?"
        r"(?:dream\s+)?(?P<query>.+?)\s*$",
    )
    for pattern in patterns:
        match = re.match(pattern, message_text)
        if match:
            return _clean_full_text_query(match.group("query"))
    return None


def _clean_full_text_query(raw_query: str) -> str | None:
    query = raw_query.strip().strip("\"'«»“”")
    if query.casefold() in {"сна", "сон", "записи", "запись", "dream"}:
        return None
    query = re.sub(r"(?i)^(?:сна|сон|записи|запись|dream)\s+", "", query).strip()
    query = re.sub(r"(?i)^(?:про|о|по|под названием|с названием)\s+", "", query).strip()
    return query or None


def _is_full_dream_text_request(request_text: str) -> bool:
    text = request_text.casefold()
    if any(marker in text for marker in _EXPLICIT_FULL_TEXT_MARKERS):
        return True
    has_full_text_marker = any(marker in text for marker in _COMPLETENESS_MARKERS)
    has_dream_marker = any(marker in text for marker in _DREAM_MARKERS)
    return has_full_text_marker and has_dream_marker


def _format_full_dream_detail_reply(detail: Any) -> str:
    title = str(getattr(detail, "title", "") or "").strip()
    date_value = _format_tool_date(str(getattr(detail, "date", "") or "").strip())
    dream_text = str(getattr(detail, "raw_text", "") or "").rstrip()
    notes = [str(note).strip() for note in getattr(detail, "notes", []) if str(note).strip()]

    header_parts = [part for part in (date_value, title) if part and part != "unknown"]
    response_parts: list[str] = []
    if header_parts:
        response_parts.append(", ".join(header_parts))
    response_parts.append(dream_text or "В архиве у этого сна пустой текст.")
    if notes:
        response_parts.append("Заметки:\n" + "\n".join(notes))
    return "\n\n".join(response_parts)


def _format_ambiguous_full_text_matches(query: str, matches: list[Any]) -> str:
    lines = [f"Нашёл несколько снов по запросу «{query}». Уточни, какой текст прислать:"]
    for index, item in enumerate(matches[:10], start=1):
        date_value = _format_tool_date(str(getattr(item, "date", "") or "").strip())
        title = str(getattr(item, "title", "") or "без названия").strip()
        label = ", ".join(part for part in (date_value, title) if part and part != "unknown")
        lines.append(f"{index}. {label or title}")
    return "\n".join(lines)


def _format_ambiguous_full_text_search_results(query: str, items: list[Any]) -> str:
    lines = [f"Нашёл несколько похожих снов по запросу «{query}». Уточни, какой текст прислать:"]
    seen_ids = set()
    option_index = 1
    for item in items:
        if item.dream_id in seen_ids:
            continue
        seen_ids.add(item.dream_id)
        date_value = _format_tool_date(
            getattr(item.date, "isoformat", lambda: str(item.date or ""))()
        )
        title = str(getattr(item, "title", "") or "без названия").strip()
        label = ", ".join(part for part in (date_value, title) if part and part != "unknown")
        lines.append(f"{option_index}. {label or title}")
        option_index += 1
        if option_index > 10:
            break
    return "\n".join(lines)


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
