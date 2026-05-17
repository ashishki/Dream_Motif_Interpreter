"""Unit tests for the bounded chat/tool-use loop in app.assistant.chat."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.assistant import tools as tools_module
from app.assistant.chat import handle_chat, handle_chat_with_metadata, _extract_text
from app.assistant.facade import (
    AssistantFacade,
    DreamDetail,
    DreamThemeItem,
    DreamSummary,
    DreamTitleSearchResult,
    MotifInductionItem,
    SearchResult,
    SearchResultItem,
)
from app.assistant.prompts import SYSTEM_PROMPT
from app.assistant.session import (
    clear_pending_interpretation_request,
    load_pending_interpretation_request,
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
    resp = _make_response(
        "tool_use", [_tool_use_block("search_dreams", "t1", {}), _text_block("hi")]
    )
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
                    title="Flying dream",
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
    final_response = _make_response(
        "end_turn", [_text_block("Found a flying dream from 2024-03-01.")]
    )

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        with patch("app.assistant.chat.AsyncAnthropic") as mock_client_cls:
            client = AsyncMock()
            client.messages.create = AsyncMock(side_effect=[tool_response, final_response])
            mock_client_cls.return_value = client

            result = await handle_chat("find flying dreams", facade)

    assert "flying" in result.lower() or "2024" in result
    facade.search_dreams.assert_awaited_once_with("flying")


@pytest.mark.asyncio
async def test_handle_chat_returns_full_dream_text_directly_without_final_llm() -> None:
    dream_id = uuid.uuid4()
    long_text = "Начало сна.\n" + ("длинный фрагмент " * 220) + "\nФинальная строка сна."
    tool_result = (
        f"Dream {dream_id}\n"
        "Date: 2026-05-15\n"
        "Title: Длинная ночь\n"
        f"Words: {len(long_text.split())}\n"
        "Themes: none\n"
        f"Text: {long_text}"
    )
    facade = _make_facade()
    tool_response = _make_response(
        "tool_use",
        [_tool_use_block("get_dream", "t-full", {"dream_id": str(dream_id)})],
    )

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        with patch("app.assistant.chat.AsyncAnthropic") as mock_client_cls:
            with patch("app.assistant.chat.execute_tool", new=AsyncMock(return_value=tool_result)):
                client = AsyncMock()
                client.messages.create = AsyncMock(return_value=tool_response)
                mock_client_cls.return_value = client

                result = await handle_chat("пришли полный текст сна", facade)

    assert result.startswith("15.05.26, Длинная ночь\n\nНачало сна.")
    assert long_text in result
    assert "Финальная строка сна." in result
    assert client.messages.create.await_count == 1


@pytest.mark.asyncio
async def test_handle_chat_pre_llm_full_text_lookup_ignores_stale_history() -> None:
    dream_id = uuid.uuid4()
    long_text = "Start of the dream. " + ("middle fragment " * 180) + "Final archive line."
    facade = AsyncMock(spec=AssistantFacade)
    facade.search_dreams_by_title.return_value = [
        DreamTitleSearchResult(
            dream_id=dream_id,
            date=None,
            title="4.08.25 dreamwork, three women",
            raw_text_preview=long_text[:120],
        )
    ]
    facade.get_dream.return_value = DreamDetail(
        id=dream_id,
        date=None,
        title="4.08.25 dreamwork, three women",
        raw_text=long_text,
        word_count=len(long_text.split()),
        source_doc_id="doc-1",
        created_at="2026-05-17T00:00:00+00:00",
        segmentation_confidence="high",
        themes=[],
        notes=[],
    )

    stale_history = [
        {"role": "user", "content": "Приведи полный текст сна dreamwork, three women"},
        {"role": "assistant", "content": "В архиве сохранён только неполный текст."},
    ]

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}):
        with patch("app.assistant.chat.AsyncAnthropic") as mock_client_cls:
            with patch("app.assistant.chat.load_history", new=AsyncMock(return_value=stale_history)):
                with patch("app.assistant.chat.save_history", new=AsyncMock()) as mock_save:
                    result = await handle_chat_with_metadata(
                        "Приведи полный текст сна dreamwork, three women",
                        facade,
                        session_factory=MagicMock(),
                        chat_id=123,
                    )

    assert result.text.startswith("4.08.25 dreamwork, three women\n\nStart of the dream.")
    assert "Final archive line." in result.text
    assert result.tool_calls_made == ["search_dreams_by_title", "get_dream"]
    facade.search_dreams_by_title.assert_awaited_once_with("dreamwork, three women", limit=10)
    facade.get_dream.assert_awaited_once_with(dream_id)
    mock_client_cls.assert_not_called()
    mock_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_chat_returns_full_title_match_text_directly() -> None:
    dream_id = uuid.uuid4()
    tool_result = (
        "Single title match found for 'рыба'. Full dream:\n"
        f"Dream {dream_id}\n"
        "Date: 2026-05-16\n"
        "Title: Рыба\n"
        "Words: 7\n"
        "Themes: none\n"
        "Text: В этом сне была рыба.\nNotes:\n- заметка к сну"
    )
    facade = _make_facade()
    tool_response = _make_response(
        "tool_use",
        [_tool_use_block("search_dreams_by_title", "t-title", {"query": "рыба"})],
    )

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        with patch("app.assistant.chat.AsyncAnthropic") as mock_client_cls:
            with patch("app.assistant.chat.execute_tool", new=AsyncMock(return_value=tool_result)):
                client = AsyncMock()
                client.messages.create = AsyncMock(return_value=tool_response)
                mock_client_cls.return_value = client

                result = await handle_chat("покажи полный текст сна", facade)

    assert result == "16.05.26, Рыба\n\nВ этом сне была рыба.\n\nЗаметки:\nзаметка к сну"
    assert client.messages.create.await_count == 1


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


@pytest.mark.asyncio
async def test_handle_chat_uses_build_tools_not_constant() -> None:
    facade = _make_facade()
    final_response = _make_response("end_turn", [_text_block("Here is your answer.")])
    sentinel_tools = [{"name": "sentinel_tool"}]
    settings = SimpleNamespace(
        MOTIF_INDUCTION_ENABLED=True,
        RESEARCH_AUGMENTATION_ENABLED=True,
    )

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        with patch("app.assistant.chat.AsyncAnthropic") as mock_client_cls:
            with patch(
                "app.assistant.chat.build_tools", return_value=sentinel_tools
            ) as mock_build_tools:
                with patch("app.assistant.chat.get_settings", return_value=settings):
                    client = AsyncMock()
                    client.messages.create = AsyncMock(return_value=final_response)
                    mock_client_cls.return_value = client

                    await handle_chat("what are my recent dreams?", facade)

    mock_build_tools.assert_called_once_with(
        motif_induction_enabled=True,
        research_enabled=True,
    )
    assert client.messages.create.await_args.kwargs["tools"] is sentinel_tools


# ---------------------------------------------------------------------------
# System prompt — motif framing rules
# ---------------------------------------------------------------------------


def test_system_prompt_forbids_word_interpretation_for_motifs() -> None:
    """The system prompt must instruct the assistant not to use 'interpretation'
    for inducted motifs. The word 'interpretation' may appear only paired with
    a negation or prohibition instruction."""
    prompt_lower = SYSTEM_PROMPT.lower()
    assert "interpretation" in prompt_lower
    idx = prompt_lower.index("interpretation")
    context = prompt_lower[max(0, idx - 80) : idx + 80]
    negation_words = {"never", "not", "instead", "avoid"}
    assert any(w in context for w in negation_words), (
        f"Expected a negation near 'interpretation' in system prompt, got: {context!r}"
    )


def test_system_prompt_contains_draft_motif_framing_rule() -> None:
    """The system prompt must instruct that draft motifs are unconfirmed suggestions."""
    assert "draft" in SYSTEM_PROMPT.lower()
    assert "unconfirmed" in SYSTEM_PROMPT.lower() or "suggestion" in SYSTEM_PROMPT.lower()


def test_system_prompt_contains_abstraction_framing_language() -> None:
    """The system prompt must use 'abstraction' or 'suggestion' as the correct
    framing vocabulary for inducted motifs."""
    prompt_lower = SYSTEM_PROMPT.lower()
    assert "abstraction" in prompt_lower or "suggestion" in prompt_lower


def test_system_prompt_contains_confidence_level_framing() -> None:
    """The system prompt must address how to frame each confidence level."""
    prompt_lower = SYSTEM_PROMPT.lower()
    assert "high confidence" in prompt_lower
    assert "moderate" in prompt_lower
    assert "low confidence" in prompt_lower or "tentatively" in prompt_lower


def test_system_prompt_is_importable_from_prompts_module() -> None:
    assert "abstraction" in SYSTEM_PROMPT.lower()


def test_tools_module_does_not_expose_tools_constant() -> None:
    assert hasattr(tools_module, "TOOLS") is False


def test_system_prompt_instructs_not_to_present_draft_as_confirmed() -> None:
    """The system prompt must instruct the assistant not to present draft motifs
    as conclusions or confirmed findings."""
    prompt_lower = SYSTEM_PROMPT.lower()
    assert "not as conclusions" in prompt_lower or "not a curated finding" in prompt_lower


def test_system_prompt_requires_create_dream_for_explicit_save_requests() -> None:
    prompt_lower = SYSTEM_PROMPT.lower()
    assert "always call create_dream" in prompt_lower
    assert "добавь в архив" in prompt_lower
    assert "занеси в архив" in prompt_lower


def test_system_prompt_requires_honest_google_doc_write_confirmation() -> None:
    assert "For successful writes, say exactly: «Сон сохранён и добавлен в документ»." in (
        SYSTEM_PROMPT
    )
    assert "Do not include a Google Doc name, URL, or document ID" in SYSTEM_PROMPT
    assert "Only say the dream was added to the document when the tool result confirms" in (
        SYSTEM_PROMPT
    )


def test_system_prompt_contains_terminology_rules_for_google_docs_sources() -> None:
    prompt_lower = SYSTEM_PROMPT.lower()
    assert "## terminology rules".lower() in prompt_lower
    assert "google docs" in prompt_lower
    assert "not the internal database" in prompt_lower
    assert (
        "manage_archive_source and trigger_sync are operations on google docs sources"
        in prompt_lower
    )


def test_system_prompt_requires_search_answers_to_cite_evidence_text() -> None:
    prompt_lower = SYSTEM_PROMPT.lower()
    assert "evidence_text" in prompt_lower
    assert "final answers must cite only evidence_text" in prompt_lower
    assert "for get_dream results, the text field is the archive-backed full dream text" in (
        prompt_lower
    )


def test_system_prompt_routes_concrete_image_queries_to_augmented_search() -> None:
    prompt_lower = SYSTEM_PROMPT.lower()
    assert "сон с рыбой" in prompt_lower
    assert "augments semantic retrieval with exact text recall" in prompt_lower


# ---------------------------------------------------------------------------
# build_tools — conditional get_dream_motifs registration
# ---------------------------------------------------------------------------


def test_build_tools_excludes_get_dream_motifs_when_flag_is_false() -> None:
    """When MOTIF_INDUCTION_ENABLED=False, get_dream_motifs must not appear in the catalog."""
    from app.assistant.tools import build_tools

    tools = build_tools(motif_induction_enabled=False)
    tool_names = [t["name"] for t in tools]
    assert "get_dream_motifs" not in tool_names


def test_build_tools_includes_get_dream_motifs_when_flag_is_true() -> None:
    """When MOTIF_INDUCTION_ENABLED=True, get_dream_motifs must appear in the catalog."""
    from app.assistant.tools import build_tools

    tools = build_tools(motif_induction_enabled=True)
    tool_names = [t["name"] for t in tools]
    assert "get_dream_motifs" in tool_names


def test_build_tools_base_tools_always_present() -> None:
    """Core tools must always be present regardless of the motif flag."""
    from app.assistant.tools import build_tools

    for flag in (False, True):
        tools = build_tools(motif_induction_enabled=flag)
        tool_names = [t["name"] for t in tools]
        for name in (
            "search_dreams",
            "create_dream",
            "get_dream",
            "list_recent_dreams",
            "get_patterns",
            "get_theme_history",
            "trigger_sync",
            "manage_archive_source",
        ):
            assert name in tool_names, f"{name} missing when motif_induction_enabled={flag}"


def test_build_tools_excludes_research_motif_parallels_when_flag_is_false() -> None:
    from app.assistant.tools import build_tools

    tools = build_tools(motif_induction_enabled=False, research_enabled=False)
    tool_names = [t["name"] for t in tools]
    assert "research_motif_parallels" not in tool_names


def test_build_tools_includes_research_motif_parallels_when_flag_is_true() -> None:
    from app.assistant.tools import build_tools

    tools = build_tools(motif_induction_enabled=False, research_enabled=True)
    tool_names = [t["name"] for t in tools]
    assert "research_motif_parallels" in tool_names


def test_build_tools_includes_search_dreams_exact() -> None:
    from app.assistant.tools import build_tools

    tools = build_tools()
    tool_names = [t["name"] for t in tools]
    assert "search_dreams_exact" in tool_names


def test_build_tools_includes_search_dreams_by_title_schema() -> None:
    from app.assistant.tools import build_tools

    tools = build_tools()
    title_tool = next(tool for tool in tools if tool["name"] == "search_dreams_by_title")

    assert title_tool["input_schema"]["required"] == ["query"]
    assert "limit" in title_tool["input_schema"]["properties"]
    assert "date" in title_tool["input_schema"]["properties"]
    assert "guessing" in title_tool["description"]


@pytest.mark.asyncio
async def test_execute_tool_search_dreams_labels_verified_strength() -> None:
    dream_id = uuid.uuid4()
    facade = AsyncMock(spec=AssistantFacade)
    facade.search_dreams.return_value = SearchResult(
        items=[
            SearchResultItem(
                dream_id=dream_id,
                date=date(2026, 4, 15),
                title="Church dream",
                chunk_text="Мне приснилась церковь на холме.",
                relevance_score=0.82,
                matched_fragments=[],
                quote="Мне приснилась церковь на холме",
            )
        ]
    )

    result = await tools_module.execute_tool("search_dreams", {"query": "церковь"}, facade)

    assert f"result_id: {dream_id}" in result
    assert "strength: strong" in result
    assert 'evidence_text: "Мне приснилась церковь на холме"' in result
    assert "Quote:" not in result


@pytest.mark.asyncio
async def test_execute_tool_search_dreams_reports_no_more_archive_backed_matches() -> None:
    facade = AsyncMock(spec=AssistantFacade)
    facade.search_dreams.return_value = SearchResult(
        items=[],
        insufficient_reason="No verified archive-backed matches found",
    )

    result = await tools_module.execute_tool("search_dreams", {"query": "молитва"}, facade)

    assert result == "No more archive-backed matches found."
    assert "Мне приснилось" not in result


@pytest.mark.asyncio
async def test_execute_tool_create_dream_requires_explicit_user_request() -> None:
    facade = AsyncMock(spec=AssistantFacade)

    result = await tools_module.execute_tool(
        "create_dream",
        {"raw_text": "I crossed a black river at night."},
        facade,
        chat_id=42,
        request_text="what does this river mean?",
    )

    assert "explicit user request" in result.lower()
    facade.create_dream.assert_not_awaited()


@pytest.mark.parametrize(
    "request_text",
    [
        "сохрани этот сон",
        "запишите мой сон",
        "запиши это в архив",
        "добавь в архив этот текст",
        "сохрани в архив мой сон",
        "сохранить в архив эту запись",
        "занести в архив этот сон",
        "занеси в архив, пожалуйста",
    ],
)
@pytest.mark.asyncio
async def test_execute_tool_create_dream_accepts_extended_explicit_russian_phrases(
    request_text: str,
) -> None:
    facade = AsyncMock(spec=AssistantFacade)
    facade.create_dream.return_value = SimpleNamespace(
        id=uuid.uuid4(),
        created=True,
        date="2026-04-23",
        title="23.04.26, без названия",
        word_count=4,
        source_doc_id="telegram:42",
        written_to_google_doc=True,
        written_to_doc_name="Сны Николая",
    )

    result = await tools_module.execute_tool(
        "create_dream",
        {"raw_text": "Мне снилась река ночью."},
        facade,
        chat_id=42,
        request_text=request_text,
    )

    assert "Dream saved:" in result
    facade.create_dream.assert_awaited_once()


@pytest.mark.parametrize(
    "request_text",
    [
        "сегодня мне приснилось рыба",
        "мне приснилась рыба",
        "мне приснился мост",
        "мне приснились рыбы",
        "сегодня мне приснилось, что я летел над морем",
        "мне приснилось, будто я открыл дверь в сад",
        "мне снилось, что поезд остановился у реки",
        "приснился сон про лестницу и светлую комнату",
        "приснилось, что я снова оказался в школе",
    ],
)
@pytest.mark.asyncio
async def test_execute_tool_create_dream_accepts_natural_russian_dream_openings(
    request_text: str,
) -> None:
    facade = AsyncMock(spec=AssistantFacade)
    facade.create_dream.return_value = SimpleNamespace(
        id=uuid.uuid4(),
        created=True,
        date="2026-05-01",
        title="01.05.26, без названия",
        word_count=7,
        source_doc_id="telegram:42",
        written_to_google_doc=True,
        written_to_doc_name="Сны Николая",
    )

    result = await tools_module.execute_tool(
        "create_dream",
        {"raw_text": request_text},
        facade,
        chat_id=42,
        request_text=request_text,
    )

    assert "Dream saved:" in result
    facade.create_dream.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_tool_create_dream_accepts_russian_relative_date_argument() -> None:
    facade = AsyncMock(spec=AssistantFacade)
    facade.create_dream.return_value = SimpleNamespace(
        id=uuid.uuid4(),
        created=True,
        date="2026-04-30",
        title="о море мост",
        word_count=7,
        source_doc_id="telegram:42",
        written_to_google_doc=True,
        written_to_doc_name="Сны Николая",
    )

    with patch("app.assistant.facade._application_today", return_value=date(2026, 5, 1)):
        result = await tools_module.execute_tool(
            "create_dream",
            {"raw_text": "вчера мне приснилось море и мост", "date": "вчера"},
            facade,
            chat_id=42,
            request_text="запиши сон",
        )

    assert "Dream saved:" in result
    facade.create_dream.assert_awaited_once()
    assert facade.create_dream.await_args.kwargs["dream_date"] == date(2026, 4, 30)


@pytest.mark.asyncio
async def test_execute_tool_create_dream_success_hides_doc_label() -> None:
    facade = AsyncMock(spec=AssistantFacade)
    facade.create_dream.return_value = SimpleNamespace(
        id=uuid.uuid4(),
        created=True,
        date="2026-05-01",
        title="01.05.26, без названия",
        word_count=4,
        source_doc_id="telegram:42",
        written_to_google_doc=True,
        written_to_doc_name="...O1rHIxHs",
    )

    result = await tools_module.execute_tool(
        "create_dream",
        {"raw_text": "запиши сон про рыбу"},
        facade,
        chat_id=42,
        request_text="запиши сон про рыбу",
    )

    assert "Запись добавлена в Google Doc." in result
    assert "...O1rHIxHs" not in result


@pytest.mark.asyncio
async def test_execute_tool_create_dream_failure_does_not_claim_doc_write() -> None:
    facade = AsyncMock(spec=AssistantFacade)
    facade.create_dream.return_value = SimpleNamespace(
        id=uuid.uuid4(),
        created=True,
        date="2026-05-01",
        title="01.05.26, без названия",
        word_count=4,
        source_doc_id="telegram:42",
        written_to_google_doc=False,
        written_to_doc_name="Dream Archive",
    )

    result = await tools_module.execute_tool(
        "create_dream",
        {"raw_text": "запиши сон про рыбу"},
        facade,
        chat_id=42,
        request_text="запиши сон про рыбу",
    )

    assert "Запись добавлена в Google Doc." not in result
    assert "Запись сохранена в архиве." in result
    assert "повтори запись в Google Doc" in result


@pytest.mark.asyncio
async def test_execute_tool_retry_write_reports_nothing_to_retry() -> None:
    facade = AsyncMock(spec=AssistantFacade)
    facade.retry_write_to_google_doc.return_value = (False, "", "nothing_to_retry")

    result = await tools_module.execute_tool(
        "retry_write_to_google_doc",
        {},
        facade,
        chat_id=42,
        request_text="повтори запись в Google Doc",
    )

    assert result == "Нет неудачной записи в Google Doc для повтора."
    facade.retry_write_to_google_doc.assert_awaited_once_with(dream_id=None, chat_id=42)


@pytest.mark.asyncio
async def test_execute_tool_retry_write_failure_is_explicit() -> None:
    facade = AsyncMock(spec=AssistantFacade)
    facade.retry_write_to_google_doc.return_value = (False, "Сны", "retried")

    result = await tools_module.execute_tool(
        "retry_write_to_google_doc",
        {},
        facade,
        chat_id=42,
        request_text="повтори запись в Google Doc",
    )

    assert "Сон не был добавлен в документ" in result


@pytest.mark.asyncio
async def test_execute_tool_retry_write_success_hides_doc_label() -> None:
    facade = AsyncMock(spec=AssistantFacade)
    facade.retry_write_to_google_doc.return_value = (True, "...O1rHIxHs", "retried")

    result = await tools_module.execute_tool(
        "retry_write_to_google_doc",
        {},
        facade,
        chat_id=42,
        request_text="повтори запись в Google Doc",
    )

    assert result == "Запись добавлена в Google Doc."


@pytest.mark.parametrize(
    "request_text",
    [
        "мне приснилось?",
        "сегодня мне приснилось",
        "мне снилось",
        "приснился сон?",
    ],
)
@pytest.mark.asyncio
async def test_execute_tool_create_dream_rejects_short_natural_mentions(
    request_text: str,
) -> None:
    facade = AsyncMock(spec=AssistantFacade)

    result = await tools_module.execute_tool(
        "create_dream",
        {"raw_text": request_text},
        facade,
        chat_id=42,
        request_text=request_text,
    )

    assert "explicit user request" in result.lower()
    facade.create_dream.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_tool_list_recent_dreams_includes_preview_and_themes() -> None:
    dream_id = uuid.uuid4()
    facade = AsyncMock(spec=AssistantFacade)
    facade.list_recent_dreams.return_value = [
        DreamSummary(
            id=dream_id,
            date="2026-04-14",
            title="Bridge dream",
            raw_text_preview="I crossed a bridge at dusk and saw a dark river.",
            theme_names=["Transitions", "Water"],
        )
    ]

    result = await tools_module.execute_tool("list_recent_dreams", {"limit": 1}, facade)

    assert "2026-04-14 | Bridge dream" in result
    assert f"dream_id: {dream_id}" in result
    assert "preview: I crossed a bridge at dusk and saw a dark river." in result
    assert "themes: Transitions, Water" in result
    assert "words" not in result


@pytest.mark.asyncio
async def test_search_dreams_exact_routing() -> None:
    dream_id = uuid.uuid4()
    facade = AsyncMock(spec=AssistantFacade)
    facade.search_dreams_exact.return_value = [
        SearchResultItem(
            dream_id=dream_id,
            date=date(2026, 4, 14),
            title="Church dream",
            chunk_text="Мне приснилась церковь на холме.",
            relevance_score=1.0,
            matched_fragments=[],
            quote="Мне приснилась церковь на холме",
        )
    ]

    result = await tools_module.execute_tool(
        "search_dreams_exact",
        {"query": "церковь"},
        facade,
    )

    assert "Exact search results for 'церковь' (1 fragments):" in result
    assert f"result_id: {dream_id}" in result
    assert 'evidence_text: "Мне приснилась церковь на холме"' in result
    facade.search_dreams_exact.assert_awaited_once_with("церковь")


@pytest.mark.asyncio
async def test_search_dreams_augments_fish_image_query_with_exact_recall() -> None:
    dream_id = uuid.uuid4()
    facade = AsyncMock(spec=AssistantFacade)
    facade.search_dreams.return_value = SearchResult(
        items=[],
        insufficient_reason="No verified archive-backed matches found",
    )
    facade.search_dreams_exact.return_value = [
        SearchResultItem(
            dream_id=dream_id,
            date=date(2026, 4, 14),
            title="Рыба в воде",
            chunk_text="В этом сне была рыба в прозрачной воде.",
            relevance_score=1.0,
            matched_fragments=[],
            quote="В этом сне была рыба в прозрачной воде",
        )
    ]

    result = await tools_module.execute_tool(
        "search_dreams",
        {"query": "сон с рыбой"},
        facade,
    )

    facade.search_dreams.assert_awaited_once_with("сон с рыбой")
    facade.search_dreams_exact.assert_awaited_once_with("рыба")
    assert f"result_id: {dream_id}" in result
    assert 'evidence_text: "В этом сне была рыба в прозрачной воде"' in result
    assert "No more archive-backed matches found." not in result


@pytest.mark.asyncio
async def test_search_dreams_dedupes_exact_and_semantic_image_results() -> None:
    dream_id = uuid.uuid4()
    facade = AsyncMock(spec=AssistantFacade)
    facade.search_dreams.return_value = SearchResult(
        items=[
            SearchResultItem(
                dream_id=dream_id,
                date=date(2026, 4, 14),
                title="Рыба в воде",
                chunk_text="Потом вода стала темной.",
                relevance_score=0.6,
                matched_fragments=[{"text": "вода стала темной", "match_type": "semantic"}],
                quote=None,
            )
        ],
    )
    facade.search_dreams_exact.return_value = [
        SearchResultItem(
            dream_id=dream_id,
            date=date(2026, 4, 14),
            title="Рыба в воде",
            chunk_text="В этом сне была рыба в прозрачной воде.",
            relevance_score=1.0,
            matched_fragments=[],
            quote="В этом сне была рыба в прозрачной воде",
        )
    ]

    result = await tools_module.execute_tool(
        "search_dreams",
        {"query": "сон с рыбой"},
        facade,
    )

    assert result.count(f"result_id: {dream_id}") == 1
    assert "strength: strong" in result
    assert "В этом сне была рыба в прозрачной воде" in result


@pytest.mark.asyncio
async def test_search_dreams_returns_exact_image_result_when_semantic_search_fails() -> None:
    dream_id = uuid.uuid4()
    facade = AsyncMock(spec=AssistantFacade)
    facade.search_dreams.side_effect = RuntimeError("embedding down")
    facade.search_dreams_exact.return_value = [
        SearchResultItem(
            dream_id=dream_id,
            date=date(2026, 4, 14),
            title="Рыба в воде",
            chunk_text="В этом сне была рыба в прозрачной воде.",
            relevance_score=1.0,
            matched_fragments=[],
            quote="В этом сне была рыба в прозрачной воде",
        )
    ]

    result = await tools_module.execute_tool(
        "search_dreams",
        {"query": "сон с рыбой"},
        facade,
    )

    facade.search_dreams_exact.assert_awaited_once_with("рыба")
    facade.search_dreams.assert_awaited_once_with("сон с рыбой")
    assert f"result_id: {dream_id}" in result
    assert 'evidence_text: "В этом сне была рыба в прозрачной воде"' in result


@pytest.mark.asyncio
async def test_execute_tool_search_dreams_by_title_includes_uuid_for_get_dream() -> None:
    dream_id = uuid.uuid4()
    theme_id = uuid.uuid4()
    category_id = uuid.uuid4()
    facade = AsyncMock(spec=AssistantFacade)
    facade.search_dreams_by_title.return_value = [
        DreamTitleSearchResult(
            dream_id=dream_id,
            date="2026-04-14",
            title="Я и дети. Тайное общество",
            raw_text_preview="Я была с детьми и мы нашли тайное общество.",
        )
    ]
    facade.get_dream.return_value = DreamDetail(
        id=dream_id,
        date="2026-04-14",
        title="Я и дети. Тайное общество",
        raw_text="Полный текст сна про детей и тайное общество.",
        word_count=8,
        source_doc_id="doc-1",
        created_at="2026-04-14T00:00:00+00:00",
        segmentation_confidence="high",
        themes=[
            DreamThemeItem(
                id=theme_id,
                category_id=category_id,
                category_name="Children",
                salience=0.9,
                status="draft",
                match_type="semantic",
                fragments=[],
                deprecated=False,
                created_at="2026-04-14T00:00:00+00:00",
            )
        ],
        notes=["важная заметка"],
    )

    result = await tools_module.execute_tool(
        "search_dreams_by_title",
        {"query": "я и дети тайное общество"},
        facade,
    )

    assert "Single title match found for 'я и дети тайное общество'. Full dream:" in result
    assert f"Dream {dream_id}" in result
    assert "Title: Я и дети. Тайное общество" in result
    assert "Text: Полный текст сна про детей и тайное общество." in result
    assert "Themes: Children" in result
    assert "важная заметка" in result
    facade.search_dreams_by_title.assert_awaited_once_with(
        "я и дети тайное общество",
        limit=10,
    )
    facade.get_dream.assert_awaited_once_with(dream_id)


@pytest.mark.asyncio
async def test_execute_tool_search_dreams_by_title_uses_date_to_get_full_dream() -> None:
    dream_id = uuid.uuid4()
    facade = AsyncMock(spec=AssistantFacade)
    facade.search_dreams_by_title.return_value = [
        DreamTitleSearchResult(
            dream_id=dream_id,
            date="2026-04-04",
            title="Кирилл, мужик, настольки",
            raw_text_preview="Начало сна про Кирилла.",
        )
    ]
    facade.get_dream.return_value = DreamDetail(
        id=dream_id,
        date="2026-04-04",
        title="Кирилл, мужик, настольки",
        raw_text="Полный текст сна про Кирилла, мужика и настольки.",
        word_count=9,
        source_doc_id="doc-1",
        created_at="2026-04-04T00:00:00+00:00",
        segmentation_confidence="high",
        themes=[],
        notes=[],
    )

    result = await tools_module.execute_tool(
        "search_dreams_by_title",
        {"query": "Кирилл, мужик, настольки", "date": "04.04.26"},
        facade,
    )

    assert "Full dream" in result
    assert f"Dream {dream_id}" in result
    assert "Text: Полный текст сна про Кирилла, мужика и настольки." in result
    facade.search_dreams_by_title.assert_awaited_once_with(
        "Кирилл, мужик, настольки",
        limit=10,
        dream_date=date(2026, 4, 4),
    )
    facade.get_dream.assert_awaited_once_with(dream_id)


@pytest.mark.asyncio
async def test_execute_tool_search_dreams_by_title_formats_ambiguous_matches() -> None:
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    facade = AsyncMock(spec=AssistantFacade)
    facade.search_dreams_by_title.return_value = [
        DreamTitleSearchResult(
            dream_id=first_id,
            date="2026-04-14",
            title="Тайное общество",
            raw_text_preview="Первый сон.",
        ),
        DreamTitleSearchResult(
            dream_id=second_id,
            date="2026-04-20",
            title="Тайное общество детей",
            raw_text_preview="Второй сон.",
        ),
    ]

    result = await tools_module.execute_tool(
        "search_dreams_by_title",
        {"query": "тайное общество", "limit": 2},
        facade,
    )

    assert "2 matches" in result
    assert "Present these as options; do not guess" in result
    assert f"dream_id: {first_id}" in result
    assert f"dream_id: {second_id}" in result
    facade.search_dreams_by_title.assert_awaited_once_with("тайное общество", limit=2)
    facade.get_dream.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_tool_search_dreams_by_title_falls_back_after_no_title_match() -> None:
    dream_id = uuid.uuid4()
    facade = AsyncMock(spec=AssistantFacade)
    facade.search_dreams_by_title.return_value = []
    facade.search_dreams.return_value = SearchResult(
        items=[
            SearchResultItem(
                dream_id=dream_id,
                date=date(2026, 4, 14),
                title="Другой заголовок",
                chunk_text="Тайное общество было в тексте сна.",
                relevance_score=0.74,
                matched_fragments=[],
                quote="Тайное общество было в тексте сна",
            )
        ]
    )

    result = await tools_module.execute_tool(
        "search_dreams_by_title",
        {"query": "тайное общество"},
        facade,
    )

    assert "No title match found for 'тайное общество'. Content search results:" in result
    assert f"result_id: {dream_id}" in result
    assert 'evidence_text: "Тайное общество было в тексте сна"' in result
    facade.search_dreams_by_title.assert_awaited_once_with("тайное общество", limit=10)
    facade.search_dreams.assert_awaited_once_with("тайное общество")
    facade.get_dream.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_tool_search_dreams_by_title_uses_default_for_bad_limit() -> None:
    dream_id = uuid.uuid4()
    facade = AsyncMock(spec=AssistantFacade)
    facade.search_dreams_by_title.return_value = [
        DreamTitleSearchResult(
            dream_id=dream_id,
            date="2026-04-14",
            title="Тайное общество",
            raw_text_preview="Первый сон.",
        ),
        DreamTitleSearchResult(
            dream_id=uuid.uuid4(),
            date="2026-04-20",
            title="Тайное общество детей",
            raw_text_preview="Второй сон.",
        ),
    ]

    result = await tools_module.execute_tool(
        "search_dreams_by_title",
        {"query": "тайное общество", "limit": "not-a-number"},
        facade,
    )

    assert "Title search results for 'тайное общество'" in result
    facade.search_dreams_by_title.assert_awaited_once_with("тайное общество", limit=10)


@pytest.mark.asyncio
async def test_execute_tool_get_dream_returns_complete_text_without_truncation() -> None:
    dream_id = uuid.uuid4()
    long_text = "Начало сна. " + ("длинный фрагмент " * 180) + "Финальная строка сна."
    facade = AsyncMock(spec=AssistantFacade)
    facade.get_dream.return_value = DreamDetail(
        id=dream_id,
        date="2026-05-15",
        title="Длинный сон",
        raw_text=long_text,
        word_count=len(long_text.split()),
        source_doc_id="doc-1",
        created_at="2026-05-15T00:00:00+00:00",
        segmentation_confidence="high",
        themes=[],
        notes=[],
    )

    result = await tools_module.execute_tool(
        "get_dream",
        {"dream_id": str(dream_id)},
        facade,
    )

    assert f"Dream {dream_id}" in result
    assert "Text: Начало сна." in result
    assert "Финальная строка сна." in result
    assert long_text in result


def test_system_prompt_routes_title_lookup_to_title_search_first() -> None:
    assert "search_dreams_by_title first" in SYSTEM_PROMPT
    assert "specific dream by title" in SYSTEM_PROMPT
    assert "copy the Text field completely and verbatim" in SYSTEM_PROMPT
    assert "Never claim that a title-to-UUID lookup is unavailable." in SYSTEM_PROMPT
    assert "pass it as the date argument" in SYSTEM_PROMPT
    assert "multiple matches" in SYSTEM_PROMPT
    assert "do not guess" in SYSTEM_PROMPT


def test_system_prompt_requires_honest_failed_sync_status() -> None:
    assert "Do not describe a failed sync as merely unfinished." in SYSTEM_PROMPT
    assert "new material may not be visible until a successful sync completes" in SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_execute_tool_get_dream_motifs_includes_motif_uuid() -> None:
    dream_id = uuid.uuid4()
    motif_id = uuid.uuid4()
    facade = AsyncMock(spec=AssistantFacade)
    facade.get_dream_motifs.return_value = [
        MotifInductionItem(
            id=motif_id,
            label="Threshold crossing",
            rationale="The dream repeatedly frames passage through liminal spaces.",
            confidence="high",
            status="confirmed",
            fragments=[],
            model_version="test",
            created_at="2026-04-23T00:00:00+00:00",
        )
    ]

    result = await tools_module.execute_tool(
        "get_dream_motifs",
        {"dream_id": str(dream_id)},
        facade,
    )

    assert f"- [high confidence] Threshold crossing (confirmed by user) [id={motif_id}]" in result
    assert "  Rationale: The dream repeatedly frames passage through liminal spaces." in result


@pytest.mark.asyncio
async def test_execute_tool_manage_archive_source_get_returns_current_doc_id() -> None:
    facade = AsyncMock(spec=AssistantFacade)
    facade.get_archive_source.return_value = "doc-current-123"

    result = await tools_module.execute_tool(
        "manage_archive_source",
        {"action": "get"},
        facade,
    )

    assert result == "Current primary archive source: doc-current-123"
    facade.get_archive_source.assert_called_once_with()
    facade.set_archive_source.assert_not_called()


@pytest.mark.asyncio
async def test_execute_tool_trigger_sync_formats_single_ref() -> None:
    job_id = uuid.uuid4()
    facade = AsyncMock(spec=AssistantFacade)
    facade.trigger_sync.return_value = [
        SimpleNamespace(job_id=job_id, doc_id="doc-123", status="queued")
    ]

    result = await tools_module.execute_tool(
        "trigger_sync",
        {"doc_id": "doc-123"},
        facade,
    )

    assert result == (
        "Запустил обновление архива: …doc-123. "
        "Обычно это занимает 1-2 минуты. "
        "Я напишу, когда документ будет готов или если синхронизация не получится."
    )
    assert str(job_id) not in result
    facade.trigger_sync.assert_awaited_once_with("doc-123", chat_id=None)


@pytest.mark.asyncio
async def test_execute_tool_trigger_sync_formats_multiple_refs() -> None:
    facade = AsyncMock(spec=AssistantFacade)
    facade.trigger_sync.return_value = [
        SimpleNamespace(job_id=uuid.uuid4(), doc_id="doc-a", status="queued"),
        SimpleNamespace(job_id=uuid.uuid4(), doc_id="doc-b", status="queued"),
    ]

    result = await tools_module.execute_tool(
        "trigger_sync",
        {},
        facade,
    )

    assert "Запустил обновление архива по документам: 2." in result
    assert "- …doc-a" in result
    assert "- …doc-b" in result
    assert "job_id" not in result
    assert "Я напишу, когда документ будет готов" in result
    facade.trigger_sync.assert_awaited_once_with("", chat_id=None)


@pytest.mark.asyncio
async def test_execute_tool_get_sync_status_formats_statuses() -> None:
    facade = AsyncMock(spec=AssistantFacade)
    facade.get_sync_status.return_value = [
        SimpleNamespace(
            doc_id="doc-123",
            status="running",
            last_checked_at="2026-05-06T10:00:00+00:00",
            last_sync_started_at=datetime(2026, 5, 6, 9, 59, tzinfo=timezone.utc).isoformat(),
            last_synced_at=None,
            last_sync_job_id="job-1",
            is_stale_running=False,
            last_sync_error=None,
            last_added_count=None,
            last_sync_stage="store",
        )
    ]

    result = await tools_module.execute_tool(
        "get_sync_status",
        {"doc_id": "doc-123"},
        facade,
    )

    assert "Статус архива:" in result
    assert "…doc-123: синхронизируется" in result
    assert "обычно это занимает 1-2 минуты" in result
    assert "последняя проверка: 06.05.26 10:00" in result
    assert "job_id" not in result
    facade.get_sync_status.assert_awaited_once_with("doc-123")


@pytest.mark.asyncio
async def test_execute_tool_get_sync_status_formats_failed_status_honestly() -> None:
    facade = AsyncMock(spec=AssistantFacade)
    facade.get_sync_status.return_value = [
        SimpleNamespace(
            doc_id="doc-123",
            status="failed",
            last_checked_at="2026-05-09T14:44:44+00:00",
            last_sync_started_at=None,
            last_synced_at="2026-04-26T10:16:43+00:00",
            last_sync_job_id="job-1",
            is_stale_running=False,
            last_sync_error="Внутренняя ошибка синхронизации",
            last_added_count=None,
            last_sync_stage="failed",
        )
    ]

    result = await tools_module.execute_tool(
        "get_sync_status",
        {"doc_id": "doc-123"},
        facade,
    )

    assert "последняя синхронизация завершилась ошибкой" in result
    assert "новые сны из Google Docs могут пока не находиться" in result
    assert "Внутренняя ошибка синхронизации" in result
    assert "последний успех: 26.04.26 10:16" in result
    assert "последняя проверка: 09.05.26 14:44" in result


@pytest.mark.asyncio
async def test_execute_tool_get_sync_status_explains_zero_new_entries() -> None:
    facade = AsyncMock(spec=AssistantFacade)
    facade.get_sync_status.return_value = [
        SimpleNamespace(
            doc_id="doc-123",
            status="synced",
            last_checked_at="2026-05-09T14:44:44+00:00",
            last_sync_started_at=None,
            last_synced_at="2026-05-09T14:44:44+00:00",
            last_sync_job_id="job-1",
            is_stale_running=False,
            last_sync_error=None,
            last_added_count=0,
            last_sync_stage="done",
        )
    ]

    result = await tools_module.execute_tool(
        "get_sync_status",
        {"doc_id": "doc-123"},
        facade,
    )

    assert "готово; новых снов не найдено" in result
    assert "job_id" not in result


@pytest.mark.asyncio
async def test_execute_tool_get_sync_status_formats_stale_running_status() -> None:
    facade = AsyncMock(spec=AssistantFacade)
    facade.get_sync_status.return_value = [
        SimpleNamespace(
            doc_id="doc-123",
            status="running",
            last_checked_at="2026-05-09T14:44:44+00:00",
            last_sync_started_at="2026-05-09T12:00:00+00:00",
            last_synced_at=None,
            last_sync_job_id="job-1",
            is_stale_running=True,
            last_sync_error=None,
            last_added_count=None,
            last_sync_stage="store",
        )
    ]

    result = await tools_module.execute_tool(
        "get_sync_status",
        {"doc_id": "doc-123"},
        facade,
    )

    assert "похоже зависла" in result
    assert "новые сны из этого документа пока могут не находиться" in result
    assert "Можно перезапустить синхронизацию" in result


@pytest.mark.asyncio
async def test_execute_tool_manage_archive_source_set_updates_doc_id() -> None:
    facade = AsyncMock(spec=AssistantFacade)
    facade.set_archive_source.return_value = "doc-next-456"

    result = await tools_module.execute_tool(
        "manage_archive_source",
        {"action": "set", "doc_id": "doc-next-456"},
        facade,
    )

    assert result == "Primary archive source updated to: doc-next-456 (takes effect on next sync)"
    facade.set_archive_source.assert_called_once_with("doc-next-456")


@pytest.mark.asyncio
async def test_execute_tool_manage_archive_source_list_formats_connected_docs() -> None:
    facade = AsyncMock(spec=AssistantFacade)
    facade.list_archive_sources.return_value = ["doc-primary", "doc-extra"]
    facade.get_archive_source.return_value = "doc-primary"

    result = await tools_module.execute_tool(
        "manage_archive_source",
        {"action": "list"},
        facade,
    )

    assert result.startswith("Connected Google Docs:")
    assert "(doc-primary)" in result
    assert "(doc-extra)" in result
    assert "← куда пишем" in result
    facade.list_archive_sources.assert_called_once_with()


@pytest.mark.asyncio
async def test_execute_tool_manage_archive_source_add_returns_updated_list() -> None:
    facade = AsyncMock(spec=AssistantFacade)
    facade.add_archive_source.return_value = ["doc-primary", "doc-extra"]
    facade.trigger_sync.return_value = [
        SimpleNamespace(job_id=uuid.uuid4(), doc_id="doc-extra", status="queued")
    ]

    result = await tools_module.execute_tool(
        "manage_archive_source",
        {"action": "add", "doc_id": "doc-extra"},
        facade,
        chat_id=42,
    )

    assert result.startswith("Archive source added. Sync started. Updated list:")
    assert "(doc-primary)" in result
    assert "(doc-extra)" in result
    assert "Обновление" in result
    assert "job_id" not in result
    assert "Я напишу, когда документ будет готов" in result
    facade.add_archive_source.assert_called_once_with("doc-extra")
    facade.trigger_sync.assert_awaited_once_with("doc-extra", chat_id=42)


@pytest.mark.asyncio
async def test_execute_tool_manage_archive_source_remove_returns_updated_list() -> None:
    facade = AsyncMock(spec=AssistantFacade)
    facade.remove_archive_source.return_value = ["doc-primary", "doc-extra-2"]

    result = await tools_module.execute_tool(
        "manage_archive_source",
        {"action": "remove", "doc_id": "doc-extra-1"},
        facade,
    )

    assert result.startswith("Archive source removed. Updated list:")
    assert "(doc-primary)" in result
    assert "(doc-extra-2)" in result
    facade.remove_archive_source.assert_called_once_with("doc-extra-1")


@pytest.mark.asyncio
async def test_execute_tool_add_dream_note_returns_message() -> None:
    facade = AsyncMock(spec=AssistantFacade)
    facade.add_dream_note.return_value = (True, "Заметка добавлена.")

    result = await tools_module.execute_tool(
        "add_dream_note",
        {"note_text": "красная дверь"},
        facade,
        chat_id=42,
    )

    assert result == "Заметка добавлена."
    facade.add_dream_note.assert_called_once_with("красная дверь", dream_id=None, chat_id=42)


@pytest.mark.asyncio
async def test_execute_tool_add_dream_note_empty_text_returns_error() -> None:
    facade = AsyncMock(spec=AssistantFacade)

    result = await tools_module.execute_tool(
        "add_dream_note",
        {"note_text": ""},
        facade,
    )

    assert result == "note_text is required."
    facade.add_dream_note.assert_not_called()


@pytest.mark.asyncio
async def test_execute_tool_prepare_dream_interpretation_stores_pending_request() -> None:
    dream_id = uuid.uuid4()
    facade = AsyncMock(spec=AssistantFacade)
    facade.prepare_dream_interpretation_request.return_value = SimpleNamespace(
        dream_id=dream_id,
        title="Запретная рыба",
        prompt="approved prompt",
    )
    clear_pending_interpretation_request(42)

    result = await tools_module.execute_tool(
        "prepare_dream_interpretation",
        {"request": "что значит рыба?"},
        facade,
        chat_id=42,
    )

    assert "Подготовлен запрос на интерпретацию сна «Запретная рыба»." in result
    assert "ответьте «да»" in result
    pending = load_pending_interpretation_request(42)
    assert pending is not None
    assert pending.dream_id == str(dream_id)
    assert pending.prompt == "approved prompt"
    clear_pending_interpretation_request(42)


@pytest.mark.asyncio
async def test_execute_tool_prepare_dream_interpretation_without_dream_returns_message() -> None:
    facade = AsyncMock(spec=AssistantFacade)
    facade.prepare_dream_interpretation_request.return_value = None

    result = await tools_module.execute_tool(
        "prepare_dream_interpretation",
        {},
        facade,
        chat_id=42,
    )

    assert result == "Не найден сон для интерпретации."
