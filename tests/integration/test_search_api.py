from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import date
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.dream import DreamEntry
from app.models.theme import DreamTheme, ThemeCategory
from app.retrieval.query import EvidenceBlock, InsufficientEvidence

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config() -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    return config


async def _reset_public_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
        await connection.exec_driver_sql("CREATE SCHEMA public")
        await connection.exec_driver_sql("GRANT ALL ON SCHEMA public TO public")


def _load_app():
    sys.modules.pop("app.api.search", None)
    sys.modules.pop("app.api.dreams", None)
    sys.modules.pop("app.main", None)

    from app.main import app

    return app


class StubRagQueryService:
    def __init__(self, result: list[EvidenceBlock] | InsufficientEvidence) -> None:
        self._result = result

    async def retrieve(self, query: str) -> list[EvidenceBlock] | InsufficientEvidence:
        del query
        return self._result


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


async def _create_dream(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    title: str,
    raw_text: str,
    dream_date: date,
) -> DreamEntry:
    async with session_factory() as session:
        dream = DreamEntry(
            source_doc_id="doc-search-api",
            date=dream_date,
            title=title,
            raw_text=raw_text,
            word_count=len(raw_text.split()),
            content_hash=f"search-api-{uuid.uuid4()}",
            segmentation_confidence="high",
        )
        session.add(dream)
        await session.commit()
        await session.refresh(dream)
        return dream


async def _create_category(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    name: str | None = None,
) -> ThemeCategory:
    async with session_factory() as session:
        category = ThemeCategory(
            name=f"{name}-{uuid.uuid4()}" if name is not None else f"search-api-category-{uuid.uuid4()}",
            description="Theme for search API tests",
            status="active",
        )
        session.add(category)
        await session.commit()
        await session.refresh(category)
        return category


async def _attach_theme(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    dream_id: uuid.UUID,
    category_id: uuid.UUID,
    salience: float,
    status: str,
    match_type: str,
    fragment_text: str,
) -> DreamTheme:
    async with session_factory() as session:
        dream_theme = DreamTheme(
            dream_id=dream_id,
            category_id=category_id,
            salience=salience,
            status=status,
            match_type=match_type,
            fragments=[{"text": fragment_text}],
            deprecated=False,
        )
        session.add(dream_theme)
        await session.commit()
        await session.refresh(dream_theme)
        return dream_theme


def _auth_headers() -> dict[str, str]:
    return {"X-API-Key": os.environ["SECRET_KEY"]}


def _install_stub_query_service(
    monkeypatch: pytest.MonkeyPatch,
    *,
    result: list[EvidenceBlock] | InsufficientEvidence,
) -> None:
    import app.api.search as search_api

    monkeypatch.setattr(search_api, "_get_rag_query_service", lambda: StubRagQueryService(result))


