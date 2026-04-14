from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.models.annotation import AnnotationVersion
from app.models.dream import DreamEntry
from app.models.theme import DreamTheme, ThemeCategory
from app.services.taxonomy import TaxonomyService

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
async def migrated_session() -> AsyncSession:
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
        async with session_factory() as session:
            yield session
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_category_defaults_to_suggested(migrated_session: AsyncSession) -> None:
    category_id = await TaxonomyService.create_category(
        migrated_session,
        name="liminal_space",
        description="Threshold imagery and transition spaces.",
    )

    category = await migrated_session.get(ThemeCategory, category_id)

    assert category is not None
    assert category.name == "liminal_space"
    assert category.description == "Threshold imagery and transition spaces."
    assert category.status == "suggested"


@pytest.mark.asyncio
async def test_approve_category_writes_annotation_version(
    migrated_session: AsyncSession,
) -> None:
    category_id = await TaxonomyService.create_category(
        migrated_session,
        name="ancestor",
        description="Ancestral presence or inherited memory.",
    )

    await TaxonomyService.approve_category(migrated_session, category_id)

    category = await migrated_session.get(ThemeCategory, category_id)
    result = await migrated_session.execute(
        select(AnnotationVersion)
        .where(
            AnnotationVersion.entity_type == "theme_category",
            AnnotationVersion.entity_id == category_id,
        )
        .order_by(AnnotationVersion.created_at.asc())
    )
    versions = result.scalars().all()

    assert category is not None
    assert category.status == "active"
    assert len(versions) == 2
    assert versions[-1].snapshot["entity_type"] == "theme_category"
    assert versions[-1].snapshot["entity_id"] == str(category_id)
    assert versions[-1].snapshot["name"] == "ancestor"
    assert versions[-1].snapshot["description"] == "Ancestral presence or inherited memory."
    assert versions[-1].snapshot["status"] == "suggested"
    assert versions[-1].snapshot["status_before"] == "suggested"
    assert versions[-1].snapshot["status_after"] == "active"
    assert versions[-1].snapshot["changed_by"] == "system"
    assert versions[-1].changed_by == "system"


@pytest.mark.asyncio
async def test_deprecate_category_soft_delete(migrated_session: AsyncSession) -> None:
    category_id = await TaxonomyService.create_category(
        migrated_session,
        name="labyrinth",
        description="Recursive paths, loops, and maze structures.",
    )
    await TaxonomyService.approve_category(migrated_session, category_id)

    dream = DreamEntry(
        source_doc_id="doc-1",
        date=None,
        title="A dream of corridors",
        raw_text="I kept turning through corridors that looked the same.",
        word_count=10,
        content_hash="dream-taxonomy-hash",
        segmentation_confidence="high",
    )
    migrated_session.add(dream)
    await migrated_session.flush()

    dream_theme = DreamTheme(
        dream_id=dream.id,
        category_id=category_id,
        salience=0.8,
        status="draft",
        match_type="symbolic",
        fragments=[{"text": "corridors that looked the same"}],
    )
    migrated_session.add(dream_theme)
    await migrated_session.commit()

    await TaxonomyService.deprecate_category(migrated_session, category_id)
    await migrated_session.refresh(dream_theme)

    category = await migrated_session.get(ThemeCategory, category_id)

    assert category is not None
    assert category.status == "deprecated"
    assert dream_theme.category_id == category_id
    assert dream_theme.deprecated is True


@pytest.mark.asyncio
async def test_seed_categories_present(migrated_session: AsyncSession) -> None:
    result = await migrated_session.execute(
        select(ThemeCategory).where(ThemeCategory.status == "active")
    )
    active_categories = result.scalars().all()
    active_names = {category.name for category in active_categories}

    assert len(active_categories) >= 5
    assert {
        "separation",
        "mother_figure",
        "shadow",
        "inner_child",
        "transformation",
        "water",
        "flying",
        "pursuit",
        "house_rooms",
        "death_rebirth",
    }.issubset(active_names)
