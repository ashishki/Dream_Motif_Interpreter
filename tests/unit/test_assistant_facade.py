from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.assistant.facade import (
    ArchiveSyncStatus,
    AssistantFacade,
    CreatedDreamItem,
    DREAM_PROCESSING_STAGES,
    NOTE_PROCESSING_STAGES,
    DreamDetail,
    DreamIngressConflictError,
    DreamProcessingLeaseLost,
    DreamProcessingRetryable,
    DreamSummary,
    DreamTitleSearchResult,
    MotifInductionItem,
    NoteProcessingLeaseLost,
    NoteProcessingRetryable,
    SearchResult,
    SearchResultItem,
    SyncJobRef,
    _exact_result_item,
    _extract_quote,
    _resolve_absolute_dream_date,
    _resolve_relative_dream_date,
    _resolve_dream_title,
)
from app.assistant.session import save_recent_dream_set
from app.models.dream import DreamEntry
from app.models.note import DreamNote
from app.models.processing import DreamProcessingJob, NoteProcessingJob
from app.retrieval.query import EvidenceBlock, FragmentMatch, InsufficientEvidence
from app.services.gdocs_client import GDocsWriteError


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
    def __init__(self, *, get_result=None, get_results=None, execute_results=None):
        self._get_result = get_result
        self._get_results = list(get_results or [])
        self._execute_results = list(execute_results or [])
        self.executed_statements = []
        self.add = MagicMock()
        self.add_all = MagicMock(
            # Keep the primary aggregate as the last call for legacy assertions.
            side_effect=lambda items: [self.add(item) for item in reversed(items)]
        )
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.refresh = AsyncMock()

    async def get(self, model, identity, **kwargs):
        del model, identity, kwargs
        if self._get_results:
            return self._get_results.pop(0)
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
                quote="A bridge crossed a dark river",
            )
        ]
    )
    rag_query_service.retrieve.assert_awaited_once_with("bridge river")


def test_extract_quote_finds_matching_russian_sentence() -> None:
    chunk_text = "Сначала я шел по лесу. Потом увидел церковь на холме! После этого начался дождь."

    assert _extract_quote(chunk_text, "церковь") == "Потом увидел церковь на холме"


def test_exact_result_item_sets_quote_field() -> None:
    dream_id = uuid4()

    result = _exact_result_item(
        {
            "dream_id": dream_id,
            "date": date(2026, 4, 15),
            "title": "Холм",
            "chunk_text": "Сначала я шел по лесу. Потом увидел церковь на холме.",
        },
        "церковь",
    )

    assert result == SearchResultItem(
        dream_id=dream_id,
        date=date(2026, 4, 15),
        title="Холм",
        chunk_text="Сначала я шел по лесу. Потом увидел церковь на холме.",
        relevance_score=1.0,
        matched_fragments=[],
        quote="Потом увидел церковь на холме",
    )


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
        execute_results=[
            _FakeResult(rows=[(theme, "Transitions")]),
            _FakeResult(scalars=[]),
        ],
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
        notes=[],
    )


@pytest.mark.asyncio
async def test_get_dream_includes_notes() -> None:
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
        execute_results=[
            _FakeResult(rows=[(theme, "Transitions")]),
            _FakeResult(scalars=["note text"]),
        ],
    )
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    result = await facade.get_dream(dream_id)

    assert result is not None
    assert result.notes == ["note text"]


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


@pytest.mark.asyncio
async def test_search_dreams_by_title_returns_title_matches() -> None:
    dream_id = uuid4()
    created_at = datetime(2026, 4, 15, tzinfo=timezone.utc)
    dream = SimpleNamespace(
        id=dream_id,
        date=date(2026, 4, 14),
        title="Я и дети. Тайное общество",
        raw_text="Я была с детьми и мы нашли тайное общество. " * 20,
        created_at=created_at,
    )
    session = _FakeSession(execute_results=[_FakeResult(scalars=[dream])])
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    result = await facade.search_dreams_by_title("я и дети тайное общество", limit=5)

    assert result == [
        DreamTitleSearchResult(
            dream_id=dream_id,
            date="2026-04-14",
            title="Я и дети. Тайное общество",
            raw_text_preview=dream.raw_text[:400],
        )
    ]
    statement = str(session.executed_statements[0])
    assert "dream_entries.title" in statement
    assert "dream_chunks" not in statement


@pytest.mark.asyncio
async def test_search_dreams_by_title_can_filter_by_date() -> None:
    dream_id = uuid4()
    dream = SimpleNamespace(
        id=dream_id,
        date=date(2026, 4, 4),
        title="Кирилл, мужик, настольки",
        raw_text="Полный текст сна.",
        created_at=datetime(2026, 4, 4, tzinfo=timezone.utc),
    )
    session = _FakeSession(execute_results=[_FakeResult(scalars=[dream])])
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    result = await facade.search_dreams_by_title(
        "Кирилл, мужик, настольки",
        limit=5,
        dream_date=date(2026, 4, 4),
    )

    assert result == [
        DreamTitleSearchResult(
            dream_id=dream_id,
            date="2026-04-04",
            title="Кирилл, мужик, настольки",
            raw_text_preview="Полный текст сна.",
        )
    ]
    statement = str(session.executed_statements[0])
    assert "dream_entries.date" in statement


def test_assistant_facade_exposes_only_approved_operations() -> None:
    public_methods = {
        name
        for name, value in AssistantFacade.__dict__.items()
        if callable(value) and not name.startswith("_")
    }

    assert public_methods == {
        "search_dreams",
        "shutdown",
        "start_background_workers",
        "search_dreams_exact",
        "search_dreams_by_title",
        "get_dream",
        "list_recent_dreams",
        "get_patterns",
        "create_dream",
        "process_dream_processing_job",
        "retry_dream_processing",
        "add_dream_note",
        "process_note_processing_job",
        "retry_note_processing",
        "write_dream_to_google_doc",
        "retry_write_to_google_doc",
        "get_theme_history",
        "trigger_sync",
        "get_sync_status",
        "create_archive_source_document",
        "search_archive_source_by_title",
        "get_archive_source",
        "get_archive_source_name",
        "set_archive_source",
        "list_archive_sources",
        "add_archive_source",
        "remove_archive_source",
        "get_dream_motifs",
        "research_motif_parallels",
        "prepare_dream_interpretation_request",
        "interpret_dream_with_prompt",
    }


def test_assistant_facade_does_not_expose_chat_mutation_methods() -> None:
    public_methods = set(AssistantFacade.__dict__)

    assert "confirm_theme" not in public_methods
    assert "reject_theme" not in public_methods
    assert "rollback_theme" not in public_methods
    assert "approve_category" not in public_methods


@pytest.mark.asyncio
async def test_facade_shutdown_awaits_owned_sync_enqueuer_only() -> None:
    enqueuer = SimpleNamespace(shutdown=AsyncMock())
    session_factory = _FakeSessionFactory(_FakeSession())
    facade = AssistantFacade(
        session_factory=session_factory,
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        sync_job_enqueuer=enqueuer,
    )

    await facade.shutdown()

    enqueuer.shutdown.assert_awaited_once()


@pytest.mark.asyncio
async def test_facade_start_background_workers_awaits_owned_sync_enqueuer() -> None:
    enqueuer = SimpleNamespace(start=AsyncMock())
    session_factory = _FakeSessionFactory(_FakeSession())
    facade = AssistantFacade(
        session_factory=session_factory,
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        sync_job_enqueuer=enqueuer,
    )

    await facade.start_background_workers()

    enqueuer.start.assert_awaited_once()


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
        chat_id=None,
    )