@pytest.mark.anyio
async def test_search_returns_ranked_results(
    migrated_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    category = await _create_category(migrated_session_factory)
    dreams = [
        await _create_dream(
            migrated_session_factory,
            title=f"Flying dream {index}",
            raw_text=f"Dream {index} about flying through bright air.",
            dream_date=date(2026, 4, index),
        )
        for index in range(1, 7)
    ]
    for dream in dreams:
        await _attach_theme(
            migrated_session_factory,
            dream_id=dream.id,
            category_id=category.id,
            salience=0.5,
            status="confirmed",
            match_type="symbolic",
            fragment_text="flying through bright air",
        )

    app = _load_app()
    _install_stub_query_service(
        monkeypatch,
        result=[
            EvidenceBlock(
                dream_id=dream.id,
                date=dream.date,
                chunk_text=dream.raw_text,
                relevance_score=0.95 - (index * 0.05),
                matched_fragments=["flying through bright air"],
            )
            for index, dream in enumerate(dreams)
        ],
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/search?q=flying", headers=_auth_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "flying"
    assert body["expanded_terms"] == ["flying"]
    assert len(body["results"]) == 5
    assert [item["dream_id"] for item in body["results"]] == [str(dream.id) for dream in dreams[:5]]
    for item in body["results"]:
        assert set(item) == {
            "dream_id",
            "date",
            "matched_fragments",
            "relevance_score",
            "theme_matches",
        }
        assert item["matched_fragments"] == ["flying through bright air"]
        assert item["theme_matches"] == [
            {
                "category_id": str(category.id),
                "match_type": "symbolic",
                "status": "confirmed",
            }
        ]


@pytest.mark.anyio
async def test_search_returns_insufficient_evidence(
    migrated_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del migrated_session_factory
    app = _load_app()
    _install_stub_query_service(
        monkeypatch,
        result=InsufficientEvidence(reason="No evidence met retrieval threshold"),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/search?q=no%20match", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json() == {
        "result": "insufficient_evidence",
        "query": "no match",
        "expanded_terms": ["no match", "no", "match"],
    }


@pytest.mark.anyio
async def test_search_with_theme_filter(
    migrated_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matching_category = await _create_category(migrated_session_factory, name="separation")
    other_category = await _create_category(migrated_session_factory, name="other")
    confirmed_dream = await _create_dream(
        migrated_session_factory,
        title="Confirmed separation dream",
        raw_text="A separation dream with a train platform goodbye.",
        dream_date=date(2026, 4, 10),
    )
    draft_dream = await _create_dream(
        migrated_session_factory,
        title="Draft separation dream",
        raw_text="Another separation dream with a train platform goodbye.",
        dream_date=date(2026, 4, 11),
    )

    await _attach_theme(
        migrated_session_factory,
        dream_id=confirmed_dream.id,
        category_id=matching_category.id,
        salience=0.9,
        status="confirmed",
        match_type="narrative",
        fragment_text="train platform goodbye",
    )
    await _attach_theme(
        migrated_session_factory,
        dream_id=draft_dream.id,
        category_id=matching_category.id,
        salience=0.8,
        status="draft",
        match_type="narrative",
        fragment_text="train platform goodbye",
    )
    await _attach_theme(
        migrated_session_factory,
        dream_id=draft_dream.id,
        category_id=other_category.id,
        salience=0.4,
        status="confirmed",
        match_type="symbolic",
        fragment_text="rail station",
    )

    app = _load_app()
    _install_stub_query_service(
        monkeypatch,
        result=[
            EvidenceBlock(
                dream_id=confirmed_dream.id,
                date=confirmed_dream.date,
                chunk_text=confirmed_dream.raw_text,
                relevance_score=0.92,
                matched_fragments=["train platform goodbye"],
            ),
            EvidenceBlock(
                dream_id=draft_dream.id,
                date=draft_dream.date,
                chunk_text=draft_dream.raw_text,
                relevance_score=0.89,
                matched_fragments=["train platform goodbye"],
            ),
        ],
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/search?q=separation&theme_ids={matching_category.id}",
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    body = response.json()
    assert [item["dream_id"] for item in body["results"]] == [str(confirmed_dream.id)]
    assert body["results"][0]["theme_matches"] == [
        {
            "category_id": str(matching_category.id),
            "match_type": "narrative",
            "status": "confirmed",
        }
    ]


@pytest.mark.anyio
async def test_get_dream_themes_sorted_by_salience(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dream = await _create_dream(
        migrated_session_factory,
        title="Layered theme dream",
        raw_text="A wolf, a bridge, and a lantern all appear in sequence.",
        dream_date=date(2026, 4, 12),
    )
    highest = await _create_category(migrated_session_factory, name="highest")
    middle = await _create_category(migrated_session_factory, name="middle")
    lowest = await _create_category(migrated_session_factory, name="lowest")

    await _attach_theme(
        migrated_session_factory,
        dream_id=dream.id,
        category_id=middle.id,
        salience=0.65,
        status="draft",
        match_type="symbolic",
        fragment_text="bridge",
    )
    await _attach_theme(
        migrated_session_factory,
        dream_id=dream.id,
        category_id=highest.id,
        salience=0.95,
        status="confirmed",
        match_type="narrative",
        fragment_text="wolf",
    )
    await _attach_theme(
        migrated_session_factory,
        dream_id=dream.id,
        category_id=lowest.id,
        salience=0.22,
        status="confirmed",
        match_type="emotional",
        fragment_text="lantern",
    )

    async with AsyncClient(
        transport=ASGITransport(app=_load_app()),
        base_url="http://testserver",
    ) as client:
        response = await client.get(f"/dreams/{dream.id}/themes", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json() == {
        "dream_id": str(dream.id),
        "themes": [
            {
                "category_id": str(highest.id),
                "salience": 0.95,
                "match_type": "narrative",
                "status": "confirmed",
                "fragments": [{"text": "wolf"}],
            },
            {
                "category_id": str(middle.id),
                "salience": 0.65,
                "match_type": "symbolic",
                "status": "draft",
                "fragments": [{"text": "bridge"}],
            },
            {
                "category_id": str(lowest.id),
                "salience": 0.22,
                "match_type": "emotional",
                "status": "confirmed",
                "fragments": [{"text": "lantern"}],
            },
        ],
    }
