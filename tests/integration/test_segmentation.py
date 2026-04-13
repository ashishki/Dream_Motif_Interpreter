from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models.dream import DreamEntry
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
async def migrated_session(db_engine: AsyncEngine) -> AsyncSession:
    await _reset_public_schema(db_engine)
    await asyncio.to_thread(command.upgrade, _alembic_config(), "head")

    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest.mark.anyio
async def test_deduplication_by_content_hash(migrated_session: AsyncSession) -> None:
    paragraphs = [
        "2026-02-14",
        "I was climbing a staircase made of paper.",
        "At the top, I found my childhood bedroom.",
    ]

    first_insert = await segment_and_store(paragraphs, migrated_session)
    second_insert = await segment_and_store(paragraphs, migrated_session)
    result = await migrated_session.execute(select(DreamEntry))
    stored_entries = result.scalars().all()

    assert len(first_insert) == 1
    assert len(second_insert) == 0
    assert len(stored_entries) == 1
