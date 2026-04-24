from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.assistant.facade import (
    AssistantFacade,
    CreatedDreamItem,
    DreamDetail,
    DreamSummary,
    MotifInductionItem,
    SearchResult,
    SyncJobRef,
    _resolve_dream_title,
)
from app.retrieval.query import EvidenceBlock, FragmentMatch, InsufficientEvidence


class _FakeScalars:
    def __init__(self, items):
        self._items = list(items)

    def all(self):
        return list(self._items)


class _FakeResult:
    def __init__(self, *, rows=None, scalars=None, scalar=None):
        self._rows = list(rows or [])
        self._scalars = list(scalars or [])
        self._scalar = scalar

    def all(self):
        return list(self._rows)

    def scalars(self):
        return _FakeScalars(self._scalars)

    def scalar_one_or_none(self):
        return self._scalar


class _FakeSession:
    def __init__(self, *, get_result=None, execute_results=None):
        self._get_result = get_result
        self._execute_results = list(execute_results or [])
        self.executed_statements = []
        self.add = MagicMock()
        self.commit = AsyncMock()
        self.refresh = AsyncMock()

    async def get(self, model, identity):
        del model, identity
        return self._get_result

    async def execute(self, statement):
        self.executed_statements.append(statement)
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
                    title="Bridge dream",
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
                title="Bridge dream",
                chunk_text="A bridge crossed a dark river.",
                relevance_score=0.88,
                matched_fragments=[{"text": "bridge", "match_type": "semantic", "char_offset": 0}],
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


@pytest.mark.asyncio
async def test_list_recent_dreams_returns_preview_and_theme_names() -> None:
    dream_id = uuid4()
    created_at = datetime(2026, 4, 15, tzinfo=timezone.utc)
    dream = SimpleNamespace(
        id=dream_id,
        date=date(2026, 4, 14),
        title="Bridge dream",
        raw_text="I crossed a bridge at dusk. " * 30,
        created_at=created_at,
    )
    session = _FakeSession(
        execute_results=[
            _FakeResult(scalars=[dream]),
            _FakeResult(rows=[(dream_id, "Transitions"), (dream_id, "Water")]),
        ],
    )
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    result = await facade.list_recent_dreams(limit=5)

    assert result == [
        DreamSummary(
            id=dream_id,
            date="2026-04-14",
            title="Bridge dream",
            raw_text_preview=dream.raw_text[:400],
            theme_names=["Transitions", "Water"],
        )
    ]
    theme_statement = str(session.executed_statements[1])
    assert "dream_themes" in theme_statement
    assert "theme_categories" in theme_statement


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
        "create_dream",
        "get_theme_history",
        "trigger_sync",
        "get_archive_source",
        "set_archive_source",
        "list_archive_sources",
        "add_archive_source",
        "remove_archive_source",
        "get_dream_motifs",
        "research_motif_parallels",
    }


def test_assistant_facade_does_not_expose_chat_mutation_methods() -> None:
    public_methods = set(AssistantFacade.__dict__)

    assert "confirm_theme" not in public_methods
    assert "reject_theme" not in public_methods
    assert "rollback_theme" not in public_methods
    assert "approve_category" not in public_methods


@pytest.mark.asyncio
async def test_trigger_sync_enqueues_job_and_returns_refs() -> None:
    sync_job_enqueuer = SimpleNamespace(enqueue_ingest=AsyncMock())
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(_FakeSession()),
        rag_query_service=SimpleNamespace(
            retrieve=AsyncMock(return_value=InsufficientEvidence("x"))
        ),
        sync_job_enqueuer=sync_job_enqueuer,
    )

    result = await facade.trigger_sync("doc-789")

    assert len(result) == 1
    assert isinstance(result[0], SyncJobRef)
    assert result[0].status == "queued"
    assert result[0].doc_id == "doc-789"
    sync_job_enqueuer.enqueue_ingest.assert_awaited_once_with(
        job_id=result[0].job_id,
        doc_id="doc-789",
    )