@pytest.mark.asyncio
async def test_trigger_sync_passes_chat_id_to_enqueuer() -> None:
    sync_job_enqueuer = SimpleNamespace(enqueue_ingest=AsyncMock())
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(_FakeSession()),
        rag_query_service=SimpleNamespace(
            retrieve=AsyncMock(return_value=InsufficientEvidence("x"))
        ),
        sync_job_enqueuer=sync_job_enqueuer,
    )

    result = await facade.trigger_sync("doc-789", chat_id=12345)

    assert len(result) == 1
    sync_job_enqueuer.enqueue_ingest.assert_awaited_once_with(
        job_id=result[0].job_id,
        doc_id="doc-789",
        chat_id=12345,
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
    assert [
        call.kwargs["chat_id"] for call in sync_job_enqueuer.enqueue_ingest.await_args_list
    ] == [
        None,
        None,
        None,
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
            side_effect=[
                ["doc-primary", "doc-extra-1"],
                ["doc-primary", "doc-extra-1", "doc-extra-2"],
            ],
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
            side_effect=[
                ["doc-primary", "doc-extra-1", "doc-extra-2"],
                ["doc-primary", "doc-extra-2"],
            ],
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
async def test_create_dream_persists_entry_and_pending_job_without_external_calls() -> None:
    session = _FakeSession(execute_results=[_FakeResult(scalar=None)])
    analysis_service = SimpleNamespace(analyse_dream_with_session_factory=AsyncMock())
    index_dream_callable = AsyncMock(return_value=1)
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        analysis_service=analysis_service,
        index_dream_callable=index_dream_callable,
        title_llm_client=SimpleNamespace(complete=AsyncMock(return_value="Мост у моря")),
    )

    with patch.object(
        facade, "write_dream_to_google_doc", AsyncMock(return_value=(True, "Сны"))
    ) as mock_write:
        result = await facade.create_dream(
            "I was walking through a dark river valley.",
            title="River valley",
            dream_date=date(2026, 4, 21),
            chat_id=42,
        )

    assert isinstance(result, CreatedDreamItem)
    assert result.created is True
    assert result.title == "River valley"
    assert result.date == "2026-04-21"
    assert result.source_doc_id == "telegram:42"
    assert result.written_to_google_doc is False
    assert result.semantic_index_status == "pending"
    assert result.processing_status == "pending"
    assert result.google_doc_write_status == "pending"
    assert result.processing_job_id is not None
    added_rows = [call.args[0] for call in session.add.call_args_list]
    added = next(row for row in added_rows if isinstance(row, DreamEntry))
    jobs = [row for row in added_rows if isinstance(row, DreamProcessingJob)]
    assert added.raw_text == "I was walking through a dark river valley."
    assert added.word_count == 8
    assert added.parser_profile == "telegram"
    session.commit.assert_awaited_once()
    assert {job.dream_id for job in jobs} == {result.id}
    assert {job.stage for job in jobs} == set(DREAM_PROCESSING_STAGES)
    assert {job.status for job in jobs} == {"pending"}
    assert result.processing_job_ids == tuple(
        next(job.id for job in jobs if job.stage == stage) for stage in DREAM_PROCESSING_STAGES
    )
    analysis_service.analyse_dream_with_session_factory.assert_not_awaited()
    index_dream_callable.assert_not_awaited()
    mock_write.assert_not_awaited()


@pytest.mark.asyncio
async def test_repeated_text_from_distinct_ingress_events_creates_distinct_dreams() -> None:
    sessions = [
        _FakeSession(execute_results=[_FakeResult(scalar=None)]),
        _FakeSession(execute_results=[_FakeResult(scalar=None)]),
    ]
    results: list[CreatedDreamItem] = []
    for message_id, session in enumerate(sessions, start=10):
        facade = AssistantFacade(
            session_factory=_FakeSessionFactory(session),
            rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        )
        results.append(
            await facade.create_dream(
                "The same legitimate dream happened again.",
                chat_id=42,
                source_event_key=f"telegram:42:message:{message_id}",
            )
        )

    dreams = [
        next(
            call.args[0]
            for call in session.add.call_args_list
            if isinstance(call.args[0], DreamEntry)
        )
        for session in sessions
    ]
    assert all(result.created for result in results)
    assert results[0].id != results[1].id
    assert dreams[0].content_hash == dreams[1].content_hash
    assert dreams[0].source_event_key != dreams[1].source_event_key


@pytest.mark.asyncio
async def test_create_dream_does_not_call_indexing_in_capture_transaction() -> None:
    session = _FakeSession(execute_results=[_FakeResult(scalar=None), _FakeResult(scalar=None)])
    analysis_service = SimpleNamespace(analyse_dream_with_session_factory=AsyncMock())
    index_dream_callable = AsyncMock(side_effect=RuntimeError("OpenAI 429"))
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        analysis_service=analysis_service,
        index_dream_callable=index_dream_callable,
        title_llm_client=SimpleNamespace(complete=AsyncMock(return_value="Мост у моря")),
    )

    with patch.object(
        facade,
        "write_dream_to_google_doc",
        AsyncMock(return_value=(True, "Сны")),
    ) as mock_write:
        result = await facade.create_dream(
            "Мне приснилось, что я перехожу мост через море.",
            chat_id=42,
        )

    assert result.created is True
    assert result.semantic_index_status == "pending"
    assert result.processing_status == "pending"
    mock_write.assert_not_awaited()
    analysis_service.analyse_dream_with_session_factory.assert_not_awaited()
    index_dream_callable.assert_not_awaited()
    assert session.executed_statements == []
    assert session.commit.await_count == 1


@pytest.mark.asyncio
async def test_create_dream_defaults_date_and_title_deterministically() -> None:
    session = _FakeSession(execute_results=[_FakeResult(scalar=None)])
    analysis_service = SimpleNamespace(analyse_dream_with_session_factory=AsyncMock())
    index_dream_callable = AsyncMock(return_value=1)
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        analysis_service=analysis_service,
        index_dream_callable=index_dream_callable,
        title_llm_client=SimpleNamespace(complete=AsyncMock(return_value="Мост у моря")),
    )

    with (
        patch("app.assistant.facade._application_today", return_value=date(2026, 5, 1)),
        patch.object(facade, "write_dream_to_google_doc", AsyncMock(return_value=(True, "Сны"))),
    ):
        result = await facade.create_dream(
            "вчера мне приснилось море мост башня",
            chat_id=42,
        )

    assert result.date == "2026-04-30"
    assert result.title == "Море мост башня"
    added = session.add.call_args[0][0]
    assert added.date == date(2026, 4, 30)
    assert added.title == "Море мост башня"


@pytest.mark.asyncio
async def test_create_dream_does_not_take_date_words_from_story_body() -> None:
    session = _FakeSession(execute_results=[_FakeResult(scalar=None)])
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        analysis_service=SimpleNamespace(analyse_dream_with_session_factory=AsyncMock()),
        index_dream_callable=AsyncMock(return_value=1),
        title_llm_client=SimpleNamespace(complete=AsyncMock(return_value="Старый календарь")),
    )

    with patch("app.assistant.facade._application_today", return_value=date(2026, 8, 30)):
        result = await facade.create_dream(
            "Мне приснилось, что вчера во сне я нашёл календарь с датой 19.05.",
            chat_id=42,
        )

    added = session.add.call_args[0][0]
    assert result.date == "2026-08-30"
    assert added.date == date(2026, 8, 30)
    assert "вчера" in added.raw_text
    assert "19.05" in added.raw_text


