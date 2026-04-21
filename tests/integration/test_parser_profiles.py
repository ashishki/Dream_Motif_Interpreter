from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
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

from app.models.dream import DreamEntry
from app.retrieval.types import NormalizedDocument
from app.services.segmentation import segment_and_store

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
    engine = create_async_engine(os.environ["DATABASE_URL"])

    await _reset_public_schema(engine)
    await asyncio.to_thread(command.upgrade, _alembic_config(), "head")

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            yield session
    finally:
        await engine.dispose()


def _build_document(
    paragraphs: list[str],
    *,
    metadata: dict[str, object] | None = None,
) -> NormalizedDocument:
    return NormalizedDocument(
        client_id="default",
        source_type="google_doc",
        external_id="doc-parser-profile-integration",
        source_path="documents/doc-parser-profile-integration",
        title="Сны",
        raw_text="\n\n".join(paragraphs),
        sections=paragraphs,
        metadata=metadata or {},
        fetched_at=datetime(2026, 4, 21, tzinfo=timezone.utc),
    )


@pytest.mark.anyio
async def test_ingestion_persists_applied_profile_and_warnings(
    migrated_session: AsyncSession,
) -> None:
    document = _build_document(
        [
            "I was standing in an empty field at dusk.",
            "The wind kept moving the same ladder in slow circles.",
        ]
    )

    await segment_and_store(document, migrated_session)
    result = await migrated_session.execute(select(DreamEntry))
    stored_entry = result.scalar_one()

    assert stored_entry.parser_profile == "default"
    assert any(
        "falling back to default profile" in warning for warning in stored_entry.parse_warnings
    )
