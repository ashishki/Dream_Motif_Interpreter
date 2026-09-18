"""Authored-synthetic journeys, not evidence of live model or operator quality."""

from __future__ import annotations

import uuid
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest

from app.assistant.chat import (
    ChatResult,
    _finish_bounded_answer,
    handle_chat_with_metadata,
)
from app.assistant.facade import AssistantFacade
from app.assistant.session import (
    DisplayedDreamRef,
    RedisOperationalStateStore,
    load_displayed_dream_set,
    load_recent_dream_set,
    save_displayed_dream_set,
    save_recent_dream_set,
)
from app.assistant import session as session_module
from app.telegram.handlers import _remember_displayed_dreams

A, B, C = (str(uuid.UUID(int=n)) for n in (101, 102, 103))


def response(reason, text="", tools=()):
    return NS(
        stop_reason=reason,
        content=[NS(type="text", text=text), *tools],
        usage=NS(input_tokens=1, output_tokens=1),
    )


def tool(name, query="мост"):
    return NS(type="tool_use", id=str(uuid.uuid4()), name=name, input={"query": query})


def detail(identity, title):
    return NS(
        id=uuid.UUID(identity),
        title=title,
        date="2026-01-01",
        raw_text="Синтетическая запись: я у моста.",
        notes=[],
    )


def refs():
    return [
        DisplayedDreamRef(i, identity, "2026-01-01", title)
        for i, (identity, title) in enumerate([(A, "Мост"), (B, "Вокзал"), (C, "Окно")], 1)
    ]


class MemoryRedis:
    def __init__(self):
        self.values = {}

    async def set(self, key, value, ex=None):
        assert ex is not None and ex > 0
        self.values[key] = value

    async def get(self, key):
        return self.values.get(key)

    async def delete(self, key):
        self.values.pop(key, None)


@pytest.mark.asyncio
async def test_visible_selection_round_trip_keeps_identity_and_original_expiry():
    store = RedisOperationalStateStore(MemoryRedis())
    created = datetime.now(timezone.utc) - timedelta(minutes=119)
    selected = save_displayed_dream_set(42, refs=refs(), created_at=created)
    await store.save_displayed_set(42, selected)
    session_module._displayed_dream_sets.clear()
    session_module._recent_dream_sets.clear()
    facade = AsyncMock(spec=AssistantFacade)
    facade.get_dream.return_value = detail(B, "Вокзал")
    with patch("app.assistant.chat.AsyncAnthropic") as llm:
        result = await handle_chat_with_metadata(
            "покажи второй целиком", facade, chat_id=42, operational_state_store=store
        )
    llm.assert_not_called()
    facade.get_dream.assert_awaited_once_with(uuid.UUID(B))
    assert result.preserve_selection
    restored = load_displayed_dream_set(42)
    assert restored.selection_id == selected.selection_id
    assert restored.created_at == created
    assert load_recent_dream_set(42).created_at == created


@pytest.mark.asyncio
async def test_remove_updates_only_delivered_selection_never_archive():
    original = save_displayed_dream_set(42, refs=refs())
    facade = AsyncMock(spec=AssistantFacade)
    result = await handle_chat_with_metadata("Третий не подходит", facade, chat_id=42)
    assert [r.dream_id for r in result.selection_refs] == [A, B]
    assert load_displayed_dream_set(42) == original  # No transition before Telegram delivery.
    facade.create_dream.assert_not_called()
    facade.add_dream_note.assert_not_called()
    await _remember_displayed_dreams(42, result.text, result, state_store=None)
    assert [r.dream_id for r in load_displayed_dream_set(42).refs] == [A, B]
    assert load_recent_dream_set(42).dream_ids == [A, B]


@pytest.mark.asyncio
async def test_open_does_not_replace_working_set_after_delivery():
    selected = save_displayed_dream_set(42, refs=refs())
    facade = AsyncMock(spec=AssistantFacade)
    facade.get_dream.return_value = detail(B, "Вокзал")
    result = await handle_chat_with_metadata("открой второй", facade, chat_id=42)
    await _remember_displayed_dreams(
        42, result.text, result, state_store=None, sent_message=NS(message_id=800)
    )
    assert load_displayed_dream_set(42) == selected
    assert session_module.load_displayed_dream_message(42, 800).refs[0].dream_id == B


@pytest.mark.asyncio
async def test_empty_search_clears_old_selection_after_delivery():
    save_displayed_dream_set(42, refs=refs())
    result = ChatResult(
        "В этой выдаче нет подходящих записей", ["search_dreams"], selection_refs=[]
    )
    await _remember_displayed_dreams(42, result.text, result, state_store=None)
    assert load_displayed_dream_set(42).refs == []
    assert load_recent_dream_set(42).dream_ids == []
    facade = AsyncMock(spec=AssistantFacade)
    with patch("app.assistant.chat.AsyncAnthropic") as llm:
        result = await handle_chat_with_metadata("открой второй", facade, chat_id=42)
    llm.assert_not_called()
    assert "не буду угадывать" in result.text
    facade.get_dream.assert_not_called()