@pytest.mark.asyncio
async def test_create_dream_extracts_inline_title_and_strips_record_command() -> None:
    session = _FakeSession(execute_results=[_FakeResult(scalar=None)])
    analysis_service = SimpleNamespace(analyse_dream_with_session_factory=AsyncMock())
    index_dream_callable = AsyncMock(return_value=1)
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        analysis_service=analysis_service,
        index_dream_callable=index_dream_callable,
        title_llm_client=SimpleNamespace(complete=AsyncMock(return_value="ignored")),
    )

    with (
        patch("app.assistant.facade._application_today", return_value=date(2026, 5, 1)),
        patch.object(facade, "write_dream_to_google_doc", AsyncMock(return_value=(True, "Сны"))),
    ):
        result = await facade.create_dream(
            "Запиши сон. Название — Пирог с фруктовой начинкой. "
            "Мне приснилось, что я пеку пирог на даче.",
            title="о запиши название пирог",
            chat_id=42,
        )

    assert result.title == "Пирог с фруктовой начинкой"
    added = session.add.call_args[0][0]
    assert added.raw_text == "Мне приснилось, что я пеку пирог на даче."
    assert added.title == "Пирог с фруктовой начинкой"


@pytest.mark.asyncio
async def test_create_dream_strips_text_record_command_word() -> None:
    session = _FakeSession(execute_results=[_FakeResult(scalar=None)])
    analysis_service = SimpleNamespace(analyse_dream_with_session_factory=AsyncMock())
    index_dream_callable = AsyncMock(return_value=1)
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        analysis_service=analysis_service,
        index_dream_callable=index_dream_callable,
        title_llm_client=SimpleNamespace(complete=AsyncMock(return_value="Поиск друзей")),
    )

    with (
        patch("app.assistant.facade._application_today", return_value=date(2026, 5, 1)),
        patch.object(facade, "write_dream_to_google_doc", AsyncMock(return_value=(True, "Сны"))),
    ):
        await facade.create_dream(
            "Можешь записать сон текстом. Сегодня мне приснилось, что я ищу друзей.",
            chat_id=42,
        )

    added = session.add.call_args[0][0]
    assert added.raw_text == "мне приснилось, что я ищу друзей."


@pytest.mark.asyncio
async def test_create_dream_extracts_short_date_directive() -> None:
    session = _FakeSession(execute_results=[_FakeResult(scalar=None)])
    analysis_service = SimpleNamespace(analyse_dream_with_session_factory=AsyncMock())
    index_dream_callable = AsyncMock(return_value=1)
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        analysis_service=analysis_service,
        index_dream_callable=index_dream_callable,
        title_llm_client=SimpleNamespace(complete=AsyncMock(return_value="Река в доме")),
    )

    with (
        patch("app.assistant.facade._application_today", return_value=date(2026, 5, 20)),
        patch.object(facade, "write_dream_to_google_doc", AsyncMock(return_value=(True, "Сны"))),
    ):
        result = await facade.create_dream(
            "Запиши сон за 19.05: Мне приснилась река в доме.",
            chat_id=42,
        )

    assert result.date == "2026-05-19"
    added = session.add.call_args[0][0]
    assert added.date == date(2026, 5, 19)
    assert added.raw_text == "Мне приснилась река в доме."


@pytest.mark.asyncio
async def test_create_dream_extracts_bare_leading_date_from_old_dream_text() -> None:
    session = _FakeSession(execute_results=[_FakeResult(scalar=None)])
    analysis_service = SimpleNamespace(analyse_dream_with_session_factory=AsyncMock())
    index_dream_callable = AsyncMock(return_value=1)
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        analysis_service=analysis_service,
        index_dream_callable=index_dream_callable,
        title_llm_client=SimpleNamespace(complete=AsyncMock(return_value="Старый мост")),
    )

    with (
        patch("app.assistant.facade._application_today", return_value=date(2026, 6, 8)),
        patch.object(facade, "write_dream_to_google_doc", AsyncMock(return_value=(True, "Сны"))),
    ):
        result = await facade.create_dream(
            "Запиши старый сон 05.06.25: Мне приснилось, что я возвращаюсь к старому мосту.",
            chat_id=42,
        )

    added = session.add.call_args[0][0]
    assert result.date == "2025-06-05"
    assert added.date == date(2025, 6, 5)
    assert added.raw_text == "Мне приснилось, что я возвращаюсь к старому мосту."


@pytest.mark.asyncio
async def test_create_dream_extracts_labeled_date_from_old_dream_text() -> None:
    session = _FakeSession(execute_results=[_FakeResult(scalar=None)])
    analysis_service = SimpleNamespace(analyse_dream_with_session_factory=AsyncMock())
    index_dream_callable = AsyncMock(return_value=1)
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        analysis_service=analysis_service,
        index_dream_callable=index_dream_callable,
        title_llm_client=SimpleNamespace(complete=AsyncMock(return_value="Старый мост")),
    )

    with (
        patch("app.assistant.facade._application_today", return_value=date(2026, 6, 8)),
        patch.object(facade, "write_dream_to_google_doc", AsyncMock(return_value=(True, "Сны"))),
    ):
        result = await facade.create_dream(
            "Запиши старый сон. Дата: 05.06.25. Мне приснилось, что я возвращаюсь к старому мосту.",
            chat_id=42,
        )

    added = session.add.call_args[0][0]
    assert result.date == "2025-06-05"
    assert added.date == date(2025, 6, 5)
    assert added.raw_text == "Мне приснилось, что я возвращаюсь к старому мосту."


@pytest.mark.asyncio
async def test_create_dream_removes_technical_relative_date_phrase_from_text() -> None:
    session = _FakeSession(execute_results=[_FakeResult(scalar=None)])
    analysis_service = SimpleNamespace(analyse_dream_with_session_factory=AsyncMock())
    index_dream_callable = AsyncMock(return_value=1)
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        analysis_service=analysis_service,
        index_dream_callable=index_dream_callable,
        title_llm_client=SimpleNamespace(complete=AsyncMock(return_value="Мост")),
    )

    with (
        patch("app.assistant.facade._application_today", return_value=date(2026, 7, 12)),
        patch.object(facade, "write_dream_to_google_doc", AsyncMock(return_value=(True, "Сны"))),
    ):
        result = await facade.create_dream(
            "Запиши сон: он мне приснился вчера. Я шел по мосту над морем.",
            chat_id=42,
        )

    added = session.add.call_args[0][0]
    assert result.date == "2026-07-11"
    assert added.raw_text == "Я шел по мосту над морем."


@pytest.mark.asyncio
async def test_create_dream_extracts_title_after_name_it_command_and_removes_command() -> None:
    session = _FakeSession(execute_results=[_FakeResult(scalar=None)])
    analysis_service = SimpleNamespace(analyse_dream_with_session_factory=AsyncMock())
    index_dream_callable = AsyncMock(return_value=1)
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        analysis_service=analysis_service,
        index_dream_callable=index_dream_callable,
        title_llm_client=SimpleNamespace(complete=AsyncMock(return_value="ignored")),
    )

    with (
        patch("app.assistant.facade._application_today", return_value=date(2026, 7, 12)),
        patch.object(facade, "write_dream_to_google_doc", AsyncMock(return_value=(True, "Сны"))),
    ):
        result = await facade.create_dream(
            "Запиши сон: назови его Рыба в воде, мне приснилось прозрачное озеро.",
            chat_id=42,
        )

    added = session.add.call_args[0][0]
    assert result.title == "Рыба в воде"
    assert added.title == "Рыба в воде"
    assert added.raw_text == "мне приснилось прозрачное озеро."