@pytest.mark.asyncio
async def test_trigger_sync_without_doc_id_enqueues_all_configured_sources() -> None:
    sync_job_enqueuer = SimpleNamespace(enqueue_ingest=AsyncMock())
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(_FakeSession()),
        rag_query_service=SimpleNamespace(
            retrieve=AsyncMock(return_value=InsufficientEvidence("x"))
        ),
        sync_job_enqueuer=sync_job_enqueuer,
    )

    with patch("app.shared.config.get_all_doc_ids", return_value=["doc-a", "doc-b", "doc-c"]):
        result = await facade.trigger_sync()

    assert [ref.doc_id for ref in result] == ["doc-a", "doc-b", "doc-c"]
    assert all(ref.status == "queued" for ref in result)
    assert sync_job_enqueuer.enqueue_ingest.await_count == 3
    assert [call.kwargs["doc_id"] for call in sync_job_enqueuer.enqueue_ingest.await_args_list] == [
        "doc-a",
        "doc-b",
        "doc-c",
    ]


def test_list_archive_sources_returns_all_configured_doc_ids() -> None:
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(_FakeSession()),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    with patch("app.shared.config.get_all_doc_ids", return_value=["doc-a", "doc-b", "doc-c"]):
        result = facade.list_archive_sources()

    assert result == ["doc-a", "doc-b", "doc-c"]


def test_add_archive_source_appends_new_non_primary_doc_id() -> None:
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(_FakeSession()),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    with (
        patch(
            "app.shared.config.get_all_doc_ids",
            side_effect=[["doc-primary", "doc-extra-1"], ["doc-primary", "doc-extra-1", "doc-extra-2"]],
        ),
        patch("app.shared.config.set_google_doc_ids_override") as mock_set_override,
    ):
        result = facade.add_archive_source("doc-extra-2")

    mock_set_override.assert_called_once_with(["doc-extra-1", "doc-extra-2"])
    assert result == ["doc-primary", "doc-extra-1", "doc-extra-2"]


def test_remove_archive_source_removes_non_primary_doc_id() -> None:
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(_FakeSession()),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    with (
        patch("app.shared.config.get_effective_google_doc_id", return_value="doc-primary"),
        patch(
            "app.shared.config.get_all_doc_ids",
            side_effect=[["doc-primary", "doc-extra-1", "doc-extra-2"], ["doc-primary", "doc-extra-2"]],
        ),
        patch("app.shared.config.set_google_doc_ids_override") as mock_set_override,
    ):
        result = facade.remove_archive_source("doc-extra-1")

    mock_set_override.assert_called_once_with(["doc-extra-2"])
    assert result == ["doc-primary", "doc-extra-2"]


def test_remove_archive_source_rejects_primary_doc_id() -> None:
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(_FakeSession()),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    with patch("app.shared.config.get_effective_google_doc_id", return_value="doc-primary"):
        with pytest.raises(ValueError, match="Cannot remove the primary archive source"):
            facade.remove_archive_source("doc-primary")


@pytest.mark.asyncio
async def test_create_dream_persists_entry_and_runs_pipeline() -> None:
    session = _FakeSession(execute_results=[_FakeResult(scalar=None)])
    analysis_service = SimpleNamespace(analyse_dream_with_session_factory=AsyncMock())
    index_dream_callable = AsyncMock(return_value=1)
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        analysis_service=analysis_service,
        index_dream_callable=index_dream_callable,
    )

    result = await facade.create_dream(
        "I was walking through a dark river valley.",
        title="River valley",
        dream_date=date(2026, 4, 21),
        chat_id=42,
    )

    assert isinstance(result, CreatedDreamItem)
    assert result.created is True
    assert result.title == "21.04.26 - River valley"
    assert result.date == "2026-04-21"
    assert result.source_doc_id == "telegram:42"
    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    assert added.raw_text == "I was walking through a dark river valley."
    assert added.word_count == 8
    assert added.parser_profile == "telegram"
    session.commit.assert_awaited_once()
    analysis_service.analyse_dream_with_session_factory.assert_awaited_once_with(
        result.id,
        facade._session_factory,
    )
    index_dream_callable.assert_awaited_once_with(result.id)


