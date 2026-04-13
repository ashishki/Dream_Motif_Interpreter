from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from sqlalchemy import text

from app.models.dream import DreamEntry
from app.retrieval.ingestion import EMBEDDING_DIMENSIONS, RagIngestionService, fetch_indexed_chunks

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


@pytest_asyncio.fixture
async def migrated_session_factory() -> async_sessionmaker[AsyncSession]:
    database_url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://postgres@localhost:5433/dream_motif_test",
    )
    os.environ["DATABASE_URL"] = database_url

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


def _dream_text(word_count: int) -> str:
    first_half = word_count // 2
    second_half = word_count - first_half
    return "\n\n".join(
        [
            " ".join(f"alpha{index}" for index in range(first_half)),
            " ".join(f"beta{index}" for index in range(second_half)),
        ]
    )


def _vector_length(vector_literal: str | None) -> int:
    assert vector_literal is not None
    return len(vector_literal.strip("[]").split(","))


@pytest.mark.skipif(
    (not os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY", "").startswith("test-"))
    or not os.getenv("TEST_DATABASE_URL"),
    reason="Real OpenAI API key required",
)
@pytest.mark.asyncio
async def test_index_dream_creates_chunk_with_embedding(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with migrated_session_factory() as session:
        dream = DreamEntry(
            source_doc_id="doc-rag-1",
            date=None,
            title="Embedding test dream",
            raw_text=_dream_text(100),
            word_count=100,
            content_hash=f"rag-hash-{uuid.uuid4()}",
            segmentation_confidence="high",
        )
        session.add(dream)
        await session.commit()

    service = RagIngestionService(session_factory=migrated_session_factory)
    await service.index_dream(dream.id)

    async with migrated_session_factory() as session:
        chunks = await fetch_indexed_chunks(session, dream.id)

    assert len(chunks) >= 1
    assert chunks[0].embedding is not None
    assert _vector_length(chunks[0].embedding) == EMBEDDING_DIMENSIONS


@pytest.mark.skipif(
    (not os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY", "").startswith("test-"))
    or not os.getenv("TEST_DATABASE_URL"),
    reason="Real OpenAI API key required",
)
@pytest.mark.asyncio
async def test_index_dream_idempotent(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with migrated_session_factory() as session:
        dream = DreamEntry(
            source_doc_id="doc-rag-2",
            date=None,
            title="Idempotency test dream",
            raw_text=_dream_text(100),
            word_count=100,
            content_hash=f"rag-idempotent-hash-{uuid.uuid4()}",
            segmentation_confidence="high",
        )
        session.add(dream)
        await session.commit()

    service = RagIngestionService(session_factory=migrated_session_factory)
    await service.index_dream(dream.id)
    await service.index_dream(dream.id)

    async with migrated_session_factory() as session:
        chunks = await fetch_indexed_chunks(session, dream.id)

    assert len(chunks) == 1