@pytest.mark.asyncio
async def test_create_dream_generated_title_ignores_record_command_words() -> None:
    session = _FakeSession(execute_results=[_FakeResult(scalar=None)])
    analysis_service = SimpleNamespace(analyse_dream_with_session_factory=AsyncMock())
    index_dream_callable = AsyncMock(return_value=1)
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        analysis_service=analysis_service,
        index_dream_callable=index_dream_callable,
        title_llm_client=SimpleNamespace(complete=AsyncMock(return_value="Башня и мост")),
    )

    with (
        patch("app.assistant.facade._application_today", return_value=date(2026, 5, 1)),
        patch.object(facade, "write_dream_to_google_doc", AsyncMock(return_value=(True, "Сны"))),
    ):
        result = await facade.create_dream(
            "Сохрани сон: вчера мне приснилось море мост башня",
            chat_id=42,
        )

    assert result.title == "Море мост башня"
    facade._title_llm_client.complete.assert_not_awaited()
    added = session.add.call_args[0][0]
    assert added.raw_text == "мне приснилось море мост башня"


@pytest.mark.asyncio
async def test_create_dream_does_not_call_title_llm() -> None:
    session = _FakeSession(execute_results=[_FakeResult(scalar=None)])
    analysis_service = SimpleNamespace(analyse_dream_with_session_factory=AsyncMock())
    index_dream_callable = AsyncMock(return_value=1)
    title_llm_client = SimpleNamespace(complete=AsyncMock(side_effect=RuntimeError("down")))
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        analysis_service=analysis_service,
        index_dream_callable=index_dream_callable,
        title_llm_client=title_llm_client,
    )

    with (
        patch("app.assistant.facade._application_today", return_value=date(2026, 5, 1)),
        patch.object(facade, "write_dream_to_google_doc", AsyncMock(return_value=(True, "Сны"))),
    ):
        result = await facade.create_dream(
            "Сохрани сон: вчера мне приснилось море мост башня",
            chat_id=42,
        )

    assert result.title == "Море мост башня"
    title_llm_client.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_add_dream_note_atomically_queues_two_jobs_without_external_work() -> None:
    dream_id = uuid4()
    dream = SimpleNamespace(
        id=dream_id,
        source_doc_id="doc-123",
        date=date(2026, 4, 21),
        title="River valley",
        created_at=datetime(2026, 4, 21, tzinfo=timezone.utc),
    )
    session = _FakeSession(execute_results=[_FakeResult(scalar=dream), _FakeResult(scalar=None)])
    index_note_callable = AsyncMock(return_value=1)
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        index_note_callable=index_note_callable,
    )

    with patch("app.assistant.facade.GDocsClient") as mock_client_cls:
        success, message = await facade.add_dream_note("remember the red door", chat_id=42)

    assert success is True
    assert message == "Заметка сохранена. Семантический индекс и Google Doc обновятся в фоне."
    added = [call.args[0] for call in session.add.call_args_list]
    notes = [item for item in added if isinstance(item, DreamNote)]
    jobs = [item for item in added if isinstance(item, NoteProcessingJob)]
    assert len(notes) == 1
    assert {job.stage for job in jobs} == set(NOTE_PROCESSING_STAGES)
    assert next(job for job in jobs if job.stage == "gdocs").target_doc_id == "doc-123"
    assert all(job.note_id == notes[0].id for job in jobs)
    session.commit.assert_awaited_once()
    index_note_callable.assert_not_awaited()
    mock_client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_existing_legacy_note_queues_only_safe_index_repair() -> None:
    dream = SimpleNamespace(
        id=uuid4(),
        source_doc_id="doc-123",
        date=date(2026, 4, 21),
        title="River valley",
    )
    existing_note = DreamNote(
        id=uuid4(),
        dream_id=dream.id,
        text="remember the red door",
        content_hash="a" * 64,
        source="telegram",
        created_at=datetime(2026, 4, 21, tzinfo=timezone.utc),
    )
    session = _FakeSession(
        execute_results=[
            _FakeResult(scalar=dream),
            _FakeResult(scalar=existing_note),
            _FakeResult(scalar=None),
            _FakeResult(scalar=None),
        ]
    )
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    success, message = await facade.add_dream_note("remember the red door", chat_id=42)

    assert success is True
    assert "уже сохранена" in message
    added = [call.args[0] for call in session.add.call_args_list]
    assert len(added) == 1
    assert isinstance(added[0], NoteProcessingJob)
    assert added[0].stage == "index"
    assert added[0].target_doc_id is None
    session.commit.assert_awaited_once()


@pytest.mark.parametrize(
    ("index_status", "gdocs_status", "expected_message"),
    [
        (
            "succeeded",
            None,
            "Заметка уже сохранена; семантический индекс готов; состояние доставки "
            "в Google Docs неизвестно, поэтому автоматически её не повторяю.",
        ),
        (
            "succeeded",
            "failed",
            "Заметка уже сохранена; семантический индекс готов; доставка в Google Docs "
            "требует явного повтора.",
        ),
        (
            "succeeded",
            "pending",
            "Заметка уже сохранена; семантический индекс готов; обновление Google Docs "
            "стоит в очереди.",
        ),
        (
            "succeeded",
            "succeeded",
            "Заметка уже сохранена; семантический индекс готов; запись в Google Docs подтверждена.",
        ),
        (
            "failed",
            "succeeded",
            "Заметка уже сохранена; семантический индекс требует явного повтора; "
            "запись в Google Docs подтверждена.",
        ),
    ],
)
@pytest.mark.asyncio
async def test_existing_note_ack_aggregates_both_jobs_without_reset(
    index_status: str,
    gdocs_status: str | None,
    expected_message: str,
) -> None:
    dream = SimpleNamespace(id=uuid4(), source_doc_id="doc-123")
    existing_note = DreamNote(
        id=uuid4(),
        dream_id=dream.id,
        text="same note",
        content_hash="a" * 64,
        source="telegram",
        created_at=datetime(2026, 4, 21, tzinfo=timezone.utc),
    )
    existing_job = SimpleNamespace(
        id=uuid4(),
        note_id=existing_note.id,
        stage="index",
        status=index_status,
    )
    gdocs_job = (
        SimpleNamespace(
            id=uuid4(),
            note_id=existing_note.id,
            stage="gdocs",
            status=gdocs_status,
        )
        if gdocs_status is not None
        else None
    )
    session = _FakeSession(
        execute_results=[
            _FakeResult(scalar=dream),
            _FakeResult(scalar=existing_note),
            _FakeResult(scalar=existing_job),
            _FakeResult(scalar=gdocs_job),
        ]
    )
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    success, message = await facade.add_dream_note("same note", chat_id=42)

    assert success is True
    assert message == expected_message
    assert existing_job.status == index_status
    if gdocs_job is not None:
        assert gdocs_job.status == gdocs_status
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_note_uniqueness_race_repairs_only_safe_index_stage() -> None:
    dream = SimpleNamespace(
        id=uuid4(),
        source_doc_id="doc-123",
        date=date(2026, 4, 21),
        title="River valley",
    )
    winner = DreamNote(
        id=uuid4(),
        dream_id=dream.id,
        text="remember the red door",
        content_hash="a" * 64,
        source="telegram",
        created_at=datetime(2026, 4, 21, tzinfo=timezone.utc),
    )
    session = _FakeSession(
        execute_results=[
            _FakeResult(scalar=dream),
            _FakeResult(scalar=None),
            _FakeResult(scalar=winner),
            _FakeResult(scalar=None),
            _FakeResult(scalar=None),
        ]
    )
    session.commit.side_effect = [
        IntegrityError("insert", {}, RuntimeError("unique")),
        None,
    ]
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    success, message = await facade.add_dream_note("remember the red door", chat_id=42)

    assert success is True
    assert "уже сохранена" in message
    session.rollback.assert_awaited_once()
    safe_repair = session.add.call_args_list[-1].args[0]
    assert isinstance(safe_repair, NoteProcessingJob)
    assert safe_repair.stage == "index"
    assert safe_repair.note_id == winner.id


