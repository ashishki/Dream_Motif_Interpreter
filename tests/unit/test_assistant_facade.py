from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.assistant.facade import (
    ArchiveSyncStatus,
    AssistantFacade,
    CreatedDreamItem,
    DreamDetail,
    DreamSummary,
    DreamTitleSearchResult,
    MotifInductionItem,
    SearchResult,
    SearchResultItem,
    SyncJobRef,
    _exact_result_item,
    _extract_quote,
    _resolve_relative_dream_date,
    _resolve_dream_title,
)
from app.services.gdocs_client import GDocsWriteError
from app.models.write_status import DreamWriteStatus
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
    def __init__(self, *, get_result=None, get_results=None, execute_results=None):
        self._get_result = get_result
        self._get_results = list(get_results or [])
        self._execute_results = list(execute_results or [])
        self.executed_statements = []
        self.add = MagicMock()
        self.commit = AsyncMock()
        self.refresh = AsyncMock()

    async def get(self, model, identity):
        del model, identity
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
        "search_dreams_exact",
        "search_dreams_by_title",
        "get_dream",
        "list_recent_dreams",
        "get_patterns",
        "create_dream",
        "add_dream_note",
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
async def test_create_dream_persists_entry_and_runs_pipeline() -> None:
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

    with patch.object(facade, "write_dream_to_google_doc", AsyncMock(return_value=(True, "Сны"))):
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
    assert result.written_to_google_doc is True
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
    assert result.title == "Мост у моря"
    added = session.add.call_args[0][0]
    assert added.date == date(2026, 4, 30)
    assert added.title == "Мост у моря"


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

    assert result.title == "Башня и мост"
    added = session.add.call_args[0][0]
    assert added.raw_text == "вчера мне приснилось море мост башня"


@pytest.mark.asyncio
async def test_create_dream_falls_back_when_title_llm_fails() -> None:
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

    assert result.title == "о море мост башня"
    title_llm_client.complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_add_dream_note_returns_true_on_success() -> None:
    dream_id = uuid4()
    created_at = datetime(2026, 4, 21, tzinfo=timezone.utc)
    dream = SimpleNamespace(
        id=dream_id,
        source_doc_id="doc-123",
        date=date(2026, 4, 21),
        title="River valley",
        created_at=created_at,
    )
    session = _FakeSession(execute_results=[_FakeResult(scalar=dream)])
    index_note_callable = AsyncMock(return_value=1)
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        index_note_callable=index_note_callable,
    )

    with patch("app.assistant.facade.GDocsClient") as mock_client_cls:
        mock_client_cls.return_value.insert_text_under_heading = MagicMock(return_value=True)
        mock_client_cls.return_value.append_text = MagicMock()

        success, message = await facade.add_dream_note("remember the red door", chat_id=42)

    assert success is True
    assert message == "Заметка добавлена под нужным сном."
    session.add.assert_called_once()
    note = session.add.call_args[0][0]
    assert note.dream_id == dream_id
    assert note.text == "remember the red door"
    assert note.source == "telegram"
    session.commit.assert_awaited_once()
    index_note_callable.assert_awaited_once_with(note.id)
    mock_client_cls.return_value.insert_text_under_heading.assert_called_once()
    call_args = mock_client_cls.return_value.insert_text_under_heading.call_args
    assert call_args.args == ("doc-123",)
    assert call_args.kwargs["heading"] == "21.04.26 - River valley"
    assert call_args.kwargs["text"].startswith("[Note ")
    assert call_args.kwargs["text"].endswith("]: remember the red door")
    mock_client_cls.return_value.append_text.assert_not_called()


@pytest.mark.asyncio
async def test_add_dream_note_reports_google_doc_not_updated_when_heading_missing() -> None:
    dream_id = uuid4()
    created_at = datetime(2026, 4, 21, tzinfo=timezone.utc)
    dream = SimpleNamespace(
        id=dream_id,
        source_doc_id="doc-123",
        date=date(2026, 4, 21),
        title="River valley",
        created_at=created_at,
    )
    session = _FakeSession(execute_results=[_FakeResult(scalar=dream)])
    index_note_callable = AsyncMock(return_value=1)
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        index_note_callable=index_note_callable,
    )

    with patch("app.assistant.facade.GDocsClient") as mock_client_cls:
        mock_client_cls.return_value.insert_text_under_heading = MagicMock(return_value=False)
        mock_client_cls.return_value.append_text = MagicMock()

        success, message = await facade.add_dream_note("remember the red door", chat_id=42)

    assert success is True
    assert (
        message
        == "Заметка сохранена в архиве, но не добавлена в Google Doc: заголовок сна не найден."
    )
    session.commit.assert_awaited_once()
    index_note_callable.assert_awaited_once()
    mock_client_cls.return_value.insert_text_under_heading.assert_called_once()
    mock_client_cls.return_value.append_text.assert_not_called()


