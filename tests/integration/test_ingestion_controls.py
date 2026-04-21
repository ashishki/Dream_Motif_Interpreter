from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.dream import DreamEntry
from app.retrieval.ingestion import EMBEDDING_DIMENSIONS, process_source_document
from app.retrieval.types import FetchedSourceDocument, SourceDocumentRef, SourceConnector
from app.shared.config import get_settings
from app.workers.ingest import _store_entries, ingest_source_container

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


class StubEmbeddingClient:
    async def embed(self, texts: list[str], *, dream_id: str | None = None) -> list[list[float]]:
        del dream_id
        return [[0.25] * EMBEDDING_DIMENSIONS for _ in texts]


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


class StaticFolderConnector(SourceConnector):
    def __init__(self, documents: list[FetchedSourceDocument]) -> None:
        self._documents = {document.external_id: document for document in documents}

    def list_documents(self) -> list[SourceDocumentRef]:
        return [
            SourceDocumentRef(
                source_type=document.source_type,
                external_id=document.external_id,
                title=document.title,
                source_path=document.source_path,
                updated_at=document.updated_at,
            )
            for document in self._documents.values()
        ]

    def fetch_document(self, document: SourceDocumentRef) -> FetchedSourceDocument:
        return self._documents[document.external_id]


@pytest_asyncio.fixture
async def migrated_session_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> async_sessionmaker[AsyncSession]:
    database_url = "postgresql+asyncpg://postgres@localhost:5433/dream_motif_test"
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
        get_settings.cache_clear()
        await engine.dispose()


def _fetched_document(
    external_id: str,
    *,
    source_path: str,
    paragraphs: list[str],
) -> FetchedSourceDocument:
    return FetchedSourceDocument(
        source_type="google_doc",
        external_id=external_id,
        title=external_id,
        source_path=source_path,
        updated_at=datetime(2026, 4, 21, tzinfo=timezone.utc),
        raw_contents=paragraphs,
    )


def _worker_ctx(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, object]:
    return {
        "redis": FakeRedis(),
        "session_factory": session_factory,
        "analysis_service": NoopAnalysisService(),
        "embedding_client": StubEmbeddingClient(),
        "motif_service": NoopMotifService(),
    }


@pytest.mark.asyncio
async def test_operator_profile_assignment_applied_on_next_ingest(
    migrated_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_document = _fetched_document(
        "doc-operator-controls-first",
        source_path="documents/doc-operator-controls-first",
        paragraphs=["I crossed a bridge that led nowhere."],
    )
    await _store_entries(
        session_factory=migrated_session_factory,
        fetched_document=first_document,
        client_id="client-controls",
    )

    monkeypatch.setenv(
        "OPERATOR_PARSER_PROFILE_ASSIGNMENTS",
        json.dumps({"clients": {"client-controls": "heading_based"}}),
    )
    get_settings.cache_clear()

    second_document = _fetched_document(
        "doc-operator-controls-second",
        source_path="documents/doc-operator-controls-second",
        paragraphs=["I crossed a bridge that led somewhere else."],
    )
    await _store_entries(
        session_factory=migrated_session_factory,
        fetched_document=second_document,
        client_id="client-controls",
    )

    async with migrated_session_factory() as session:
        entries = list(
            (
                await session.execute(
                    select(DreamEntry).order_by(DreamEntry.source_doc_id.asc())
                )
            ).scalars()
        )

    assert len(entries) == 2
    assert entries[0].source_doc_id == "doc-operator-controls-first"
    assert entries[0].parser_profile == "default"
    assert entries[1].source_doc_id == "doc-operator-controls-second"
    assert entries[1].parser_profile == "heading_based"


@pytest.mark.asyncio
async def test_low_confidence_parse_is_reviewable() -> None:
    document = _fetched_document(
        "doc-low-confidence-review",
        source_path="folders/review/doc-low-confidence-review",
        paragraphs=[
            "I was standing in an empty field at dusk.",
            "The wind kept moving the same ladder in slow circles.",
        ],
    )

    pipeline = process_source_document(document, client_id="client-review")

    assert pipeline.parsed_document.applied_profile == "default"
    assert len(pipeline.parsed_document.review_warnings) == 1
    assert pipeline.validated_entries[0].segmentation_confidence == "low"

    warning = pipeline.parsed_document.review_warnings[0]
    assert warning.code == "low_confidence_parse"
    assert warning.source_type == "google_doc"
    assert warning.external_id == "doc-low-confidence-review"
    assert warning.source_path == "folders/review/doc-low-confidence-review"
    assert warning.client_id == "client-review"
    assert warning.applied_profile == "default"
    assert any("falling back to default profile" in item for item in warning.warnings)


@pytest.mark.asyncio
async def test_folder_intake_preserves_per_document_provenance(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    connector = StaticFolderConnector(
        [
            _fetched_document(
                "doc-folder-one",
                source_path="folders/april/doc-folder-one",
                paragraphs=["2026-04-01", "A silver bird circled over the station."],
            ),
            _fetched_document(
                "doc-folder-two",
                source_path="folders/april/doc-folder-two",
                paragraphs=["Threshold", "I waited at a doorway made of rain."],
            ),
        ]
    )

    new_entries = await ingest_source_container(
        _worker_ctx(migrated_session_factory),
        job_id=uuid.uuid4(),
        connector=connector,
        client_id="client-folder",
    )

    async with migrated_session_factory() as session:
        entries = list(
            (
                await session.execute(
                    select(DreamEntry).order_by(DreamEntry.source_doc_id.asc())
                )
            ).scalars()
        )

    assert new_entries == 2
    assert [entry.source_doc_id for entry in entries] == ["doc-folder-one", "doc-folder-two"]
    assert entries[0].date.isoformat() == "2026-04-01"
    assert entries[0].parser_profile == "dated_entries"
    assert entries[1].title == "Threshold"
    assert entries[1].parser_profile == "heading_based"