@pytest.mark.asyncio
async def test_process_note_gdocs_uses_snapshot_marker_and_created_date() -> None:
    note_id = uuid4()
    lock_token = uuid4()
    job = SimpleNamespace(
        id=uuid4(),
        note_id=note_id,
        stage="gdocs",
        status="running",
        lock_token=lock_token,
        target_doc_id="snapshot-doc",
    )
    note = SimpleNamespace(
        id=note_id,
        dream_id=uuid4(),
        text="remember the red door",
        created_at=datetime(2026, 4, 21, 23, 59, tzinfo=timezone.utc),
    )
    dream = SimpleNamespace(
        id=note.dream_id,
        date=date(2026, 4, 21),
        title="River valley",
    )
    session = _FakeSession(get_results=[job, note, dream])
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    with patch("app.assistant.facade.GDocsClient") as mock_client_cls:
        mock_client_cls.return_value.insert_text_under_heading = MagicMock(return_value=True)
        await facade.process_note_processing_job(job.id, lock_token=lock_token)

    call = mock_client_cls.return_value.insert_text_under_heading.call_args
    assert call.args == ("snapshot-doc",)
    assert call.kwargs == {
        "heading": "21.04.26 - River valley",
        "text": "[Note 21.04.26]: remember the red door",
        "idempotency_key": f"note:{note_id}",
    }


@pytest.mark.asyncio
async def test_process_note_gdocs_missing_heading_stays_retryable() -> None:
    note_id = uuid4()
    job = SimpleNamespace(
        id=uuid4(),
        note_id=note_id,
        stage="gdocs",
        status="running",
        lock_token=uuid4(),
        target_doc_id="snapshot-doc",
    )
    note = SimpleNamespace(
        id=note_id,
        dream_id=uuid4(),
        text="note",
        created_at=datetime(2026, 4, 21, tzinfo=timezone.utc),
    )
    dream = SimpleNamespace(id=note.dream_id, date=None, title="Dream title")
    session = _FakeSession(get_results=[job, note, dream])
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    with patch("app.assistant.facade.GDocsClient") as mock_client_cls:
        mock_client_cls.return_value.insert_text_under_heading = MagicMock(return_value=False)
        with pytest.raises(NoteProcessingRetryable, match="not present"):
            await facade.process_note_processing_job(job.id, lock_token=job.lock_token)


@pytest.mark.asyncio
async def test_process_note_rejects_stale_lease_before_side_effect() -> None:
    job = SimpleNamespace(
        id=uuid4(),
        note_id=uuid4(),
        stage="index",
        status="running",
        lock_token=uuid4(),
        target_doc_id=None,
    )
    index_note_callable = AsyncMock()
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(_FakeSession(get_result=job)),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        index_note_callable=index_note_callable,
    )

    with pytest.raises(NoteProcessingLeaseLost, match="no longer owned"):
        await facade.process_note_processing_job(job.id, lock_token=uuid4())

    index_note_callable.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_note_retry_resets_failed_stage_only() -> None:
    failed = SimpleNamespace(
        id=uuid4(),
        note_id=uuid4(),
        stage="gdocs",
        status="failed",
        attempt_count=5,
        last_error="heading missing",
        available_at=datetime.now(timezone.utc),
        locked_at=datetime.now(timezone.utc),
        lock_token=uuid4(),
        updated_at=datetime.now(timezone.utc),
    )
    session = _FakeSession(execute_results=[_FakeResult(scalars=[failed])])
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    retried = await facade.retry_note_processing(failed.note_id, stages=("gdocs",))

    assert retried == (failed.id,)
    assert failed.status == "retryable"
    assert failed.attempt_count == 0
    assert failed.last_error is None
    assert failed.lock_token is None
    assert "failed" in session.executed_statements[0].compile().params.values()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_add_dream_note_without_id_targets_latest_archive_dream() -> None:
    dream = SimpleNamespace(
        id=uuid4(),
        source_doc_id="doc-123",
        date=date(2026, 5, 3),
        title="Manual Google Doc dream",
        created_at=datetime(2026, 5, 4, tzinfo=timezone.utc),
    )
    session = _FakeSession(execute_results=[_FakeResult(scalar=dream), _FakeResult(scalar=None)])
    index_note_callable = AsyncMock(return_value=1)
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        index_note_callable=index_note_callable,
    )

    with patch("app.assistant.facade.GDocsClient") as mock_client_cls:
        mock_client_cls.return_value.insert_text_under_heading = MagicMock(return_value=True)

        success, _message = await facade.add_dream_note(
            "после пробуждения было тревожно",
            chat_id=42,
        )

    assert success is True
    statement_sql = str(session.executed_statements[0].compile())
    assert " WHERE " not in statement_sql
    assert "ORDER BY dream_entries.date DESC NULLS LAST" in statement_sql
    note = session.add.call_args[0][0]
    assert note.dream_id == dream.id
    index_note_callable.assert_not_awaited()
    mock_client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_add_dream_note_without_id_targets_single_recent_search_result() -> None:
    chat_id = 909001
    dream = SimpleNamespace(
        id=uuid4(),
        source_doc_id="doc-123",
        date=date(2026, 5, 3),
        title="Specific dream",
        created_at=datetime(2026, 5, 4, tzinfo=timezone.utc),
    )
    save_recent_dream_set(chat_id, query="specific", dream_ids=[str(dream.id)])
    session = _FakeSession(get_result=dream, execute_results=[_FakeResult(scalar=None)])
    index_note_callable = AsyncMock(return_value=1)
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        index_note_callable=index_note_callable,
    )

    with patch("app.assistant.facade.GDocsClient") as mock_client_cls:
        mock_client_cls.return_value.insert_text_under_heading = MagicMock(return_value=True)
        success, _message = await facade.add_dream_note("важная заметка", chat_id=chat_id)

    assert success is True
    note = session.add.call_args[0][0]
    assert note.dream_id == dream.id
    assert len(session.executed_statements) == 1
    assert "dream_notes" in str(session.executed_statements[0])


@pytest.mark.asyncio
async def test_prepare_dream_interpretation_request_uses_latest_dream_when_id_omitted() -> None:
    dream_id = uuid4()
    dream = SimpleNamespace(
        id=dream_id,
        source_doc_id="doc-123",
        date=date(2026, 5, 3),
        title="Запретная рыба",
        raw_text="Рыба черного цвета, она очень красивая.",
        created_at=datetime(2026, 5, 4, tzinfo=timezone.utc),
    )
    session = _FakeSession(execute_results=[_FakeResult(scalar=dream)])
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    request = await facade.prepare_dream_interpretation_request(
        user_request="что значит рыба?",
        chat_id=42,
    )

    assert request is not None
    assert request.dream_id == dream_id
    assert request.title == "Запретная рыба"
    assert "что значит рыба?" in request.prompt
    assert "Рыба черного цвета" in request.prompt


@pytest.mark.asyncio
async def test_interpret_dream_with_prompt_calls_llm_client() -> None:
    dream_id = uuid4()
    dream = SimpleNamespace(
        id=dream_id,
        title="Запретная рыба",
    )
    session = _FakeSession(get_result=dream)
    llm_client = SimpleNamespace(complete=AsyncMock(return_value="Осторожная интерпретация."))
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        interpretation_llm_client=llm_client,
    )

    result = await facade.interpret_dream_with_prompt(
        dream_id=dream_id,
        prompt="approved prompt",
    )

    assert result is not None
    assert result.title == "Запретная рыба"
    assert result.text == "Осторожная интерпретация."
    llm_client.complete.assert_awaited_once()
    assert llm_client.complete.call_args.args[1] == "approved prompt"


