from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import date, timezone
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
            source_doc_id="doc-dreams-api",
            date=dream_date,
            title=title,
            raw_text=raw_text,
            word_count=len(raw_text.split()),
            content_hash=f"dreams-api-{uuid.uuid4()}",
            segmentation_confidence="high",
        )
        session.add(dream)
        await session.commit()
        await session.refresh(dream)
        return dream


async def _attach_theme(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    dream_id: uuid.UUID,
) -> None:
    async with session_factory() as session:
        category = ThemeCategory(
            name=f"dreams-api-category-{uuid.uuid4()}",
            description="Theme for dreams API test",
            status="active",
        )
        session.add(category)
        await session.flush()
        session.add(
            DreamTheme(
                dream_id=dream_id,
                category_id=category.id,
                salience=0.84,
                status="draft",
                match_type="symbolic",
                fragments=[{"text": "bright river"}],
                deprecated=False,
            )
        )
        await session.commit()


def _auth_headers() -> dict[str, str]:
    return {"X-API-Key": os.environ["SECRET_KEY"]}


@pytest.mark.anyio
async def test_post_sync_returns_202(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    del migrated_session_factory

    async with AsyncClient(
        transport=ASGITransport(app=_load_app()),
        base_url="http://testserver",
    ) as client:
        response = await client.post("/sync", headers=_auth_headers())

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert uuid.UUID(body["job_id"])


@pytest.mark.anyio
async def test_post_sync_requires_auth(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    del migrated_session_factory

    async with AsyncClient(
        transport=ASGITransport(app=_load_app()),
        base_url="http://testserver",
    ) as client:
        response = await client.post("/sync")

    assert response.status_code == 401


@pytest.mark.anyio
async def test_get_dreams_paginated(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first = await _create_dream(
        migrated_session_factory,
        title="First listed dream",
        raw_text="Dream text for the first listed dream.",
        dream_date=date(2026, 4, 1),
    )
    second = await _create_dream(
        migrated_session_factory,
        title="Second listed dream",
        raw_text="Dream text for the second listed dream.",
        dream_date=date(2026, 4, 2),
    )
    third = await _create_dream(
        migrated_session_factory,
        title="Third listed dream",
        raw_text="Dream text for the third listed dream.",
        dream_date=date(2026, 4, 3),
    )

    async with AsyncClient(
        transport=ASGITransport(app=_load_app()),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/dreams?page=1&page_size=2",
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": str(third.id),
                "date": "2026-04-03",
                "title": "Third listed dream",
                "word_count": third.word_count,
                "source_doc_id": "doc-dreams-api",
                "created_at": third.created_at.astimezone(timezone.utc).isoformat(),
            },
            {
                "id": str(second.id),
                "date": "2026-04-02",
                "title": "Second listed dream",
                "word_count": second.word_count,
                "source_doc_id": "doc-dreams-api",
                "created_at": second.created_at.astimezone(timezone.utc).isoformat(),
            },
        ],
        "total": 3,
        "page": 1,
    }
    assert str(first.id) not in {item["id"] for item in response.json()["items"]}


@pytest.mark.anyio
async def test_get_dream_by_id(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dream = await _create_dream(
        migrated_session_factory,
        title="Detailed dream",
        raw_text="A bright river moved through the house at dawn.",
        dream_date=date(2026, 4, 4),
    )
    await _attach_theme(migrated_session_factory, dream_id=dream.id)

    async with AsyncClient(
        transport=ASGITransport(app=_load_app()),
        base_url="http://testserver",
    ) as client:
        missing_response = await client.get(
            f"/dreams/{uuid.uuid4()}",
            headers=_auth_headers(),
        )
        response = await client.get(
            f"/dreams/{dream.id}",
            headers=_auth_headers(),
        )

    assert missing_response.status_code == 404
    assert response.status_code == 200
    assert response.json() == {
        "id": str(dream.id),
        "date": "2026-04-04",
        "title": "Detailed dream",
        "raw_text": "A bright river moved through the house at dawn.",
        "word_count": dream.word_count,
        "source_doc_id": "doc-dreams-api",
        "created_at": dream.created_at.astimezone(timezone.utc).isoformat(),
        "metadata": {
            "segmentation_confidence": "high",
            "theme_count": 1,
        },
    }
