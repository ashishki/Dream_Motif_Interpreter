from __future__ import annotations

import asyncio
import math
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.models.dream import DreamEntry
from app.retrieval.ingestion import RagIngestionService
from app.retrieval.query import (
    EvidenceBlock,
    FragmentMatch,
    InsufficientEvidence,
    QueryEmbeddingError,
    RagQueryService,
)
from app.shared.config import get_settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAG_QUERY_SKIP_REASON = (
    "Real OpenAI API key and TEST_DATABASE_URL are required for integration retrieval tests"
)


class _StaticEmbeddingClient:
    async def embed(self, texts: list[str], **_: object) -> list[list[float]]:
        embedding = [1.0, *([0.0] * 1535)]
        return [embedding.copy() for _ in texts]


class _MappedEmbeddingClient:
    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors

    async def embed(self, texts: list[str], **_: object) -> list[list[float]]:
        return [self._vectors[text].copy() for text in texts]


def _embedding_with_cosine(cosine: float) -> list[float]:
    return [cosine, math.sqrt(1 - cosine**2), *([0.0] * 1534)]


def _alembic_config() -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    return config


async def _reset_public_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
        await connection.execute(text("GRANT ALL ON SCHEMA public TO public"))


def _reload_app():
    import sys

    sys.modules.pop("app.main", None)
    sys.modules.pop("app.api.health", None)
    get_settings.cache_clear()

    from app.api import health as health_module
    from app.main import app

    health_module._get_engine.cache_clear()
    return app


@pytest_asyncio.fixture
async def migrated_session_factory() -> async_sessionmaker[AsyncSession]:
    database_url = os.environ["TEST_DATABASE_URL"]
    os.environ["DATABASE_URL"] = database_url
    get_settings.cache_clear()

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


async def _create_dream(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    title: str,
    raw_text: str,
) -> uuid.UUID:
    async with session_factory() as session:
        dream = DreamEntry(
            source_doc_id=f"doc-{uuid.uuid4()}",
            date=datetime.now(timezone.utc).date(),
            title=title,
            raw_text=raw_text,
            word_count=len(raw_text.split()),
            content_hash=f"hash-{uuid.uuid4()}",
            segmentation_confidence="high",
        )
        session.add(dream)
        await session.commit()
        await session.refresh(dream)
        return dream.id