@pytest.mark.asyncio
async def test_get_sync_status_reads_auto_sync_state_from_enqueuer() -> None:
    class _Enqueuer:
        async def get_auto_sync_status(self, doc_id: str) -> object:
            assert doc_id == "doc-123"
            return SimpleNamespace(
                last_sync_status="synced",
                last_checked_at="2026-05-06T10:00:00+00:00",
                last_sync_started_at=None,
                last_synced_at="2026-05-06T09:59:00+00:00",
                last_sync_job_id="job-1",
            )

    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(_FakeSession()),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        sync_job_enqueuer=_Enqueuer(),
    )

    result = await facade.get_sync_status("doc-123")

    assert result == [
        ArchiveSyncStatus(
            doc_id="doc-123",
            status="synced",
            last_checked_at="2026-05-06T10:00:00+00:00",
            last_sync_started_at=None,
            last_synced_at="2026-05-06T09:59:00+00:00",
            last_sync_job_id="job-1",
            is_stale_running=False,
        )
    ]


def test_resolve_dream_title_without_title_generates_topic_title() -> None:
    assert (
        _resolve_dream_title("сегодня мне приснилось море мост башня", title=None)
        == "Море мост башня"
    )


def test_resolve_dream_title_without_enough_content_returns_unnamed() -> None:
    assert (
        _resolve_dream_title("raw text", title=None, dream_date=date(2026, 4, 21)) == "без названия"
    )


def test_resolve_dream_title_with_title_and_dream_date_returns_clean_title() -> None:
    assert (
        _resolve_dream_title(
            "raw text",
            title="River valley",
            dream_date=date(2026, 4, 21),
        )
        == "River valley"
    )


def test_resolve_dream_title_with_title_and_no_dream_date_returns_title_as_is() -> None:
    assert _resolve_dream_title("raw text", title="River valley") == "River valley"


def test_resolve_dream_title_strips_date_prefix_from_provided_title() -> None:
    assert (
        _resolve_dream_title(
            "raw text",
            title="21.04.26 - River valley",
            dream_date=date(2026, 4, 21),
        )
        == "River valley"
    )


def test_resolve_relative_dream_date_from_russian_markers() -> None:
    today = date(2026, 5, 1)

    assert _resolve_relative_dream_date("сегодня мне приснился мост", today=today) == date(
        2026, 5, 1
    )
    assert _resolve_relative_dream_date("вчера снилось море", today=today) == date(2026, 4, 30)
    assert _resolve_relative_dream_date("позавчера снилась башня", today=today) == date(2026, 4, 29)


def test_resolve_absolute_dream_date_from_short_numeric_date() -> None:
    today = date(2026, 5, 20)

    assert _resolve_absolute_dream_date("запиши сон за 19.05", today=today) == date(2026, 5, 19)
    assert _resolve_absolute_dream_date("сон от 19.05.26", today=today) == date(2026, 5, 19)


@pytest.mark.asyncio
async def test_create_dream_reuses_existing_pending_processing_job() -> None:
    existing_id = uuid4()
    created_at = datetime(2026, 4, 21, tzinfo=timezone.utc)
    existing = SimpleNamespace(
        id=existing_id,
        date=date(2026, 4, 20),
        title="Existing dream",
        word_count=5,
        source_doc_id="doc-123",
        content_hash=hashlib.sha256(b"Existing dream text").hexdigest(),
        created_at=created_at,
    )
    jobs = [
        SimpleNamespace(
            id=uuid4(),
            dream_id=existing_id,
            status="pending",
            stage=stage,
        )
        for stage in DREAM_PROCESSING_STAGES
    ]
    job_id = jobs[0].id
    session = _FakeSession(
        execute_results=[
            _FakeResult(scalar=existing),
            _FakeResult(scalars=jobs),
        ]
    )
    analysis_service = SimpleNamespace(analyse_dream_with_session_factory=AsyncMock())
    index_dream_callable = AsyncMock(return_value=1)
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        analysis_service=analysis_service,
        index_dream_callable=index_dream_callable,
        title_llm_client=SimpleNamespace(complete=AsyncMock(return_value="Short title")),
    )

    with patch.object(
        facade,
        "write_dream_to_google_doc",
        AsyncMock(return_value=(True, "Сны")),
    ) as mock_write:
        result = await facade.create_dream(
            "Existing dream text",
            chat_id=7,
            source_event_key="telegram:7:message:123",
        )

    assert result == CreatedDreamItem(
        id=existing_id,
        date="2026-04-20",
        title="Existing dream",
        word_count=5,
        source_doc_id="doc-123",
        created_at=created_at.isoformat(),
        created=False,
        written_to_google_doc=False,
        semantic_index_status="pending",
        processing_status="pending",
        google_doc_write_status="pending",
        processing_job_id=job_id,
        processing_job_ids=tuple(job.id for job in jobs),
    )
    session.add.assert_not_called()
    session.commit.assert_not_awaited()
    analysis_service.analyse_dream_with_session_factory.assert_not_awaited()
    index_dream_callable.assert_not_awaited()
    mock_write.assert_not_awaited()


@pytest.mark.asyncio
async def test_source_event_replay_with_changed_body_fails_closed() -> None:
    existing = SimpleNamespace(content_hash=hashlib.sha256(b"original body").hexdigest())
    session = _FakeSession(execute_results=[_FakeResult(scalar=existing)])
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    with pytest.raises(DreamIngressConflictError, match="different dream text"):
        await facade.create_dream(
            "changed body",
            chat_id=42,
            source_event_key="telegram:42:message:777",
        )

    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_dream_source_event_race_returns_winner_and_job() -> None:
    existing_id = uuid4()
    created_at = datetime(2026, 5, 1, tzinfo=timezone.utc)
    existing = SimpleNamespace(
        id=existing_id,
        date=date(2026, 5, 1),
        title="Race winner",
        word_count=3,
        source_doc_id="telegram:42",
        content_hash=hashlib.sha256(b"Same dream text").hexdigest(),
        created_at=created_at,
    )
    jobs = [
        SimpleNamespace(
            id=uuid4(),
            dream_id=existing_id,
            status="pending",
            stage=stage,
        )
        for stage in DREAM_PROCESSING_STAGES
    ]
    job_id = jobs[0].id
    session = _FakeSession(
        execute_results=[
            _FakeResult(scalar=None),
            _FakeResult(scalar=existing),
            _FakeResult(scalars=jobs),
        ]
    )
    session.commit.side_effect = [
        IntegrityError("insert", {}, RuntimeError("unique")),
    ]
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    result = await facade.create_dream(
        "Same dream text",
        chat_id=42,
        source_event_key="telegram:42:message:456",
    )

    assert result.created is False
    assert result.id == existing_id
    assert result.processing_job_id == job_id
    assert result.processing_status == "pending"
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_duplicate_capture_does_not_reset_failed_stage_attempt_budget() -> None:
    dream_id = uuid4()
    jobs = [
        SimpleNamespace(
            id=uuid4(),
            dream_id=dream_id,
            stage=stage,
            status="failed" if stage == "index" else "succeeded",
            attempt_count=5,
            last_error="provider down",
            available_at=datetime.now(timezone.utc),
            locked_at=datetime.now(timezone.utc),
            lock_token=uuid4(),
            updated_at=datetime.now(timezone.utc),
        )
        for stage in DREAM_PROCESSING_STAGES
    ]
    session = _FakeSession(execute_results=[_FakeResult(scalars=jobs)])
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    returned = await facade._ensure_dream_processing_jobs(session, dream_id=dream_id)

    index_job = next(job for job in returned if job.stage == "index")
    assert index_job.status == "failed"
    assert index_job.attempt_count == 5
    assert index_job.last_error == "provider down"
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_processing_retry_resets_failed_stage_attempt_budget() -> None:
    dream_id = uuid4()
    failed_job = SimpleNamespace(
        id=uuid4(),
        dream_id=dream_id,
        stage="index",
        status="failed",
        attempt_count=5,
        last_error="provider down",
        available_at=datetime.now(timezone.utc),
        locked_at=datetime.now(timezone.utc),
        lock_token=uuid4(),
        updated_at=datetime.now(timezone.utc),
    )
    session = _FakeSession(execute_results=[_FakeResult(scalars=[failed_job])])
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    retried_ids = await facade.retry_dream_processing(
        dream_id,
        stages=("index",),
    )

    assert retried_ids == (failed_job.id,)
    assert failed_job.status == "retryable"
    assert failed_job.attempt_count == 0
    assert failed_job.last_error is None
    assert failed_job.locked_at is None
    assert failed_job.lock_token is None
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_write_dream_to_google_doc_returns_true_on_success() -> None:
    dream_id = uuid4()
    receipt_id = uuid4()
    dream = SimpleNamespace(
        id=dream_id,
        date=date(2026, 4, 24),
        title="Мост",
        raw_text="Я шёл по мосту.",
    )
    session = _FakeSession(
        get_result=dream,
        execute_results=[
            _FakeResult(scalar=receipt_id),
            _FakeResult(scalar=receipt_id),
        ],
    )
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    with patch("app.assistant.facade.GDocsClient.append_dream_entry", MagicMock()):
        success, _doc_name = await facade.write_dream_to_google_doc(dream_id)

    assert success is True
    assert len(session.executed_statements) == 2
    assert "ON CONFLICT" in str(session.executed_statements[0])
    assert "claim_token" in str(session.executed_statements[1])
    assert "succeeded" in session.executed_statements[1].compile().params.values()


