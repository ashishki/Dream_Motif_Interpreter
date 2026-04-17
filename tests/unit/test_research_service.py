from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.research import ResearchResult
from app.services.research_service import ResearchService


class _StubResearchRetriever:
    def __init__(self, sources: list[dict[str, str]]) -> None:
        self._sources = sources
        self.retrieve = AsyncMock(return_value=sources)


class _StubResearchSynthesizer:
    def __init__(self, parallels: list[dict[str, str]]) -> None:
        self._parallels = parallels
        self.synthesize = AsyncMock(return_value=parallels)


def _make_motif(*, status: str = "confirmed", label: str = "black river") -> Any:
    motif = MagicMock()
    motif.id = uuid.uuid4()
    motif.dream_id = uuid.uuid4()
    motif.label = label
    motif.status = status
    return motif


def _make_session(motif: Any) -> MagicMock:
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = motif
    session.execute = AsyncMock(return_value=execute_result)
    return session


@pytest.mark.asyncio
async def test_run_raises_value_error_when_motif_is_not_confirmed() -> None:
    motif = _make_motif(status="draft")
    session = _make_session(motif)
    retriever = _StubResearchRetriever([])
    synthesizer = _StubResearchSynthesizer([])
    service = ResearchService(retriever=retriever, synthesizer=synthesizer)

    with pytest.raises(ValueError, match="confirmed motifs"):
        await service.run(motif.id, session, triggered_by="user")

    retriever.retrieve.assert_not_awaited()
    synthesizer.synthesize.assert_not_awaited()
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_run_creates_research_result_with_correct_fields() -> None:
    motif = _make_motif(label="flooded staircase")
    session = _make_session(motif)
    sources = [
        {
            "url": "https://example.com/flood",
            "excerpt": "Excerpt",
            "retrieved_at": "2026-04-17T10:00:00+00:00",
        }
    ]
    parallels = [
        {
            "domain": "folklore",
            "label": "threshold crossing under water",
            "source_url": "https://example.com/flood",
            "relevance_note": "Both involve impeded ascent and inundation.",
            "confidence": "plausible",
        }
    ]
    retriever = _StubResearchRetriever(sources)
    synthesizer = _StubResearchSynthesizer(parallels)
    service = ResearchService(retriever=retriever, synthesizer=synthesizer)

    result = await service.run(motif.id, session, triggered_by="chat-123")

    retriever.retrieve.assert_awaited_once_with("flooded staircase")
    synthesizer.synthesize.assert_awaited_once_with("flooded staircase", sources)
    session.add.assert_called_once()
    added_row = session.add.call_args[0][0]

    assert isinstance(result, ResearchResult)
    assert result is added_row
    assert result.motif_id == motif.id
    assert result.dream_id == motif.dream_id
    assert result.query_label == "flooded staircase"
    assert result.parallels == parallels
    assert result.sources == sources
    assert result.triggered_by == "chat-123"


@pytest.mark.asyncio
async def test_run_does_not_call_session_commit() -> None:
    motif = _make_motif()
    session = _make_session(motif)
    retriever = _StubResearchRetriever([])
    synthesizer = _StubResearchSynthesizer([])
    service = ResearchService(retriever=retriever, synthesizer=synthesizer)

    await service.run(motif.id, session, triggered_by="user")

    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_run_sets_triggered_by_from_caller_value() -> None:
    motif = _make_motif()
    session = _make_session(motif)
    retriever = _StubResearchRetriever([])
    synthesizer = _StubResearchSynthesizer([])
    service = ResearchService(retriever=retriever, synthesizer=synthesizer)

    result = await service.run(motif.id, session, triggered_by="assistant-session-42")

    assert result.triggered_by == "assistant-session-42"
