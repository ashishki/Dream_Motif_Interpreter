from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import date, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.models.dream import DreamEntry
from app.models.theme import DreamTheme, ThemeCategory

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INTERPRETATION_NOTE = "These are computational patterns, not authoritative interpretations."


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
    sys.modules.pop("app.api.patterns", None)
    sys.modules.pop("app.api.search", None)
    sys.modules.pop("app.api.dreams", None)
    sys.modules.pop("app.main", None)

    from app.main import app

    return app


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
            source_doc_id="doc-patterns-api",
            date=dream_date,
            title=title,
            raw_text=raw_text,
            word_count=len(raw_text.split()),
            content_hash=f"patterns-api-{uuid.uuid4()}",
            segmentation_confidence="high",
        )
        session.add(dream)
        await session.commit()
        await session.refresh(dream)
        return dream


async def _create_category(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    name: str,
) -> ThemeCategory:
    async with session_factory() as session:
        category = ThemeCategory(
            name=f"{name}-{uuid.uuid4()}",
            description=f"{name} category for pattern API tests",
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
    match_type: str = "symbolic",
) -> DreamTheme:
    async with session_factory() as session:
        dream_theme = DreamTheme(
            dream_id=dream_id,
            category_id=category_id,
            salience=salience,
            status=status,
            match_type=match_type,
            fragments=[],
            deprecated=False,
        )
        session.add(dream_theme)
        await session.commit()
        await session.refresh(dream_theme)
        return dream_theme


def _auth_headers() -> dict[str, str]:
    return {"X-API-Key": os.environ["SECRET_KEY"]}


def _assert_common_pattern_fields(body: dict[str, object]) -> None:
    assert body["interpretation_note"] == INTERPRETATION_NOTE
    assert isinstance(body["generated_at"], str)
    datetime.fromisoformat(str(body["generated_at"]))