@pytest.mark.asyncio
async def test_write_dream_to_google_doc_returns_false_on_write_error() -> None:
    dream_id = uuid4()
    receipt_id = uuid4()
    dream = SimpleNamespace(
        id=dream_id,
        date=date(2026, 4, 24),
        title="Мост",
        raw_text="Я шёл по мосту.",
    )
    session = _FakeSession(
        get_result=dream,
        execute_results=[
            _FakeResult(scalar=receipt_id),
            _FakeResult(scalar=receipt_id),
        ],
    )
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    with patch(
        "app.assistant.facade.GDocsClient.append_dream_entry",
        MagicMock(side_effect=GDocsWriteError("permission denied")),
    ):
        success, _doc_name = await facade.write_dream_to_google_doc(dream_id)

    assert success is False
    final_params = session.executed_statements[1].compile().params.values()
    assert "failed" in final_params
    assert "permission denied" in final_params


@pytest.mark.asyncio
async def test_write_dream_to_google_doc_skips_network_for_successful_receipt() -> None:
    dream_id = uuid4()
    dream = SimpleNamespace(
        id=dream_id,
        date=date(2026, 4, 24),
        title="Мост",
        raw_text="Я шёл по мосту.",
    )
    receipt = SimpleNamespace(
        id=uuid4(),
        dream_id=dream_id,
        target_doc_id="doc",
        status="succeeded",
        updated_at=datetime.now(timezone.utc),
    )
    session = _FakeSession(
        get_result=dream,
        execute_results=[
            _FakeResult(scalar=None),
            _FakeResult(scalar=receipt),
        ],
    )
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    with (
        patch("app.shared.config.get_effective_google_doc_id", return_value="doc"),
        patch("app.assistant.facade.GDocsClient.append_dream_entry", MagicMock()) as append,
    ):
        success, _doc_name = await facade.write_dream_to_google_doc(dream_id)

    assert success is True
    append.assert_not_called()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_write_dream_does_not_race_fresh_pending_receipt_owner() -> None:
    dream_id = uuid4()
    dream = SimpleNamespace(
        id=dream_id,
        date=date(2026, 4, 24),
        title="Мост",
        raw_text="Я шёл по мосту.",
    )
    pending_receipt = SimpleNamespace(
        id=uuid4(),
        dream_id=dream_id,
        target_doc_id="doc",
        status="pending",
        updated_at=datetime.now(timezone.utc),
    )
    session = _FakeSession(
        get_result=dream,
        execute_results=[
            _FakeResult(scalar=None),
            _FakeResult(scalar=pending_receipt),
        ],
    )
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    with (
        patch("app.shared.config.get_effective_google_doc_id", return_value="doc"),
        patch("app.assistant.facade.GDocsClient.append_dream_entry", MagicMock()) as append,
    ):
        success, _doc_name = await facade.write_dream_to_google_doc(dream_id)

    assert success is False
    append.assert_not_called()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_write_dream_to_google_doc_reuses_existing_failed_status_on_retry() -> None:
    dream_id = uuid4()
    status_id = uuid4()
    dream = SimpleNamespace(
        id=dream_id,
        date=date(2026, 4, 24),
        title="Мост",
        raw_text="Я шёл по мосту.",
    )
    session = _FakeSession(
        get_result=dream,
        execute_results=[
            _FakeResult(scalar=status_id),
            _FakeResult(scalar=status_id),
        ],
    )
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    with patch("app.assistant.facade.GDocsClient.append_dream_entry", MagicMock()):
        success, _doc_name = await facade.write_dream_to_google_doc(
            dream_id,
            write_status_id=status_id,
        )

    assert success is True
    claim_sql = str(session.executed_statements[0])
    assert "ON CONFLICT" in claim_sql
    assert "attempt_count" in claim_sql
    assert "failed" in session.executed_statements[0].compile().params.values()
    assert "succeeded" in session.executed_statements[1].compile().params.values()


@pytest.mark.asyncio
async def test_retry_write_to_google_doc_uses_latest_failed_status_for_chat() -> None:
    dream_id = uuid4()
    status_id = uuid4()
    failed_status = SimpleNamespace(id=status_id, dream_id=dream_id)
    dream = SimpleNamespace(
        id=dream_id,
        date=date(2026, 4, 24),
        title="Мост",
        raw_text="Я шёл по мосту.",
    )
    session = _FakeSession(
        get_result=dream,
        execute_results=[_FakeResult(scalar=failed_status)],
    )
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    with patch.object(
        facade,
        "write_dream_to_google_doc",
        AsyncMock(return_value=(True, "Сны")),
    ) as mock_write:
        success, doc_name, reason = await facade.retry_write_to_google_doc(chat_id=42)

    assert success is True
    assert doc_name == "Сны"
    assert reason == "retried"
    mock_write.assert_awaited_once_with(dream_id=dream_id, write_status_id=status_id)


