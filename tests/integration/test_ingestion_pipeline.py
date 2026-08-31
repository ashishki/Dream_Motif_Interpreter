from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.assistant.facade import AssistantFacade
from app.models.dream import DreamChunk, DreamEntry
from app.models.note import DreamNote
from app.models.processing import DreamProcessingJob, NoteProcessingJob
from app.models.write_status import DreamWriteStatus
from app.retrieval.ingestion import DreamEntryValidationError
from app.retrieval.ingestion import EMBEDDING_DIMENSIONS
from app.retrieval.query import RagQueryService
from app.workers.ingest import ingest_document
from app.workers.index import index_note
from app.workers.note_processing import process_pending_note_jobs

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config() -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    return config


async def _reset_public_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
        await connection.execute(text("GRANT ALL ON SCHEMA public TO public"))


class FakeRedis:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        del ex
        self._values[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self._values.get(key)


class StaticGDocsClient:
    def __init__(self, paragraphs: list[str], order_log: list[str] | None = None) -> None:
        self._paragraphs = paragraphs
        self._order_log = order_log

    def fetch_document(self, document_id: str | None = None) -> list[str]:
        del document_id
        if self._order_log is not None:
            self._order_log.append("source_connector")
        return list(self._paragraphs)


class StubEmbeddingClient:
    async def embed(self, texts: list[str], *, dream_id: str | None = None) -> list[list[float]]:
        del dream_id
        return [[0.125] * EMBEDDING_DIMENSIONS for _ in texts]


class NoopAnalysisService:
    async def analyse_dream_with_session_factory(
        self,
        dream_id: uuid.UUID,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        del dream_id, session_factory


class NoopMotifService:
    async def run(self, dream_entry: DreamEntry, session: AsyncSession) -> None:
        del dream_entry, session


@pytest_asyncio.fixture
async def migrated_session_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> async_sessionmaker[AsyncSession]:
    database_url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://postgres@localhost:5433/dream_motif_test",
    )
    monkeypatch.setenv("DATABASE_URL", database_url)

    reset_engine = create_async_engine(
        database_url,
        poolclass=NullPool,
        connect_args={"statement_cache_size": 0},
    )
    await _reset_public_schema(reset_engine)
    await reset_engine.dispose()
    await asyncio.to_thread(command.upgrade, _alembic_config(), "head")

    engine = create_async_engine(
        database_url,
        poolclass=NullPool,
        connect_args={"statement_cache_size": 0},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield session_factory
    finally:
        await engine.dispose()


def _worker_ctx(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    paragraphs: list[str],
    order_log: list[str] | None = None,
) -> dict[str, object]:
    return {
        "redis": FakeRedis(),
        "session_factory": session_factory,
        "gdocs_client": StaticGDocsClient(paragraphs, order_log=order_log),
        "analysis_service": NoopAnalysisService(),
        "embedding_client": StubEmbeddingClient(),
        "motif_service": NoopMotifService(),
    }


async def _drain_note_jobs(
    session_factory: async_sessionmaker[AsyncSession],
    worker_ctx: dict[str, object],
) -> int:
    async def _index(note_id: uuid.UUID) -> int:
        return await index_note(worker_ctx, note_id=note_id)

    facade = AssistantFacade(
        session_factory=session_factory,
        rag_query_service=RagQueryService(session_factory=session_factory),
        index_note_callable=_index,
    )
    return await process_pending_note_jobs(
        {
            "session_factory": session_factory,
            "assistant_facade": facade,
        },
        limit=20,
    )


@pytest.mark.asyncio
async def test_ingestion_uses_canonical_stage_order(
    migrated_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.retrieval.ingestion as ingestion_module
    import app.workers.ingest as ingest_module

    order: list[str] = []

    original_normalize = ingestion_module.normalize_source_document
    original_parse = ingestion_module.parse_normalized_document
    original_validate = ingestion_module.validate_dream_entry_candidates
    original_index = ingest_module.index_dream

    def _recording_normalize(*args, **kwargs):
        order.append("normalized_document")
        return original_normalize(*args, **kwargs)

    def _recording_parse(*args, **kwargs):
        order.append("parser_profile")
        parsed = original_parse(*args, **kwargs)
        order.append("dream_entry_candidates")
        return parsed

    def _recording_validate(*args, **kwargs):
        order.append("validated_dream_entries")
        return original_validate(*args, **kwargs)

    async def _recording_index(ctx: dict[str, object], *, dream_id: uuid.UUID) -> int:
        order.append("embeddings_indexing")
        return await original_index(ctx, dream_id=dream_id)

    monkeypatch.setattr(ingestion_module, "normalize_source_document", _recording_normalize)
    monkeypatch.setattr(ingestion_module, "parse_normalized_document", _recording_parse)
    monkeypatch.setattr(ingestion_module, "validate_dream_entry_candidates", _recording_validate)
    monkeypatch.setattr(ingest_module, "index_dream", _recording_index)

    await ingest_document(
        _worker_ctx(
            migrated_session_factory,
            paragraphs=[
                "2026-04-01",
                "I walked through a blue hallway toward a garden.",
            ],
            order_log=order,
        ),
        job_id=uuid.uuid4(),
        doc_id="doc-canonical-order",
    )

    assert order == [
        "source_connector",
        "normalized_document",
        "parser_profile",
        "dream_entry_candidates",
        "validated_dream_entries",
        "embeddings_indexing",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure_stage", "patched_name", "error"),
    [
        ("normalize", "normalize_source_document", ValueError("normalization failed")),
        (
            "validate",
            "validate_dream_entry_candidates",
            DreamEntryValidationError("candidate validation failed"),
        ),
    ],
)
async def test_invalid_documents_do_not_reach_embedding_stage(
    migrated_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
    patched_name: str,
    error: Exception,
) -> None:
    import app.retrieval.ingestion as ingestion_module
    import app.workers.ingest as ingest_module

    index_calls: list[uuid.UUID] = []

    def _raise_error(*args, **kwargs):
        del args, kwargs
        raise error

    async def _recording_index(ctx: dict[str, object], *, dream_id: uuid.UUID) -> int:
        del ctx
        index_calls.append(dream_id)
        return 0

    monkeypatch.setattr(ingestion_module, patched_name, _raise_error)
    monkeypatch.setattr(ingest_module, "index_dream", _recording_index)

    with pytest.raises(type(error), match=str(error)):
        await ingest_document(
            _worker_ctx(
                migrated_session_factory,
                paragraphs=[
                    "2026-04-02",
                    f"This document fails at the {failure_stage} stage.",
                ],
            ),
            job_id=uuid.uuid4(),
            doc_id=f"doc-invalid-{failure_stage}",
        )

    async with migrated_session_factory() as session:
        entry_count = await session.scalar(select(func.count()).select_from(DreamEntry))
        chunk_count = await session.scalar(select(func.count()).select_from(DreamChunk))

    assert index_calls == []
    assert entry_count == 0
    assert chunk_count == 0


@pytest.mark.asyncio
async def test_reingest_is_idempotent_under_normalized_pipeline(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    worker_ctx = _worker_ctx(
        migrated_session_factory,
        paragraphs=[
            "2026-04-03",
            "A lantern drifted over the river and turned into a bridge.",
        ],
    )

    first_new_entries = await ingest_document(
        worker_ctx,
        job_id=uuid.uuid4(),
        doc_id="doc-reingest-idempotent",
    )
    second_new_entries = await ingest_document(
        worker_ctx,
        job_id=uuid.uuid4(),
        doc_id="doc-reingest-idempotent",
    )

    async with migrated_session_factory() as session:
        entry_count = await session.scalar(select(func.count()).select_from(DreamEntry))
        chunk_count = await session.scalar(select(func.count()).select_from(DreamChunk))
        stored_entry = await session.scalar(
            select(DreamEntry).where(DreamEntry.source_doc_id == "doc-reingest-idempotent")
        )

    assert stored_entry is not None
    assert first_new_entries == 1
    assert second_new_entries == 0
    assert entry_count == 1
    assert chunk_count == 1


@pytest.mark.asyncio
async def test_reingest_updates_existing_telegram_dream_title_from_google_doc(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    raw_text = "I walked through a hallway with red doors."
    content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    async with migrated_session_factory() as session:
        session.add(
            DreamEntry(
                id=uuid.uuid4(),
                source_doc_id="telegram:42",
                date=None,
                title="Old voice title",
                raw_text=raw_text,
                word_count=len(raw_text.split()),
                content_hash=content_hash,
                segmentation_confidence="high",
                parser_profile="telegram",
                parse_warnings=[],
            )
        )
        await session.commit()

    worker_ctx = _worker_ctx(
        migrated_session_factory,
        paragraphs=[
            "2026-05-01 - New Google Doc title",
            raw_text,
        ],
    )

    new_entries = await ingest_document(
        worker_ctx,
        job_id=uuid.uuid4(),
        doc_id="doc-title-update",
    )

    facade = AssistantFacade(
        session_factory=migrated_session_factory,
        rag_query_service=RagQueryService(session_factory=migrated_session_factory),
    )
    title_matches = await facade.search_dreams_by_title("New Google Doc title")

    async with migrated_session_factory() as session:
        entry_count = await session.scalar(select(func.count()).select_from(DreamEntry))
        stored_entry = await session.scalar(
            select(DreamEntry).where(DreamEntry.content_hash == content_hash)
        )

    assert stored_entry is not None
    assert new_entries == 0
    assert entry_count == 1
    assert stored_entry.source_doc_id == "doc-title-update"
    assert stored_entry.date.isoformat() == "2026-05-01"
    assert stored_entry.title == "New Google Doc title"
    assert [match.dream_id for match in title_matches] == [stored_entry.id]


@pytest.mark.asyncio
async def test_google_ingest_marks_adopted_telegram_delivery_as_succeeded(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    raw_text = "I found the same blue gate from my captured dream."
    content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    dream_id = uuid.uuid4()
    gdocs_job_id = uuid.uuid4()
    async with migrated_session_factory() as session:
        session.add_all(
            [
                DreamEntry(
                    id=dream_id,
                    source_doc_id="telegram:42",
                    date=None,
                    title="Blue gate",
                    raw_text=raw_text,
                    word_count=len(raw_text.split()),
                    content_hash=content_hash,
                    source_event_key="event-blue-gate",
                    segmentation_confidence="low",
                    parser_profile="telegram",
                    parse_warnings=[],
                ),
                DreamProcessingJob(
                    id=gdocs_job_id,
                    dream_id=dream_id,
                    stage="gdocs",
                    status="pending",
                    attempt_count=0,
                ),
            ]
        )
        await session.commit()

    added = await ingest_document(
        _worker_ctx(
            migrated_session_factory,
            paragraphs=["2026-05-01 - Blue gate", raw_text],
        ),
        job_id=uuid.uuid4(),
        doc_id="doc-adopted-capture",
    )

    async with migrated_session_factory() as session:
        dream = await session.get(DreamEntry, dream_id)
        job = await session.get(DreamProcessingJob, gdocs_job_id)
        receipt = await session.scalar(
            select(DreamWriteStatus).where(
                DreamWriteStatus.dream_id == dream_id,
                DreamWriteStatus.target_doc_id == "doc-adopted-capture",
            )
        )

    assert added == 0
    assert dream is not None
    assert dream.source_doc_id == "doc-adopted-capture"
    assert job is not None and job.status == "succeeded"
    assert receipt is not None and receipt.status == "succeeded"


@pytest.mark.asyncio
async def test_user_added_google_doc_note_is_synced_once_and_searchable(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    worker_ctx = _worker_ctx(
        migrated_session_factory,
        paragraphs=[
            "2026-05-01",
            "I walked through a hallway with red doors.",
            "[Note 06.05.26]: после пробуждения красная дверь ощущалась важной",
        ],
    )

    first_new_entries = await ingest_document(
        worker_ctx,
        job_id=uuid.uuid4(),
        doc_id="doc-user-note-simulation",
    )
    second_new_entries = await ingest_document(
        worker_ctx,
        job_id=uuid.uuid4(),
        doc_id="doc-user-note-simulation",
    )

    async with migrated_session_factory() as session:
        queued_jobs = (
            (
                await session.execute(
                    select(NoteProcessingJob).order_by(NoteProcessingJob.stage.asc())
                )
            )
            .scalars()
            .all()
        )
        note_chunks_before_drain = await session.scalar(
            select(func.count()).select_from(DreamChunk).where(DreamChunk.source_kind == "note")
        )

    assert len(queued_jobs) == 1
    assert queued_jobs[0].stage == "index"
    assert queued_jobs[0].status == "pending"
    assert queued_jobs[0].target_doc_id is None
    assert note_chunks_before_drain == 0

    processed_jobs = await _drain_note_jobs(migrated_session_factory, worker_ctx)

    search_service = RagQueryService(session_factory=migrated_session_factory)
    exact_matches = await search_service.exact_search("красная дверь важной")

    async with migrated_session_factory() as session:
        entry_count = await session.scalar(select(func.count()).select_from(DreamEntry))
        note_count = await session.scalar(select(func.count()).select_from(DreamNote))
        chunks = (
            (
                await session.execute(
                    select(DreamChunk).order_by(
                        DreamChunk.source_kind.asc(),
                        DreamChunk.chunk_index.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        dream = await session.scalar(
            select(DreamEntry).where(DreamEntry.source_doc_id == "doc-user-note-simulation")
        )

    assert first_new_entries == 1
    assert second_new_entries == 0
    assert processed_jobs == 1
    assert entry_count == 1
    assert note_count == 1
    assert dream is not None
    assert "после пробуждения" not in dream.raw_text
    assert {chunk.source_kind for chunk in chunks} == {"dream_text", "note"}
    assert any("красная дверь ощущалась важной" in row["chunk_text"] for row in exact_matches)


@pytest.mark.asyncio
async def test_google_note_and_index_job_roll_back_together(
    migrated_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workers import ingest as ingest_module

    async def _fail_outbox_insert(**_kwargs: object) -> None:
        raise RuntimeError("simulated outbox insert failure")

    monkeypatch.setattr(
        ingest_module,
        "_ensure_imported_note_index_job",
        _fail_outbox_insert,
    )

    with pytest.raises(RuntimeError, match="outbox insert failure"):
        await ingest_document(
            _worker_ctx(
                migrated_session_factory,
                paragraphs=[
                    "2026-05-01 - Атомарная заметка",
                    "I crossed a bridge under a silent sky.",
                    "[Note 06.05.26]: эта заметка не должна сохраниться отдельно",
                ],
            ),
            job_id=uuid.uuid4(),
            doc_id="doc-note-atomic-rollback",
        )

    async with migrated_session_factory() as session:
        dream_count = await session.scalar(select(func.count()).select_from(DreamEntry))
        note_count = await session.scalar(select(func.count()).select_from(DreamNote))
        job_count = await session.scalar(select(func.count()).select_from(NoteProcessingJob))

    assert dream_count == 0
    assert note_count == 0
    assert job_count == 0


@pytest.mark.asyncio
async def test_reingest_repairs_existing_note_with_null_embedding(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    worker_ctx = _worker_ctx(
        migrated_session_factory,
        paragraphs=[
            "2026-05-02 - Красная дверь",
            "I walked through a hallway with red doors.",
            "[Note 06.05.26]: после пробуждения дверь ощущалась важной",
        ],
    )
    await ingest_document(
        worker_ctx,
        job_id=uuid.uuid4(),
        doc_id="doc-note-index-repair",
    )
    assert await _drain_note_jobs(migrated_session_factory, worker_ctx) == 1

    async with migrated_session_factory() as session:
        note = await session.scalar(select(DreamNote))
        assert note is not None
        await session.execute(
            update(DreamChunk).where(DreamChunk.note_id == note.id).values(embedding=None)
        )
        await session.commit()

    await ingest_document(
        worker_ctx,
        job_id=uuid.uuid4(),
        doc_id="doc-note-index-repair",
    )

    async with migrated_session_factory() as session:
        repaired_job = await session.scalar(
            select(NoteProcessingJob).where(NoteProcessingJob.note_id == note.id)
        )
    assert repaired_job is not None
    assert repaired_job.stage == "index"
    assert repaired_job.status == "retryable"
    assert await _drain_note_jobs(migrated_session_factory, worker_ctx) == 1

    async with migrated_session_factory() as session:
        repaired_chunk = await session.scalar(
            select(DreamChunk).where(DreamChunk.note_id == note.id)
        )
    assert repaired_chunk is not None
    assert repaired_chunk.source_kind == "note"
    assert repaired_chunk.embedding is not None


@pytest.mark.asyncio
async def test_google_doc_body_edit_fails_closed_without_silent_duplicate(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first_ctx = _worker_ctx(
        migrated_session_factory,
        paragraphs=[
            "2026-05-03 - Мост над рекой",
            "The original dream body crossed a river.",
        ],
    )
    await ingest_document(
        first_ctx,
        job_id=uuid.uuid4(),
        doc_id="doc-body-edit-conflict",
    )

    edited_ctx = _worker_ctx(
        migrated_session_factory,
        paragraphs=[
            "2026-05-03 - Мост над рекой",
            "The edited dream body crossed a dark river.",
        ],
    )
    added = await ingest_document(
        edited_ctx,
        job_id=uuid.uuid4(),
        doc_id="doc-body-edit-conflict",
    )

    async with migrated_session_factory() as session:
        dreams = (await session.execute(select(DreamEntry))).scalars().all()

    assert added == 0
    assert len(dreams) == 1
    assert dreams[0].raw_text == "The original dream body crossed a river."


@pytest.mark.asyncio
async def test_source_slot_identity_survives_unrelated_heading_insert(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await ingest_document(
        _worker_ctx(
            migrated_session_factory,
            paragraphs=[
                "2026-05-01 - Первый",
                "The first stable dream body.",
                "2026-05-03 - Третий",
                "The third stable dream body.",
            ],
        ),
        job_id=uuid.uuid4(),
        doc_id="doc-heading-slot-stability",
    )

    added = await ingest_document(
        _worker_ctx(
            migrated_session_factory,
            paragraphs=[
                "2026-05-01 - Первый",
                "The first stable dream body.",
                "2026-05-02 - Второй",
                "The newly inserted second dream body.",
                "2026-05-03 - Третий",
                "The third stable dream body.",
            ],
        ),
        job_id=uuid.uuid4(),
        doc_id="doc-heading-slot-stability",
    )

    async with migrated_session_factory() as session:
        dreams = (await session.execute(select(DreamEntry))).scalars().all()
        source_keys = {dream.source_entry_key for dream in dreams}

    assert added == 1
    assert len(dreams) == 3
    assert None not in source_keys
    assert len(source_keys) == 3


@pytest.mark.asyncio
async def test_same_body_in_second_doc_does_not_flip_source_identity(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    paragraphs = [
        "2026-05-04 - Один и тот же сон",
        "The same stable dream body appears in two documents.",
    ]
    await ingest_document(
        _worker_ctx(migrated_session_factory, paragraphs=paragraphs),
        job_id=uuid.uuid4(),
        doc_id="doc-source-owner-a",
    )

    added = await ingest_document(
        _worker_ctx(migrated_session_factory, paragraphs=paragraphs),
        job_id=uuid.uuid4(),
        doc_id="doc-source-owner-b",
    )

    async with migrated_session_factory() as session:
        dreams = (await session.execute(select(DreamEntry))).scalars().all()

    assert added == 1
    assert len(dreams) == 2
    assert {dream.source_doc_id for dream in dreams} == {
        "doc-source-owner-a",
        "doc-source-owner-b",
    }
    assert len({dream.source_entry_key for dream in dreams}) == 2


@pytest.mark.asyncio
async def test_same_body_in_distinct_slots_of_one_doc_creates_distinct_dreams(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    body = "The same dream body was intentionally recorded twice."
    added = await ingest_document(
        _worker_ctx(
            migrated_session_factory,
            paragraphs=[
                "2026-05-04 - Первый повтор",
                body,
                "2026-05-05 - Второй повтор",
                body,
            ],
        ),
        job_id=uuid.uuid4(),
        doc_id="doc-repeated-body-slots",
    )

    async with migrated_session_factory() as session:
        dreams = (
            (
                await session.execute(
                    select(DreamEntry).where(DreamEntry.source_doc_id == "doc-repeated-body-slots")
                )
            )
            .scalars()
            .all()
        )

    assert added == 2
    assert len(dreams) == 2
    assert len({dream.source_entry_key for dream in dreams}) == 2


@pytest.mark.asyncio
async def test_combined_heading_and_body_edit_fails_closed(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await ingest_document(
        _worker_ctx(
            migrated_session_factory,
            paragraphs=[
                "2026-05-05 - Старый мост",
                "The original body crossed an old bridge.",
            ],
        ),
        job_id=uuid.uuid4(),
        doc_id="doc-heading-body-edit",
    )

    added = await ingest_document(
        _worker_ctx(
            migrated_session_factory,
            paragraphs=[
                "2026-05-06 - Новый маяк",
                "The changed body climbed a bright lighthouse.",
            ],
        ),
        job_id=uuid.uuid4(),
        doc_id="doc-heading-body-edit",
    )

    async with migrated_session_factory() as session:
        dreams = (await session.execute(select(DreamEntry))).scalars().all()

    assert added == 0
    assert len(dreams) == 1
    assert dreams[0].title == "Старый мост"
    assert dreams[0].raw_text == "The original body crossed an old bridge."