def test_resolve_dream_title_without_title_uses_today(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            del tz
            return cls(2026, 4, 23)

    monkeypatch.setattr("app.assistant.facade.datetime", _FrozenDateTime)

    assert _resolve_dream_title("raw text", title=None) == "23.04.26, без названия"


def test_resolve_dream_title_without_title_uses_dream_date() -> None:
    assert (
        _resolve_dream_title("raw text", title=None, dream_date=date(2026, 4, 21))
        == "21.04.26, без названия"
    )


def test_resolve_dream_title_with_title_and_dream_date_prefixes_date() -> None:
    assert (
        _resolve_dream_title(
            "raw text",
            title="River valley",
            dream_date=date(2026, 4, 21),
        )
        == "21.04.26 - River valley"
    )


def test_resolve_dream_title_with_title_and_no_dream_date_returns_title_as_is() -> None:
    assert _resolve_dream_title("raw text", title="River valley") == "River valley"


@pytest.mark.asyncio
async def test_create_dream_returns_existing_entry_without_rerunning_pipeline() -> None:
    existing_id = uuid4()
    created_at = datetime(2026, 4, 21, tzinfo=timezone.utc)
    existing = SimpleNamespace(
        id=existing_id,
        date=date(2026, 4, 20),
        title="Existing dream",
        word_count=5,
        source_doc_id="doc-123",
        created_at=created_at,
    )
    session = _FakeSession(execute_results=[_FakeResult(scalar=existing)])
    analysis_service = SimpleNamespace(analyse_dream_with_session_factory=AsyncMock())
    index_dream_callable = AsyncMock(return_value=1)
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        analysis_service=analysis_service,
        index_dream_callable=index_dream_callable,
    )

    result = await facade.create_dream("Existing dream text", chat_id=7)

    assert result == CreatedDreamItem(
        id=existing_id,
        date="2026-04-20",
        title="Existing dream",
        word_count=5,
        source_doc_id="doc-123",
        created_at=created_at.isoformat(),
        created=False,
    )
    session.add.assert_not_called()
    session.commit.assert_not_awaited()
    analysis_service.analyse_dream_with_session_factory.assert_not_awaited()
    index_dream_callable.assert_not_awaited()


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
async def test_research_motif_parallels_returns_list_of_dicts() -> None:
    motif_id = uuid4()
    created_at = datetime(2026, 4, 17, tzinfo=timezone.utc)
    research_result = SimpleNamespace(
        id=uuid4(),
        motif_id=motif_id,
        dream_id=uuid4(),
        query_label="black river",
        parallels=[
            {
                "domain": "folklore",
                "label": "river as threshold",
                "source_url": "https://example.com/river",
                "relevance_note": "Both frame the river as a liminal crossing.",
                "overlap_degree": "partial",
            }
        ],
        sources=[
            {
                "url": "https://example.com/river",
                "retrieved_at": "2026-04-17T10:00:00+00:00",
            }
        ],
        triggered_by="chat-42",
        created_at=created_at,
    )
    session = _FakeSession()
    research_service = SimpleNamespace(run=AsyncMock(return_value=research_result))
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        research_service=research_service,
    )

    result = await facade.research_motif_parallels(motif_id, triggered_by="chat-42")

    research_service.run.assert_awaited_once_with(motif_id, session, triggered_by="chat-42")
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(research_result)
    assert result == [
        {
            "domain": "folklore",
            "label": "river as threshold",
            "source_url": "https://example.com/river",
            "retrieved_at": "2026-04-17T10:00:00+00:00",
            "relevance_note": "Both frame the river as a liminal crossing.",
            "overlap_degree": "partial",
        }
    ]
    assert all(isinstance(item, dict) for item in result)


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
async def test_get_dream_motifs_excludes_rejected() -> None:
    dream_id = uuid4()
    created_at = datetime(2026, 4, 15, tzinfo=timezone.utc)
    confirmed_motif = SimpleNamespace(
        id=uuid4(),
        label="threshold crossing",
        rationale="A doorway marked a transition.",
        confidence="high",
        status="confirmed",
        fragments=[{"text": "doorway"}],
        model_version="v1",
        created_at=created_at,
    )
    rejected_motif = SimpleNamespace(
        id=uuid4(),
        label="false trail",
        rationale="This row should be excluded.",
        confidence="low",
        status="rejected",
        fragments=[{"text": "trail"}],
        model_version="v1",
        created_at=created_at,
    )

    class _FilteringSession:
        def __init__(self, motifs):
            self._motifs = list(motifs)

        async def execute(self, statement):
            statement_sql = str(statement)
            assert "motif_inductions.status !=" in statement_sql
            return _FakeResult(
                scalars=[motif for motif in self._motifs if motif.status != "rejected"]
            )

    session = _FilteringSession([confirmed_motif, rejected_motif])
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    result = await facade.get_dream_motifs(dream_id)

    assert result == [
        MotifInductionItem(
            id=confirmed_motif.id,
            label="threshold crossing",
            rationale="A doorway marked a transition.",
            confidence="high",
            status="confirmed",
            fragments=[{"text": "doorway"}],
            model_version="v1",
            created_at=created_at.isoformat(),
        )
    ]
    assert all(item.id != rejected_motif.id for item in result)


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