@pytest.mark.asyncio
async def test_retry_write_to_google_doc_repeats_latest_chat_dream_when_no_failed_status() -> None:
    dream_id = uuid4()
    latest_dream = SimpleNamespace(
        id=dream_id,
        date=date(2026, 5, 19),
        title="Река в доме",
        raw_text="Мне приснилась река в доме.",
        source_doc_id="telegram:42",
        created_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    session = _FakeSession(
        execute_results=[
            _FakeResult(scalar=None),
            _FakeResult(scalar=latest_dream),
            _FakeResult(scalar=None),
        ],
    )
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    with patch.object(
        facade,
        "write_dream_to_google_doc",
        AsyncMock(return_value=(True, "Сны")),
    ) as mock_write:
        success, doc_name, reason = await facade.retry_write_to_google_doc(chat_id=42)

    assert success is True
    assert doc_name == "Сны"
    assert reason == "retried"
    mock_write.assert_awaited_once_with(dream_id=dream_id, write_status_id=None)
    latest_query = str(session.executed_statements[1])
    assert "dream_entries.source_doc_id" in latest_query
    assert "dream_entries.created_at" in latest_query


@pytest.mark.asyncio
async def test_retry_write_reports_successful_receipt_as_already_present() -> None:
    dream_id = uuid4()
    receipt = SimpleNamespace(id=uuid4(), dream_id=dream_id, status="succeeded")
    session = _FakeSession(
        execute_results=[
            _FakeResult(scalar=None),
            _FakeResult(scalar=receipt),
        ]
    )
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    with (
        patch("app.shared.config.get_effective_google_doc_id", return_value="doc"),
        patch("app.shared.config.get_doc_name", return_value="Сны"),
        patch.object(facade, "write_dream_to_google_doc", AsyncMock()) as write,
    ):
        success, doc_name, reason = await facade.retry_write_to_google_doc(dream_id=dream_id)

    assert (success, doc_name, reason) == (True, "Сны", "already_present")
    write.assert_not_awaited()


@pytest.mark.asyncio
async def test_retry_write_to_google_doc_returns_nothing_to_retry() -> None:
    session = _FakeSession(
        execute_results=[
            _FakeResult(scalar=None),
            _FakeResult(scalar=None),
        ],
    )
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    success, doc_name, reason = await facade.retry_write_to_google_doc(chat_id=42)

    assert success is False
    assert doc_name == ""
    assert reason == "nothing_to_retry"


@pytest.mark.asyncio
async def test_create_dream_returns_google_pending_before_worker() -> None:
    session = _FakeSession(execute_results=[_FakeResult(scalar=None)])
    analysis_service = SimpleNamespace(analyse_dream_with_session_factory=AsyncMock())
    index_dream_callable = AsyncMock(return_value=1)
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        analysis_service=analysis_service,
        index_dream_callable=index_dream_callable,
        title_llm_client=SimpleNamespace(complete=AsyncMock(return_value="Short title")),
    )

    with patch.object(
        facade, "write_dream_to_google_doc", AsyncMock(return_value=(True, "Сны"))
    ) as mock_write:
        result = await facade.create_dream("Text", chat_id=1)

    assert result.written_to_google_doc is False
    assert result.google_doc_write_status == "pending"
    mock_write.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_dream_does_not_call_google_in_capture_path() -> None:
    session = _FakeSession(execute_results=[_FakeResult(scalar=None)])
    analysis_service = SimpleNamespace(analyse_dream_with_session_factory=AsyncMock())
    index_dream_callable = AsyncMock(return_value=1)
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        analysis_service=analysis_service,
        index_dream_callable=index_dream_callable,
    )

    with patch.object(
        facade, "write_dream_to_google_doc", AsyncMock(return_value=(False, ""))
    ) as mock_write:
        result = await facade.create_dream("Text", chat_id=1)

    assert result.written_to_google_doc is False
    assert result.processing_status == "pending"
    mock_write.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_dream_does_not_infer_date_from_story_body() -> None:
    session = _FakeSession(execute_results=[_FakeResult(scalar=None)])
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    with patch("app.assistant.facade._application_today", return_value=date(2026, 5, 10)):
        result = await facade.create_dream(
            "Я оказался в доме. Вчера во сне хозяин говорил про дату 19.05.",
            chat_id=1,
        )

    assert result.date == "2026-05-10"


@pytest.mark.asyncio
async def test_process_dream_processing_job_runs_only_immutable_stage() -> None:
    dream_id = uuid4()
    job_id = uuid4()
    lock_token = uuid4()
    job = SimpleNamespace(
        id=job_id,
        dream_id=dream_id,
        stage="index",
        status="running",
        lock_token=lock_token,
    )
    session = _FakeSession(get_result=job)
    analysis_service = SimpleNamespace(analyse_dream_with_session_factory=AsyncMock())
    index_dream_callable = AsyncMock(return_value=1)
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        analysis_service=analysis_service,
        index_dream_callable=index_dream_callable,
    )

    with (
        patch.object(
            facade,
            "write_dream_to_google_doc",
            AsyncMock(return_value=(True, "Сны")),
        ) as write,
    ):
        await facade.process_dream_processing_job(job_id, lock_token=lock_token)

    index_dream_callable.assert_awaited_once_with(dream_id)
    analysis_service.analyse_dream_with_session_factory.assert_not_awaited()
    write.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_dream_processing_job_keeps_gdocs_stage_retryable() -> None:
    dream_id = uuid4()
    job_id = uuid4()
    job = SimpleNamespace(id=job_id, dream_id=dream_id, stage="gdocs")
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(_FakeSession(get_result=job)),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    with patch.object(
        facade,
        "write_dream_to_google_doc",
        AsyncMock(return_value=(False, "Сны")),
    ):
        with pytest.raises(DreamProcessingRetryable, match="pending"):
            await facade.process_dream_processing_job(job_id)


@pytest.mark.asyncio
async def test_process_dream_processing_job_rejects_stale_lease() -> None:
    job_id = uuid4()
    job = SimpleNamespace(
        id=job_id,
        dream_id=uuid4(),
        stage="index",
        status="running",
        lock_token=uuid4(),
    )
    index_dream_callable = AsyncMock()
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(_FakeSession(get_result=job)),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        index_dream_callable=index_dream_callable,
    )

    with pytest.raises(DreamProcessingLeaseLost, match="no longer owned"):
        await facade.process_dream_processing_job(job_id, lock_token=uuid4())

    index_dream_callable.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_motif_stage_uses_strict_failure_semantics() -> None:
    dream_id = uuid4()
    job = SimpleNamespace(id=uuid4(), dream_id=dream_id, stage="motif")
    dream = SimpleNamespace(id=dream_id, raw_text="river")
    motif_service = SimpleNamespace(run=AsyncMock())
    session = _FakeSession(get_results=[job, dream])
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        motif_service=motif_service,
    )

    with patch("app.assistant.facade.get_settings") as settings:
        settings.return_value.MOTIF_INDUCTION_ENABLED = True
        await facade.process_dream_processing_job(job.id)

    motif_service.run.assert_awaited_once_with(dream, session, strict=True)


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


@pytest.mark.asyncio
async def test_search_dreams_groups_multiple_chunks_per_dream() -> None:
    dream_id = uuid4()
    rag_query_service = SimpleNamespace(
        retrieve=AsyncMock(
            return_value=[
                EvidenceBlock(
                    dream_id=dream_id,
                    date=date(2026, 4, 15),
                    title="Water dream",
                    chunk_text="Фрагмент первый.",
                    relevance_score=0.75,
                    matched_fragments=[],
                ),
                EvidenceBlock(
                    dream_id=dream_id,
                    date=date(2026, 4, 15),
                    title="Water dream",
                    chunk_text="Фрагмент второй.",
                    relevance_score=0.60,
                    matched_fragments=[],
                ),
            ]
        )
    )
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(_FakeSession()),
        rag_query_service=rag_query_service,
    )

    result = await facade.search_dreams("вода")

    assert len(result.items) == 1, "Chunks from same dream must be grouped into one item"
    item = result.items[0]
    assert item.relevance_score == 0.75  # higher score kept
    assert "Фрагмент первый." in item.chunk_text
    assert "Фрагмент второй." in item.chunk_text
    assert "\n---\n" in item.chunk_text


@pytest.mark.asyncio
async def test_search_dreams_suppresses_weak_vector_result_without_query_evidence() -> None:
    dream_id = uuid4()
    rag_query_service = SimpleNamespace(
        retrieve=AsyncMock(
            return_value=[
                EvidenceBlock(
                    dream_id=dream_id,
                    date=date(2026, 4, 15),
                    title="Unrelated dream",
                    chunk_text="Я шел по коридору и искал дверь.",
                    relevance_score=0.31,
                    matched_fragments=[],
                )
            ]
        )
    )
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(_FakeSession()),
        rag_query_service=rag_query_service,
    )

    result = await facade.search_dreams("молитва")

    assert result == SearchResult(
        items=[],
        insufficient_reason="No verified archive-backed matches found",
    )