from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.assistant.facade import (
    AssistantFacade,
    DreamDetail,
    MotifInductionItem,
    SearchResult,
    SyncJobRef,
)
from app.retrieval.query import EvidenceBlock, FragmentMatch, InsufficientEvidence


class _FakeScalars:
    def __init__(self, items):
        self._items = list(items)

    def all(self):
        return list(self._items)


class _FakeResult:
    def __init__(self, *, rows=None, scalars=None):
        self._rows = list(rows or [])
        self._scalars = list(scalars or [])

    def all(self):
        return list(self._rows)

    def scalars(self):
        return _FakeScalars(self._scalars)


class _FakeSession:
    def __init__(self, *, get_result=None, execute_results=None):
        self._get_result = get_result
        self._execute_results = list(execute_results or [])

    async def get(self, model, identity):
        del model, identity
        return self._get_result

    async def execute(self, statement):
        del statement
        return self._execute_results.pop(0)


class _SessionFactoryContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        del exc_type, exc, tb
        return False


class _FakeSessionFactory:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return _SessionFactoryContext(self._session)


@pytest.mark.asyncio
async def test_search_dreams_returns_facade_search_result() -> None:
    dream_id = uuid4()
    rag_query_service = SimpleNamespace(
        retrieve=AsyncMock(
            return_value=[
                EvidenceBlock(
                    dream_id=dream_id,
                    date=date(2026, 4, 15),
                    chunk_text="A bridge crossed a dark river.",
                    relevance_score=0.88,
                    matched_fragments=[
                        FragmentMatch(text="bridge", match_type="semantic", char_offset=0)
                    ],
                )
            ]
        )
    )
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(_FakeSession()),
        rag_query_service=rag_query_service,
    )

    result = await facade.search_dreams("bridge river")

    assert result == SearchResult(
        items=[
            type(result.items[0])(
                dream_id=dream_id,
                date=date(2026, 4, 15),
                chunk_text="A bridge crossed a dark river.",
                relevance_score=0.88,
                matched_fragments=[
                    {"text": "bridge", "match_type": "semantic", "char_offset": 0}
                ],
            )
        ]
    )
    rag_query_service.retrieve.assert_awaited_once_with("bridge river")


@pytest.mark.asyncio
async def test_get_dream_returns_plain_dataclass_with_themes() -> None:
    dream_id = uuid4()
    category_id = uuid4()
    theme_id = uuid4()
    created_at = datetime(2026, 4, 15, tzinfo=timezone.utc)
    dream = SimpleNamespace(
        id=dream_id,
        date=date(2026, 4, 14),
        title="Bridge dream",
        raw_text="I crossed a bridge at dusk.",
        word_count=6,
        source_doc_id="doc-123",
        created_at=created_at,
        segmentation_confidence="high",
    )
    theme = SimpleNamespace(
        id=theme_id,
        category_id=category_id,
        salience=0.91,
        status="draft",
        match_type="semantic",
        fragments=[{"text": "bridge"}],
        deprecated=False,
        created_at=created_at,
    )
    session = _FakeSession(
        get_result=dream,
        execute_results=[_FakeResult(rows=[(theme, "Transitions")])],
    )
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    result = await facade.get_dream(dream_id)

    assert result == DreamDetail(
        id=dream_id,
        date="2026-04-14",
        title="Bridge dream",
        raw_text="I crossed a bridge at dusk.",
        word_count=6,
        source_doc_id="doc-123",
        created_at=created_at.isoformat(),
        segmentation_confidence="high",
        themes=[
            type(result.themes[0])(
                id=theme_id,
                category_id=category_id,
                category_name="Transitions",
                salience=0.91,
                status="draft",
                match_type="semantic",
                fragments=[{"text": "bridge"}],
                deprecated=False,
                created_at=created_at.isoformat(),
            )
        ],
    )


