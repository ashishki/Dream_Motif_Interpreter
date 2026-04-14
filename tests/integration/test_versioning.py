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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.models.annotation import AnnotationVersion
from app.models.dream import DreamEntry
from app.models.theme import DreamTheme, ThemeCategory
from app.services.versioning import build_dream_theme_transition_version

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INTERPRETATION_NOTE = (
    "These theme assignments are computational interpretations, not authoritative conclusions."
)


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
    sys.modules.pop("app.api.versioning", None)
    sys.modules.pop("app.api.search", None)
    sys.modules.pop("app.api.themes", None)
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
            source_doc_id="doc-versioning-api",
            date=dream_date,
            title=title,
            raw_text=raw_text,
            word_count=len(raw_text.split()),
            content_hash=f"versioning-api-{uuid.uuid4()}",
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
            name=name or f"versioning-category-{uuid.uuid4()}",
            description="Theme for versioning tests",
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
    status: str = "draft",
    salience: float = 0.75,
    match_type: str = "symbolic",
    fragment_text: str = "river crossing",
) -> DreamTheme:
    async with session_factory() as session:
        theme = DreamTheme(
            dream_id=dream_id,
            category_id=category_id,
            salience=salience,
            status=status,
            match_type=match_type,
            fragments=[{"text": fragment_text, "justification": "theme cue"}],
            deprecated=False,
        )
        session.add(theme)
        await session.commit()
        await session.refresh(theme)
        return theme


def _auth_headers() -> dict[str, str]:
    return {"X-API-Key": os.environ["SECRET_KEY"]}


@pytest.mark.anyio
async def test_history_returns_all_versions(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dream = await _create_dream(
        migrated_session_factory,
        title="Dream with history",
        raw_text="I crossed a river and then returned over the same bridge.",
        dream_date=date(2026, 4, 14),
    )
    category = await _create_category(migrated_session_factory)
    theme = await _attach_theme(
        migrated_session_factory,
        dream_id=dream.id,
        category_id=category.id,
        fragment_text="crossed a river",
    )

    async with migrated_session_factory() as session:
        session.add(
            build_dream_theme_transition_version(
                theme=theme,
                to_status="confirmed",
                changed_by="user",
            )
        )
        await session.flush()
        theme.status = "confirmed"
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=_load_app()),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/dreams/{dream.id}/themes/history",
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    payload = response.json()

    assert payload["dream_id"] == str(dream.id)
    assert len(payload["items"]) == 1
    assert payload["items"][0]["entity_type"] == "dream_theme"
    assert payload["items"][0]["entity_id"] == str(theme.id)
    assert payload["items"][0]["snapshot"]["status_before"] == "draft"
    assert payload["items"][0]["snapshot"]["status_after"] == "confirmed"
    assert payload["items"][0]["created_at"]


@pytest.mark.anyio
async def test_rollback_restores_prior_state(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dream = await _create_dream(
        migrated_session_factory,
        title="Dream to roll back",
        raw_text="A silver ladder led upward through the old house.",
        dream_date=date(2026, 4, 14),
    )
    category = await _create_category(migrated_session_factory)
    theme = await _attach_theme(
        migrated_session_factory,
        dream_id=dream.id,
        category_id=category.id,
        salience=0.41,
        match_type="literal",
        fragment_text="silver ladder",
    )

    async with AsyncClient(
        transport=ASGITransport(app=_load_app()),
        base_url="http://testserver",
    ) as client:
        confirm_response = await client.patch(
            f"/dreams/{dream.id}/themes/{theme.id}/confirm",
            headers=_auth_headers(),
        )

    assert confirm_response.status_code == 200

    async with migrated_session_factory() as session:
        version_result = await session.execute(
            select(AnnotationVersion)
            .where(
                AnnotationVersion.entity_type == "dream_theme",
                AnnotationVersion.entity_id == theme.id,
            )
            .order_by(AnnotationVersion.created_at.asc())
        )
        version = version_result.scalars().all()[-1]

    async with AsyncClient(
        transport=ASGITransport(app=_load_app()),
        base_url="http://testserver",
    ) as client:
        rollback_response = await client.post(
            f"/dreams/{dream.id}/themes/{theme.id}/rollback/{version.id}",
            headers=_auth_headers(),
        )

    assert rollback_response.status_code == 200
    assert rollback_response.json() == {
        "dream_id": str(dream.id),
        "theme_id": str(theme.id),
        "category_id": str(category.id),
        "salience": 0.41,
        "match_type": "literal",
        "status": "draft",
        "fragments": [{"text": "silver ladder", "justification": "theme cue"}],
        "deprecated": False,
        "interpretation_note": INTERPRETATION_NOTE,
    }

    async with migrated_session_factory() as session:
        restored = await session.get(DreamTheme, theme.id)

    assert restored is not None
    assert restored.status == "draft"
    assert restored.salience == 0.41
    assert restored.match_type == "literal"
    assert restored.fragments == [{"text": "silver ladder", "justification": "theme cue"}]
    assert restored.deprecated is False


@pytest.mark.anyio
async def test_rollback_appends_version_record(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dream = await _create_dream(
        migrated_session_factory,
        title="Dream with append-only rollback",
        raw_text="The bridge appeared twice, once in rain and once in sunlight.",
        dream_date=date(2026, 4, 14),
    )
    category = await _create_category(migrated_session_factory)
    theme = await _attach_theme(
        migrated_session_factory,
        dream_id=dream.id,
        category_id=category.id,
        salience=0.66,
        match_type="symbolic",
        fragment_text="bridge appeared twice",
    )

    async with AsyncClient(
        transport=ASGITransport(app=_load_app()),
        base_url="http://testserver",
    ) as client:
        confirm_response = await client.patch(
            f"/dreams/{dream.id}/themes/{theme.id}/confirm",
            headers=_auth_headers(),
        )

    assert confirm_response.status_code == 200

    async with migrated_session_factory() as session:
        version_result = await session.execute(
            select(AnnotationVersion)
            .where(
                AnnotationVersion.entity_type == "dream_theme",
                AnnotationVersion.entity_id == theme.id,
            )
            .order_by(AnnotationVersion.created_at.asc())
        )
        before_versions = version_result.scalars().all()
        target_version_id = before_versions[-1].id

    async with AsyncClient(
        transport=ASGITransport(app=_load_app()),
        base_url="http://testserver",
    ) as client:
        rollback_response = await client.post(
            f"/dreams/{dream.id}/themes/{theme.id}/rollback/{target_version_id}",
            headers=_auth_headers(),
        )

    assert rollback_response.status_code == 200

    async with migrated_session_factory() as session:
        version_result = await session.execute(
            select(AnnotationVersion)
            .where(
                AnnotationVersion.entity_type == "dream_theme",
                AnnotationVersion.entity_id == theme.id,
            )
            .order_by(AnnotationVersion.created_at.asc())
        )
        after_versions = version_result.scalars().all()

    assert len(after_versions) == len(before_versions) + 1
    rollback_version = after_versions[-1]
    assert rollback_version.snapshot["status"] == "draft"
    assert rollback_version.snapshot["status_before"] == "confirmed"
    assert rollback_version.snapshot["status_after"] == "draft"
    assert rollback_version.changed_by == "user"
