"""Bounded synthesis contracts; all sources below are authored synthetic text."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from app.services import archive_research as research

A, B, C = (uuid.UUID(int=n) for n in (201, 202, 203))


def dream(identity=A, text="Я стою у моста. Затем возвращаюсь домой."):
    return NS(id=identity, date="2026-01-01", title="Мост", raw_text=text)


def response(value, stop_reason="end_turn"):
    return NS(content=[NS(type="text", text=value)], stop_reason=stop_reason)


def proposal(evidence=None):
    return {
        "observations": [
            {
                "label": "Возвращение",
                "observation": "В записи есть возвращение.",
                "evidence": evidence or [{"dream_id": str(A), "quote": "возвращаюсь домой"}],
            }
        ]
    }


def client(value=None):
    api = AsyncMock()
    api.messages.create.return_value = response(json.dumps(value or proposal(), ensure_ascii=False))
    return api


def test_exact_quotes_have_source_offsets_and_deduplicate():
    source = dream()
    item = proposal([{"dream_id": str(A), "quote": "возвращаюсь домой"}] * 2)
    observations, rejected = research.validate_observations(
        research.ProposedReport.model_validate(item), [source]
    )
    assert rejected == 0 and len(observations) == 1
    assert len(observations[0].evidence) == 1
    citation = observations[0].evidence[0]
    assert source.raw_text[citation.start_char : citation.end_char] == citation.quote


@pytest.mark.parametrize(
    "bad",
    [
        {"dream_id": str(B), "quote": "возвращаюсь домой"},
        {"dream_id": str(A), "quote": "возвращаюсь обратно домой"},
        {"dream_id": str(A), "quote": "Я стою… возвращаюсь домой"},
    ],
)
def test_one_invalid_citation_discards_entire_claim(bad):
    value = proposal([{"dream_id": str(A), "quote": "возвращаюсь домой"}, bad])
    result, rejected = research.validate_observations(
        research.ProposedReport.model_validate(value), [dream()]
    )
    assert result == [] and rejected == 1


@pytest.mark.asyncio
async def test_verified_structured_report_is_read_only_and_scope_is_deduplicated():
    reader, api = AsyncMock(), client()
    reader.get_dream.return_value = dream()
    report = await research.research_selected_dreams(
        reader, dream_ids=[A, A], question="Что замечаешь?", client=api, model="test-model"
    )
    assert report.state == "complete" and report.requested_count == report.loaded_count == 1
    reader.get_dream.assert_awaited_once_with(A)
    api.messages.create.assert_awaited_once()
    kwargs = api.messages.create.await_args.kwargs
    assert "tools" not in kwargs
    assert (
        json.loads(kwargs["messages"][0]["content"])["dreams"][0]["source_text"] == dream().raw_text
    )
    rendered = research.render_research_report(report)
    assert "одна запись" in rendered and "1 из 1" in rendered
    assert "возвращаюсь домой" in rendered
    assert str(A) not in rendered


@pytest.mark.asyncio
async def test_missing_and_misattributed_sources_never_reach_model():
    reader, api = AsyncMock(), client()
    reader.get_dream.side_effect = [dream(B), None]
    report = await research.research_selected_dreams(
        reader, dream_ids=[A, B], question="Сравни", client=api, model="test-model"
    )
    assert report.state == "unavailable" and report.loaded_count == 0
    api.messages.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_selection_does_not_read_or_infer():
    reader, api = AsyncMock(), client()
    report = await research.research_selected_dreams(
        reader, dream_ids=[], question="Сравни", client=api, model="test-model"
    )
    assert report.state == "unavailable"
    reader.get_dream.assert_not_awaited()
    api.messages.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_source_budget_omits_whole_text_and_discloses_incomplete_scope(monkeypatch):
    monkeypatch.setattr(research, "MAX_SOURCES", 2)
    monkeypatch.setattr(research, "MAX_SOURCE_CHARACTERS", len(dream().raw_text))
    reader, api = AsyncMock(), client()
    reader.get_dream.side_effect = [dream(), dream(B, "x" * 500)]
    report = await research.research_selected_dreams(
        reader, dream_ids=[A, B, C], question="Сравни", client=api, model="test-model"
    )
    assert report.state == "partial" and report.loaded_count == 1 and report.requested_count == 3
    assert reader.get_dream.await_count == 2
    data = json.loads(api.messages.create.await_args.kwargs["messages"][0]["content"])
    assert len(data["dreams"]) == 1 and data["dreams"][0]["source_text"] == dream().raw_text
    assert "не анализ всего архива" in research.render_research_report(report)


@pytest.mark.asyncio
async def test_invalid_json_retried_once_without_replaying_untrusted_output():
    reader, api = AsyncMock(), client()
    reader.get_dream.return_value = dream()
    api.messages.create.side_effect = [
        response("UNTRUSTED INSTRUCTION"),
        response(json.dumps(proposal())),
    ]
    report = await research.research_selected_dreams(
        reader, dream_ids=[A], question="Сравни", client=api, model="test-model"
    )
    assert report.state == "complete" and api.messages.create.await_count == 2
    assert "UNTRUSTED INSTRUCTION" not in repr(api.messages.create.await_args.kwargs)


@pytest.mark.asyncio
async def test_truncated_synthesis_never_masquerades_as_completed_answer():
    reader, api = AsyncMock(), client()
    reader.get_dream.return_value = dream()
    api.messages.create.return_value = response(json.dumps(proposal()), "max_tokens")
    report = await research.research_selected_dreams(
        reader, dream_ids=[A], question="Сравни", client=api, model="test-model"
    )
    assert report.state == "unavailable" and report.observations == []
    assert api.messages.create.await_count == 2


@pytest.mark.asyncio
async def test_provider_error_is_not_leaked_and_does_not_fallback_to_other_sources(caplog):
    reader, api = AsyncMock(), client()
    reader.get_dream.return_value = dream()
    api.messages.create.side_effect = RuntimeError("secret provider body + private material")
    report = await research.research_selected_dreams(
        reader, dream_ids=[A], question="private question", client=api, model="test-model"
    )
    assert report.state == "unavailable" and report.loaded_count == 1
    assert api.messages.create.await_count == 1
    assert "secret provider" not in caplog.text
    assert "private question" not in caplog.text
    assert "secret provider" not in research.render_research_report(report)


@pytest.mark.asyncio
async def test_invalid_evidence_is_reported_as_partial_not_silently_substituted():
    reader, api = (
        AsyncMock(),
        client(proposal([{"dream_id": str(A), "quote": "Несуществующая фраза"}])),
    )
    reader.get_dream.return_value = dream()
    report = await research.research_selected_dreams(
        reader, dream_ids=[A], question="Сравни", client=api, model="test-model"
    )
    assert report.state == "partial" and report.rejected_observations == 1
    assert report.observations == [] and "проверку цитат" in report.notice