def test_assistant_facade_exposes_only_approved_operations() -> None:
    public_methods = {
        name
        for name, value in AssistantFacade.__dict__.items()
        if callable(value) and not name.startswith("_")
    }

    assert public_methods == {
        "search_dreams",
        "get_dream",
        "list_recent_dreams",
        "get_patterns",
        "get_theme_history",
        "trigger_sync",
        "get_dream_motifs",
    }


def test_assistant_facade_does_not_expose_chat_mutation_methods() -> None:
    public_methods = set(AssistantFacade.__dict__)

    assert "confirm_theme" not in public_methods
    assert "reject_theme" not in public_methods
    assert "rollback_theme" not in public_methods
    assert "approve_category" not in public_methods


@pytest.mark.asyncio
async def test_trigger_sync_enqueues_job_and_returns_ref() -> None:
    sync_job_enqueuer = SimpleNamespace(enqueue_ingest=AsyncMock())
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(_FakeSession()),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock(return_value=InsufficientEvidence("x"))),
        sync_job_enqueuer=sync_job_enqueuer,
    )

    result = await facade.trigger_sync("doc-789")

    assert isinstance(result, SyncJobRef)
    assert result.status == "queued"
    assert result.doc_id == "doc-789"
    sync_job_enqueuer.enqueue_ingest.assert_awaited_once_with(
        job_id=result.job_id,
        doc_id="doc-789",
    )


@pytest.mark.asyncio
async def test_get_dream_motifs_returns_frozen_dto_list() -> None:
    """get_dream_motifs returns a list of MotifInductionItem frozen dataclasses (no ORM)."""
    dream_id = uuid4()
    motif_id = uuid4()
    created_at = datetime(2026, 4, 15, tzinfo=timezone.utc)
    motif = SimpleNamespace(
        id=motif_id,
        label="obstructed vertical movement",
        rationale="The dreamer encountered blocked stairs and a locked elevated door.",
        confidence="high",
        status="draft",
        fragments=[{"text": "crumbling stairs", "offset_start": 0, "offset_end": 16}],
        model_version="v1",
        created_at=created_at,
    )
    session = _FakeSession(
        execute_results=[_FakeResult(scalars=[motif])],
    )
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    result = await facade.get_dream_motifs(dream_id)

    assert len(result) == 1
    item = result[0]
    assert isinstance(item, MotifInductionItem)
    assert item.id == motif_id
    assert item.label == "obstructed vertical movement"
    assert item.confidence == "high"
    assert item.status == "draft"
    assert item.model_version == "v1"
    assert item.created_at == created_at.isoformat()
    assert item.fragments == [{"text": "crumbling stairs", "offset_start": 0, "offset_end": 16}]


@pytest.mark.asyncio
async def test_get_dream_motifs_returns_empty_list_when_none_found() -> None:
    dream_id = uuid4()
    session = _FakeSession(
        execute_results=[_FakeResult(scalars=[])],
    )
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    result = await facade.get_dream_motifs(dream_id)

    assert result == []


@pytest.mark.asyncio
async def test_get_dream_motifs_dto_is_frozen() -> None:
    """MotifInductionItem is a frozen dataclass — mutation must raise."""
    dream_id = uuid4()
    motif_id = uuid4()
    created_at = datetime(2026, 4, 15, tzinfo=timezone.utc)
    motif = SimpleNamespace(
        id=motif_id,
        label="dissolution",
        rationale="Things fell apart.",
        confidence="moderate",
        status="draft",
        fragments=[],
        model_version="v1",
        created_at=created_at,
    )
    session = _FakeSession(
        execute_results=[_FakeResult(scalars=[motif])],
    )
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    result = await facade.get_dream_motifs(dream_id)
    item = result[0]

    import dataclasses

    assert dataclasses.is_dataclass(item)
    try:
        item.label = "mutated"  # type: ignore[misc]
        raise AssertionError("Expected FrozenInstanceError")
    except Exception as exc:
        assert "frozen" in type(exc).__name__.lower() or "can't" in str(exc).lower()