@pytest.mark.anyio
async def test_recurring_patterns_sorted_by_count(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    flying = await _create_category(migrated_session_factory, name="flying")
    ocean = await _create_category(migrated_session_factory, name="ocean")
    bridge = await _create_category(migrated_session_factory, name="bridge")
    discarded = await _create_category(migrated_session_factory, name="discarded")
    dreams = [
        await _create_dream(
            migrated_session_factory,
            title=f"Pattern dream {index}",
            raw_text=f"Dream {index} contains archive pattern material.",
            dream_date=date(2026, 4, index),
        )
        for index in range(1, 5)
    ]

    await _attach_theme(
        migrated_session_factory,
        dream_id=dreams[0].id,
        category_id=flying.id,
        salience=0.9,
        status="confirmed",
    )
    await _attach_theme(
        migrated_session_factory,
        dream_id=dreams[1].id,
        category_id=flying.id,
        salience=0.8,
        status="confirmed",
    )
    await _attach_theme(
        migrated_session_factory,
        dream_id=dreams[2].id,
        category_id=flying.id,
        salience=0.7,
        status="confirmed",
    )
    await _attach_theme(
        migrated_session_factory,
        dream_id=dreams[0].id,
        category_id=ocean.id,
        salience=0.6,
        status="confirmed",
    )
    await _attach_theme(
        migrated_session_factory,
        dream_id=dreams[3].id,
        category_id=ocean.id,
        salience=0.5,
        status="confirmed",
    )
    await _attach_theme(
        migrated_session_factory,
        dream_id=dreams[1].id,
        category_id=bridge.id,
        salience=0.4,
        status="confirmed",
    )
    await _attach_theme(
        migrated_session_factory,
        dream_id=dreams[3].id,
        category_id=discarded.id,
        salience=0.3,
        status="draft",
    )
    await _attach_theme(
        migrated_session_factory,
        dream_id=dreams[2].id,
        category_id=discarded.id,
        salience=0.2,
        status="rejected",
    )

    async with AsyncClient(
        transport=ASGITransport(app=_load_app()),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/patterns/recurring", headers=_auth_headers())

    assert response.status_code == 200
    body = response.json()
    _assert_common_pattern_fields(body)
    assert body["patterns"] == [
        {
            "category_id": str(flying.id),
            "name": flying.name,
            "count": 3,
            "percentage_of_dreams": 0.75,
        },
        {
            "category_id": str(ocean.id),
            "name": ocean.name,
            "count": 2,
            "percentage_of_dreams": 0.5,
        },
        {
            "category_id": str(bridge.id),
            "name": bridge.name,
            "count": 1,
            "percentage_of_dreams": 0.25,
        },
    ]


@pytest.mark.anyio
async def test_co_occurrence_minimum_threshold(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    flying = await _create_category(migrated_session_factory, name="co-flying")
    ocean = await _create_category(migrated_session_factory, name="co-ocean")
    bridge = await _create_category(migrated_session_factory, name="co-bridge")
    dreams = [
        await _create_dream(
            migrated_session_factory,
            title=f"Co-occurrence dream {index}",
            raw_text=f"Dream {index} contains repeated pairings.",
            dream_date=date(2026, 4, index),
        )
        for index in range(1, 5)
    ]

    for dream in dreams[:2]:
        await _attach_theme(
            migrated_session_factory,
            dream_id=dream.id,
            category_id=flying.id,
            salience=0.8,
            status="confirmed",
        )
        await _attach_theme(
            migrated_session_factory,
            dream_id=dream.id,
            category_id=ocean.id,
            salience=0.7,
            status="confirmed",
        )

    await _attach_theme(
        migrated_session_factory,
        dream_id=dreams[2].id,
        category_id=flying.id,
        salience=0.6,
        status="confirmed",
    )
    await _attach_theme(
        migrated_session_factory,
        dream_id=dreams[2].id,
        category_id=bridge.id,
        salience=0.5,
        status="confirmed",
    )
    await _attach_theme(
        migrated_session_factory,
        dream_id=dreams[3].id,
        category_id=ocean.id,
        salience=0.4,
        status="draft",
    )
    await _attach_theme(
        migrated_session_factory,
        dream_id=dreams[3].id,
        category_id=bridge.id,
        salience=0.3,
        status="confirmed",
    )

    async with AsyncClient(
        transport=ASGITransport(app=_load_app()),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/patterns/co-occurrence", headers=_auth_headers())

    assert response.status_code == 200
    body = response.json()
    _assert_common_pattern_fields(body)
    assert body["pairs"] == [
        {
            "category_ids": sorted((str(flying.id), str(ocean.id))),
            "count": 2,
        }
    ]


@pytest.mark.anyio
async def test_theme_timeline_sorted_by_date(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ladder = await _create_category(migrated_session_factory, name="ladder")
    other = await _create_category(migrated_session_factory, name="timeline-other")
    dream_specs = [
        ("Late ladder dream", date(2026, 4, 18), 0.33),
        ("Early ladder dream", date(2026, 4, 2), 0.91),
        ("Middle ladder dream", date(2026, 4, 11), 0.57),
    ]

    dreams = [
        await _create_dream(
            migrated_session_factory,
            title=title,
            raw_text=f"{title} includes ladder imagery.",
            dream_date=dream_date,
        )
        for title, dream_date, _ in dream_specs
    ]

    for dream, (_, _, salience) in zip(dreams, dream_specs):
        await _attach_theme(
            migrated_session_factory,
            dream_id=dream.id,
            category_id=ladder.id,
            salience=salience,
            status="confirmed",
        )

    await _attach_theme(
        migrated_session_factory,
        dream_id=dreams[0].id,
        category_id=other.id,
        salience=0.4,
        status="confirmed",
    )
    await _attach_theme(
        migrated_session_factory,
        dream_id=dreams[1].id,
        category_id=ladder.id,
        salience=0.1,
        status="draft",
    )

    async with AsyncClient(
        transport=ASGITransport(app=_load_app()),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/patterns/timeline?theme_id={ladder.id}",
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    body = response.json()
    _assert_common_pattern_fields(body)
    assert body["theme_id"] == str(ladder.id)
    assert body["timeline"] == [
        {"date": "2026-04-02", "salience": 0.91},
        {"date": "2026-04-11", "salience": 0.57},
        {"date": "2026-04-18", "salience": 0.33},
    ]


@pytest.mark.anyio
async def test_patterns_include_disclaimer(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    category = await _create_category(migrated_session_factory, name="disclaimer")
    dream = await _create_dream(
        migrated_session_factory,
        title="Disclaimer dream",
        raw_text="A single dream is enough to check response framing.",
        dream_date=date(2026, 4, 7),
    )
    await _attach_theme(
        migrated_session_factory,
        dream_id=dream.id,
        category_id=category.id,
        salience=0.7,
        status="confirmed",
    )

    async with AsyncClient(
        transport=ASGITransport(app=_load_app()),
        base_url="http://testserver",
    ) as client:
        recurring = await client.get("/patterns/recurring", headers=_auth_headers())
        co_occurrence = await client.get("/patterns/co-occurrence", headers=_auth_headers())
        timeline = await client.get(
            f"/patterns/timeline?theme_id={category.id}",
            headers=_auth_headers(),
        )

    assert recurring.status_code == 200
    assert co_occurrence.status_code == 200
    assert timeline.status_code == 200

    for response in (recurring, co_occurrence, timeline):
        _assert_common_pattern_fields(response.json())