@pytest.mark.asyncio
async def test_add_dream_note_without_id_targets_latest_archive_dream() -> None:
    dream = SimpleNamespace(
        id=uuid4(),
        source_doc_id="doc-123",
        date=date(2026, 5, 3),
        title="Manual Google Doc dream",
        created_at=datetime(2026, 5, 4, tzinfo=timezone.utc),
    )
    session = _FakeSession(execute_results=[_FakeResult(scalar=dream)])
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
    index_note_callable.assert_awaited_once_with(note.id)


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
        == "о море мост башня"
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
        title_llm_client=SimpleNamespace(complete=AsyncMock(return_value="Short title")),
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
async def test_write_dream_to_google_doc_returns_true_on_success() -> None:
    dream_id = uuid4()
    dream = SimpleNamespace(
        id=dream_id,
        date=date(2026, 4, 24),
        title="Мост",
        raw_text="Я шёл по мосту.",
    )
    session = _FakeSession(get_result=dream)
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    with patch("app.assistant.facade.GDocsClient.append_dream_entry", MagicMock()):
        success, _doc_name = await facade.write_dream_to_google_doc(dream_id)

    assert success is True
    write_statuses = [
        call.args[0]
        for call in session.add.call_args_list
        if isinstance(call.args[0], DreamWriteStatus)
    ]
    assert write_statuses[-1].status == "succeeded"
    assert write_statuses[-1].attempt_count == 1


@pytest.mark.asyncio
async def test_write_dream_to_google_doc_returns_false_on_write_error() -> None:
    dream_id = uuid4()
    dream = SimpleNamespace(
        id=dream_id,
        date=date(2026, 4, 24),
        title="Мост",
        raw_text="Я шёл по мосту.",
    )
    session = _FakeSession(get_result=dream)
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
    write_statuses = [
        call.args[0]
        for call in session.add.call_args_list
        if isinstance(call.args[0], DreamWriteStatus)
    ]
    assert write_statuses[-1].status == "failed"
    assert write_statuses[-1].last_error == "permission denied"


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
    failed_status = DreamWriteStatus(
        id=status_id,
        dream_id=dream_id,
        target_doc_id="doc",
        status="failed",
        attempt_count=1,
        last_error="permission denied",
        updated_at=datetime.now(timezone.utc),
    )
    session = _FakeSession(get_results=[dream, failed_status])
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
    assert failed_status.status == "succeeded"
    assert failed_status.attempt_count == 2
    assert failed_status.last_error is None
    assert all(call.args[0] is failed_status for call in session.add.call_args_list)


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
async def test_retry_write_to_google_doc_returns_nothing_to_retry() -> None:
    session = _FakeSession(execute_results=[_FakeResult(scalar=None)])
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
    )

    success, doc_name, reason = await facade.retry_write_to_google_doc(chat_id=42)

    assert success is False
    assert doc_name == ""
    assert reason == "nothing_to_retry"


@pytest.mark.asyncio
async def test_create_dream_sets_written_to_google_doc_true_on_success() -> None:
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

    with patch.object(facade, "write_dream_to_google_doc", AsyncMock(return_value=(True, "Сны"))):
        result = await facade.create_dream("Text", chat_id=1)

    assert result.written_to_google_doc is True
    assert result.written_to_doc_name == "Сны"


@pytest.mark.asyncio
async def test_create_dream_sets_written_to_google_doc_false_on_write_failure() -> None:
    session = _FakeSession(execute_results=[_FakeResult(scalar=None)])
    analysis_service = SimpleNamespace(analyse_dream_with_session_factory=AsyncMock())
    index_dream_callable = AsyncMock(return_value=1)
    facade = AssistantFacade(
        session_factory=_FakeSessionFactory(session),
        rag_query_service=SimpleNamespace(retrieve=AsyncMock()),
        analysis_service=analysis_service,
        index_dream_callable=index_dream_callable,
    )

    with patch.object(facade, "write_dream_to_google_doc", AsyncMock(return_value=(False, ""))):
        result = await facade.create_dream("Text", chat_id=1)

    assert result.written_to_google_doc is False


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
