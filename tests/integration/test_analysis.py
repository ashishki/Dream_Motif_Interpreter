from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.llm.grounder import GroundedTheme
from app.llm.theme_extractor import ThemeAssignment
from app.models.annotation import AnnotationVersion
from app.models.dream import DreamEntry
from app.models.theme import DreamTheme, ThemeCategory
from app.services.analysis import AnalysisService

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


class StubThemeExtractor:
    async def extract(
        self,
        dream_entry: DreamEntry,
        categories: list[ThemeCategory],
    ) -> list[ThemeAssignment]:
        del dream_entry
        return [
            ThemeAssignment(
                category_id=categories[0].id,
                salience=0.91,
                match_type="literal",
                justification="Starter category matched in test double.",
            ),
            ThemeAssignment(
                category_id=categories[1].id,
                salience=0.74,
                match_type="semantic",
                justification="Second starter category matched in test double.",
            ),
        ]


class StubGrounder:
    async def ground(
        self,
        dream_entry: DreamEntry,
        theme_assignments: list[ThemeAssignment],
    ) -> list[GroundedTheme]:
        raw_text = dream_entry.raw_text
        fragments = [
            {
                "text": "water",
                "start_offset": raw_text.index("water"),
                "end_offset": raw_text.index("water") + len("water"),
                "match_type": "literal",
                "verified": True,
            },
            {
                "text": "mother called",
                "start_offset": raw_text.index("mother called"),
                "end_offset": raw_text.index("mother called") + len("mother called"),
                "match_type": "semantic",
                "verified": False,
            },
        ]
        return [
            GroundedTheme(
                category_id=theme_assignments[0].category_id,
                salience=0.96,
                fragments=[fragments[0]],
            ),
            GroundedTheme(
                category_id=theme_assignments[1].category_id,
                salience=0.83,
                fragments=[fragments[1]],
            ),
        ]


class SequencedGrounder:
    def __init__(self) -> None:
        self.calls = 0

    async def ground(
        self,
        dream_entry: DreamEntry,
        theme_assignments: list[ThemeAssignment],
    ) -> list[GroundedTheme]:
        raw_text = dream_entry.raw_text
        fragment_text = "water" if self.calls == 0 else "old house"
        self.calls += 1
        fragment = {
            "text": fragment_text,
            "start_offset": raw_text.index(fragment_text),
            "end_offset": raw_text.index(fragment_text) + len(fragment_text),
            "match_type": "literal",
            "verified": True,
        }
        return [
            GroundedTheme(
                category_id=theme_assignments[0].category_id,
                salience=0.61 + (0.2 * self.calls),
                fragments=[fragment],
            ),
            GroundedTheme(
                category_id=theme_assignments[1].category_id,
                salience=0.51 + (0.2 * self.calls),
                fragments=[fragment],
            ),
        ]


@pytest.mark.asyncio
async def test_analysis_saves_draft_themes(migrated_session: AsyncSession) -> None:
    dream = DreamEntry(
        source_doc_id="doc-1",
        date=None,
        title="Dream for analysis",
        raw_text="I moved through water in my old house while my mother called from upstairs.",
        word_count=14,
        content_hash=f"analysis-hash-{uuid.uuid4()}",
        segmentation_confidence="high",
    )
    migrated_session.add(dream)
    await migrated_session.commit()

    service = AnalysisService(
        theme_extractor=StubThemeExtractor(),
        grounder=StubGrounder(),
    )
    assignments = await service.analyse_dream(dream.id, migrated_session)

    result = await migrated_session.execute(
        select(DreamTheme)
        .where(DreamTheme.dream_id == dream.id)
        .order_by(DreamTheme.created_at.asc())
    )
    stored_themes = result.scalars().all()
    version_result = await migrated_session.execute(
        select(AnnotationVersion).where(AnnotationVersion.entity_type == "dream_theme")
    )
    versions = version_result.scalars().all()

    assert len(assignments) == 2
    assert len(stored_themes) == 2
    assert all(theme.status == "draft" for theme in stored_themes)
    assert all(theme.fragments for theme in stored_themes)
    assert all(theme.deprecated is False for theme in stored_themes)
    assert {theme.category_id for theme in stored_themes} == {
        assignment.category_id for assignment in assignments
    }
    assert len(versions) == 2


@pytest.mark.asyncio
async def test_grounded_themes_have_fragments(migrated_session: AsyncSession) -> None:
    dream = DreamEntry(
        source_doc_id="doc-2",
        date=None,
        title="Dream for grounded analysis",
        raw_text="I moved through water in my old house while my mother called from upstairs.",
        word_count=14,
        content_hash=f"analysis-grounded-hash-{uuid.uuid4()}",
        segmentation_confidence="high",
    )
    migrated_session.add(dream)
    await migrated_session.commit()

    service = AnalysisService(
        theme_extractor=StubThemeExtractor(),
        grounder=StubGrounder(),
    )
    await service.analyse_dream(dream.id, migrated_session)

    result = await migrated_session.execute(
        select(DreamTheme)
        .where(DreamTheme.dream_id == dream.id)
        .order_by(DreamTheme.created_at.asc())
    )
    stored_themes = result.scalars().all()

    assert stored_themes
    assert all(theme.fragments is not None for theme in stored_themes)
    assert all(isinstance(theme.fragments, list) and theme.fragments for theme in stored_themes)
    assert stored_themes[0].fragments[0]["verified"] is True
    assert stored_themes[1].fragments[0]["verified"] is False


@pytest.mark.asyncio
async def test_regrounding_writes_annotation_version(migrated_session: AsyncSession) -> None:
    dream = DreamEntry(
        source_doc_id="doc-3",
        date=None,
        title="Dream for re-grounding",
        raw_text="I moved through water in my old house while my mother called from upstairs.",
        word_count=14,
        content_hash=f"analysis-regrounding-hash-{uuid.uuid4()}",
        segmentation_confidence="high",
    )
    migrated_session.add(dream)
    await migrated_session.commit()

    grounder = SequencedGrounder()
    service = AnalysisService(
        theme_extractor=StubThemeExtractor(),
        grounder=grounder,
    )

    await service.analyse_dream(dream.id, migrated_session)
    first_result = await migrated_session.execute(
        select(DreamTheme)
        .where(DreamTheme.dream_id == dream.id)
        .order_by(DreamTheme.created_at.asc())
    )
    first_themes = first_result.scalars().all()
    first_state = {
        theme.id: {
            "salience": theme.salience,
            "fragments": theme.fragments,
        }
        for theme in first_themes
    }

    await service.analyse_dream(dream.id, migrated_session)
    second_result = await migrated_session.execute(
        select(DreamTheme)
        .where(DreamTheme.dream_id == dream.id)
        .order_by(DreamTheme.created_at.asc())
    )
    second_themes = second_result.scalars().all()
    version_result = await migrated_session.execute(
        select(AnnotationVersion)
        .where(AnnotationVersion.entity_type == "dream_theme")
        .order_by(AnnotationVersion.created_at.asc())
    )
    versions = version_result.scalars().all()

    assert len(second_themes) == 2
    assert len(versions) == 4
    for theme in second_themes:
        update_snapshot = next(
            version.snapshot
            for version in versions
            if version.entity_id == theme.id and version.snapshot["status_before"] == "draft"
        )
        assert update_snapshot["salience_before"] == first_state[theme.id]["salience"]
        assert update_snapshot["fragments_before"] == first_state[theme.id]["fragments"]
        assert theme.fragments != first_state[theme.id]["fragments"]