@pytest.mark.asyncio
async def test_intermediate_searches_do_not_replace_selection_and_final_order_wins():
    save_recent_dream_set(42, query="старое", dream_ids=[C])
    facade = AsyncMock(spec=AssistantFacade)

    async def execute(name, payload, *_args, **_kwargs):
        assert load_recent_dream_set(42).dream_ids == [C]
        identity, title = (A, "Мост") if payload["query"] == "мост" else (B, "Вокзал")
        return f'- result_id: {identity}\n  date: 2026-01-01\n  title: {title}\n  evidence_text: "Я у моста."'

    client = AsyncMock()
    client.messages.create.side_effect = [
        response("tool_use", tools=[tool("search_dreams", "мост")]),
        response("tool_use", tools=[tool("search_dreams", "поезд")]),
        response("end_turn", "1. 01.01.26, Вокзал: цитата.\n2. 01.01.26, Мост: цитата."),
    ]
    with (
        patch("app.assistant.chat.AsyncAnthropic", return_value=client),
        patch("app.assistant.chat.execute_tool", side_effect=execute),
    ):
        result = await handle_chat_with_metadata("Найди места перехода", facade, chat_id=42)
    assert [r.dream_id for r in result.selection_refs] == [B, A]
    assert load_recent_dream_set(42).dream_ids == [C]
    await _remember_displayed_dreams(42, result.text, result, state_store=None)
    assert load_recent_dream_set(42).dream_ids == [B, A]
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_five_tool_rounds_get_a_read_only_final_answer_not_planning_text():
    client = AsyncMock()
    client.messages.create.side_effect = [
        response("tool_use", "Сейчас посмотрю", [tool("get_patterns")]) for _ in range(5)
    ] + [response("end_turn", "Проверенные материалы собраны.")]
    facade = AsyncMock(spec=AssistantFacade)
    execute = AsyncMock(return_value="No patterns")
    with (
        patch("app.assistant.chat.AsyncAnthropic", return_value=client),
        patch("app.assistant.chat.execute_tool", execute),
    ):
        result = await handle_chat_with_metadata("Что есть в архиве?", facade)
    assert "Сейчас посмотрю" not in result.text
    assert result.text == "Проверенные материалы собраны."
    assert client.messages.create.await_count == 6
    assert execute.await_count == 5
    assert client.messages.create.await_args.kwargs["tool_choice"] == {"type": "none"}


@pytest.mark.asyncio
async def test_finalizer_does_not_execute_a_provider_tool_request():
    client = AsyncMock()
    client.messages.create.return_value = response("tool_use", "Сохранено", [tool("create_dream")])
    result = await _finish_bounded_answer(
        client, model="test-model", system_prompt="test", messages=[], tools=[]
    )
    assert "Сохранено" not in result
    assert "заверш" in result


@pytest.mark.asyncio
async def test_token_stop_is_explicit_and_client_closes():
    client = AsyncMock()
    client.messages.create.return_value = response("max_tokens", "Часть ответа")
    with patch("app.assistant.chat.AsyncAnthropic", return_value=client):
        result = await handle_chat_with_metadata("Вопрос", AsyncMock(spec=AssistantFacade))
    assert "не полный результат" in result.text
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_scoped_analysis_failure_never_falls_back_to_unrelated_search():
    save_displayed_dream_set(42, refs=refs())
    client = AsyncMock()
    client.messages.create.side_effect = RuntimeError("synthetic provider failure")
    facade = AsyncMock(spec=AssistantFacade)
    facade.get_dream.side_effect = [detail(A, "Мост"), detail(B, "Вокзал"), detail(C, "Окно")]
    with patch("app.assistant.chat.AsyncAnthropic", return_value=client):
        result = await handle_chat_with_metadata("Что у них общего?", facade, chat_id=42)
    assert result.preserve_selection
    assert "Подборка не изменена" in result.text
    facade.search_dreams.assert_not_called()
    assert client.messages.create.await_count == 1


@pytest.mark.asyncio
async def test_partial_analysis_discloses_actual_sources_without_changing_scope():
    save_displayed_dream_set(42, refs=refs())
    client = AsyncMock()
    client.messages.create.return_value = response(
        "end_turn",
        json.dumps(
            {
                "observations": [
                    {
                        "label": "Мост",
                        "observation": "Осторожное наблюдение.",
                        "evidence": [{"dream_id": A, "quote": "я у моста"}],
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )
    facade = AsyncMock(spec=AssistantFacade)
    facade.get_dream.side_effect = [detail(A, "Мост"), None, detail(C, "Окно")]
    with patch("app.assistant.chat.AsyncAnthropic", return_value=client):
        result = await handle_chat_with_metadata("Сравни оставшиеся", facade, chat_id=42)
    assert "2 из 3" in result.text
    assert result.preserve_selection
    assert [r.dream_id for r in result.dream_refs] == [A, B, C]
    # Original ordinals remain visible, including sources not processed this time.
    assert "2. 01.01.26 — Вокзал" in result.text
    assert "3. 01.01.26 — Окно" in result.text
    await _remember_displayed_dreams(42, result.text, result, state_store=None)
    assert [r.dream_id for r in load_displayed_dream_set(42).refs] == [A, B, C]
