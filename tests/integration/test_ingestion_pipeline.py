from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.models.dream import DreamChunk, DreamEntry
from app.retrieval.ingestion import DreamEntryValidationError
from app.retrieval.ingestion import EMBEDDING_DIMENSIONS
from app.workers.ingest import ingest_document

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

    def fetch_document(self) -> list[str]:
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