async def _attach_fragment(
    session_factory: async_sessionmaker[AsyncSession], dream_id: uuid.UUID, fragment_text: str
) -> None:
    async with session_factory() as session:
        category_id = (
            await session.execute(
                text(
                    """
                    INSERT INTO theme_categories (name, description, status)
                    VALUES (:name, :description, :status)
                    RETURNING id
                    """
                ),
                {
                    "name": f"category-{uuid.uuid4()}",
                    "description": "Dream fragment test category",
                    "status": "active",
                },
            )
        ).scalar_one()
        await session.execute(
            text(
                """
                INSERT INTO dream_themes (
                    dream_id,
                    category_id,
                    salience,
                    status,
                    match_type,
                    fragments,
                    deprecated
                )
                VALUES (
                    :dream_id,
                    :category_id,
                    :salience,
                    :status,
                    :match_type,
                    CAST(:fragments AS jsonb),
                    :deprecated
                )
                """
            ),
            {
                "dream_id": dream_id,
                "category_id": category_id,
                "salience": 0.9,
                "status": "draft",
                "match_type": "direct",
                "fragments": f'[{{"text": {fragment_text!r}}}]'.replace("'", '"'),
                "deprecated": False,
            },
        )
        await session.commit()


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is required")
@pytest.mark.asyncio
async def test_concrete_fish_recall_survives_semantic_failure(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dream_id = await _create_dream(
        migrated_session_factory,
        title="Запретная рыба",
        raw_text="Рыба черного цвета, она очень красивая.",
    )
    ingestion_service = RagIngestionService(
        session_factory=migrated_session_factory,
        embedding_client=_StaticEmbeddingClient(),
    )
    await ingestion_service.index_dream(dream_id)

    query_service = RagQueryService(
        session_factory=migrated_session_factory,
        embedding_client=_StaticEmbeddingClient(),
    )
    query_service._expand_query_terms = AsyncMock(  # type: ignore[method-assign]
        return_value="сон с рыбой"
    )
    query_service._search_probes = AsyncMock(  # type: ignore[method-assign]
        side_effect=QueryEmbeddingError(503, len("сон с рыбой"))
    )

    result = await query_service.retrieve("сон с рыбой")

    assert isinstance(result, list)
    assert result[0].dream_id == dream_id
    assert result[0].relevance_score == 1.0
    assert result[0].matched_fragments == [
        FragmentMatch(
            text="Рыба черного цвета, она очень красивая",
            match_type="semantic",
            char_offset=0,
        )
    ]


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is required")
@pytest.mark.asyncio
async def test_matched_theme_fragments_are_conditioned_on_fish_query(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    fish_dream_id = await _create_dream(
        migrated_session_factory,
        title="Черная рыба",
        raw_text=(
            "Рыба черного цвета плыла в воде. Рядом со стеклянным лифтом стояла красная дверь."
        ),
    )
    unrelated_dream_id = await _create_dream(
        migrated_session_factory,
        title="Стеклянный лифт",
        raw_text="Красная дверь стояла рядом со стеклянным лифтом.",
    )
    await _attach_fragment(migrated_session_factory, fish_dream_id, "Рыба черного цвета")
    await _attach_fragment(
        migrated_session_factory,
        fish_dream_id,
        "красная дверь",
    )
    await _attach_fragment(
        migrated_session_factory,
        unrelated_dream_id,
        "Красная дверь",
    )

    ingestion_service = RagIngestionService(
        session_factory=migrated_session_factory,
        embedding_client=_StaticEmbeddingClient(),
    )
    await ingestion_service.index_dream(fish_dream_id)
    await ingestion_service.index_dream(unrelated_dream_id)

    query_service = RagQueryService(
        session_factory=migrated_session_factory,
        embedding_client=_StaticEmbeddingClient(),
    )
    query_service._expand_query_terms = AsyncMock(  # type: ignore[method-assign]
        return_value="найди черную рыбу"
    )

    result = await query_service.retrieve("найди черную рыбу")

    assert isinstance(result, list)
    by_id = {block.dream_id: block for block in result}
    fish_fragment_texts = {fragment.text for fragment in by_id[fish_dream_id].matched_fragments}
    assert "Рыба черного цвета" in fish_fragment_texts
    assert "красная дверь" not in fish_fragment_texts
    assert by_id[unrelated_dream_id].matched_fragments == []


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is required")
@pytest.mark.asyncio
async def test_vector_only_results_obey_semantic_floor_and_stricter_config(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    low_text = "A quiet red room with a wooden table."
    floor_text = "A quiet blue room with a stone table."
    high_text = "A quiet green room with a round table."
    query_text = "abstract signal"
    low_id = await _create_dream(
        migrated_session_factory,
        title="Low neighbor",
        raw_text=low_text,
    )
    floor_id = await _create_dream(
        migrated_session_factory,
        title="Floor neighbor",
        raw_text=floor_text,
    )
    high_id = await _create_dream(
        migrated_session_factory,
        title="High neighbor",
        raw_text=high_text,
    )
    vectors = {
        low_text: _embedding_with_cosine(0.39),
        floor_text: _embedding_with_cosine(0.4001),
        high_text: _embedding_with_cosine(0.60),
        query_text: _embedding_with_cosine(1.0),
    }
    embedding_client = _MappedEmbeddingClient(vectors)
    ingestion_service = RagIngestionService(
        session_factory=migrated_session_factory,
        embedding_client=embedding_client,
    )
    for dream_id in (low_id, floor_id, high_id):
        await ingestion_service.index_dream(dream_id)

    default_service = RagQueryService(
        session_factory=migrated_session_factory,
        embedding_client=embedding_client,
        relevance_threshold=0.20,
    )
    default_service._expand_query_terms = AsyncMock(  # type: ignore[method-assign]
        return_value=query_text
    )
    default_result = await default_service.retrieve(query_text)

    assert isinstance(default_result, list)
    assert {block.dream_id for block in default_result} == {floor_id, high_id}

    strict_service = RagQueryService(
        session_factory=migrated_session_factory,
        embedding_client=embedding_client,
        relevance_threshold=0.50,
    )
    strict_service._expand_query_terms = AsyncMock(  # type: ignore[method-assign]
        return_value=query_text
    )
    strict_result = await strict_service.retrieve(query_text)

    assert isinstance(strict_result, list)
    assert [block.dream_id for block in strict_result] == [high_id]


@pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY")
    or os.getenv("OPENAI_API_KEY", "").startswith("test-")
    or not os.getenv("TEST_DATABASE_URL"),
    reason=RAG_QUERY_SKIP_REASON,
)
@pytest.mark.preserve_openai_env
@pytest.mark.asyncio
async def test_retrieve_returns_evidence_blocks(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dream_text = (
        "I was climbing a spiral staircase through a lighthouse while waves crashed below. "
        "At the top I found my grandmother waiting beside a lantern."
    )
    dream_id = await _create_dream(
        migrated_session_factory,
        title="Lighthouse staircase dream",
        raw_text=dream_text,
    )
    await _attach_fragment(migrated_session_factory, dream_id, "spiral staircase")

    ingestion_service = RagIngestionService(session_factory=migrated_session_factory)
    await ingestion_service.index_dream(dream_id)

    query_service = RagQueryService(session_factory=migrated_session_factory)
    result = await query_service.retrieve("lighthouse staircase")

    assert isinstance(result, list)
    assert result
    assert isinstance(result[0], EvidenceBlock)
    assert result[0].dream_id == dream_id
    assert result[0].chunk_text == dream_text
    assert result[0].relevance_score >= 0.35
    assert (
        FragmentMatch(
            text="spiral staircase",
            match_type="semantic",
            char_offset=dream_text.index("spiral staircase"),
        )
        in result[0].matched_fragments
    )


@pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY")
    or os.getenv("OPENAI_API_KEY", "").startswith("test-")
    or not os.getenv("TEST_DATABASE_URL"),
    reason=RAG_QUERY_SKIP_REASON,
)
@pytest.mark.preserve_openai_env
@pytest.mark.asyncio
async def test_retrieve_returns_insufficient_evidence_for_zero_match(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dream_id = await _create_dream(
        migrated_session_factory,
        title="Forest dream",
        raw_text="I walked through a pine forest and crossed a narrow stream at dusk.",
    )

    ingestion_service = RagIngestionService(session_factory=migrated_session_factory)
    await ingestion_service.index_dream(dream_id)

    query_service = RagQueryService(
        session_factory=migrated_session_factory,
        relevance_threshold=0.95,
    )
    result = await query_service.retrieve("airport terminal departure gate")

    assert result == InsufficientEvidence(reason="No evidence met retrieval threshold")


@pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY")
    or os.getenv("OPENAI_API_KEY", "").startswith("test-")
    or not os.getenv("TEST_DATABASE_URL"),
    reason=RAG_QUERY_SKIP_REASON,
)
@pytest.mark.preserve_openai_env
@pytest.mark.asyncio
async def test_hybrid_search_returns_keyword_only_match(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dream_text = (
        "I found a moonkey hidden under the bed and wrote the word moonkey three times "
        "before the room dissolved into static."
    )
    dream_id = await _create_dream(
        migrated_session_factory,
        title="Moonkey dream",
        raw_text=dream_text,
    )

    ingestion_service = RagIngestionService(session_factory=migrated_session_factory)
    await ingestion_service.index_dream(dream_id)

    query_service = RagQueryService(session_factory=migrated_session_factory)
    result = await query_service.retrieve("moonkey")

    assert isinstance(result, list)
    assert result
    assert result[0].dream_id == dream_id
    assert result[0].chunk_text == dream_text
    assert result[0].relevance_score >= 0.35


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is required")
@pytest.mark.asyncio
async def test_health_stays_ok_when_complete_index_is_old(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with migrated_session_factory() as session:
        dream_id = (
            await session.execute(
                text(
                    """
                    INSERT INTO dream_entries (
                        source_doc_id,
                        date,
                        title,
                        raw_text,
                        word_count,
                        content_hash,
                        segmentation_confidence
                    )
                    VALUES (
                        :source_doc_id,
                        :date,
                        :title,
                        :raw_text,
                        :word_count,
                        :content_hash,
                        :segmentation_confidence
                    )
                    RETURNING id
                    """
                ),
                {
                    "source_doc_id": "doc-health-stale",
                    "date": datetime.now(timezone.utc).date(),
                    "title": "Stale health dream",
                    "raw_text": "A quiet dream used for health checks.",
                    "word_count": 7,
                    "content_hash": f"stale-hash-{uuid.uuid4()}",
                    "segmentation_confidence": "high",
                },
            )
        ).scalar_one()
        stale_timestamp = datetime.now(timezone.utc) - timedelta(hours=49)
        await session.execute(
            text(
                """
                INSERT INTO dream_chunks (
                    dream_id,
                    chunk_index,
                    chunk_text,
                    embedding,
                    created_at
                )
                VALUES (
                    :dream_id,
                    :chunk_index,
                    :chunk_text,
                    :embedding,
                    :created_at
                )
                """
            ),
            {
                "dream_id": dream_id,
                "chunk_index": 0,
                "chunk_text": "A quiet dream used for health checks.",
                "embedding": "[" + ",".join(["0"] * 1536) + "]",
                "created_at": stale_timestamp,
            },
        )
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=_reload_app()),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["index_last_updated"] == stale_timestamp.isoformat()
    assert payload["unindexed_dreams"] == 0
    assert payload["unindexed_notes"] == 0


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is required")
@pytest.mark.asyncio
async def test_health_degrades_when_dream_is_missing_index_chunks(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _create_dream(
        migrated_session_factory,
        title="Unindexed health dream",
        raw_text="A dream that has not reached the semantic index yet.",
    )

    async with AsyncClient(
        transport=ASGITransport(app=_reload_app()),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["index_last_updated"] is None
    assert payload["unindexed_dreams"] == 1
    assert payload["unindexed_notes"] == 0
