from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

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


async def _table_names(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as connection:
        return await connection.run_sync(
            lambda sync_connection: inspect(sync_connection).get_table_names()
        )


async def _columns(engine: AsyncEngine, table_name: str) -> list[dict[str, object]]:
    async with engine.connect() as connection:
        return await connection.run_sync(
            lambda sync_connection: inspect(sync_connection).get_columns(table_name)
        )


async def _foreign_keys(engine: AsyncEngine, table_name: str) -> list[dict[str, object]]:
    async with engine.connect() as connection:
        return await connection.run_sync(
            lambda sync_connection: inspect(sync_connection).get_foreign_keys(table_name)
        )


async def _column_types(engine: AsyncEngine, table_name: str) -> dict[str, str]:
    query = text(
        """
        SELECT a.attname AS column_name, format_type(a.atttypid, a.atttypmod) AS formatted_type
        FROM pg_attribute AS a
        JOIN pg_class AS c ON a.attrelid = c.oid
        JOIN pg_namespace AS n ON c.relnamespace = n.oid
        WHERE n.nspname = 'public'
          AND c.relname = :table_name
          AND a.attnum > 0
          AND NOT a.attisdropped
        """
    )

    async with engine.connect() as connection:
        result = await connection.execute(query, {"table_name": table_name})
        rows = result.mappings().all()

    return {row["column_name"]: row["formatted_type"] for row in rows}


async def _column_metadata(
    engine: AsyncEngine, table_name: str, column_name: str
) -> dict[str, object] | None:
    query = text(
        """
        SELECT is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = :table_name
          AND column_name = :column_name
        """
    )

    async with engine.connect() as connection:
        result = await connection.execute(
            query,
            {"table_name": table_name, "column_name": column_name},
        )
        return result.mappings().one_or_none()


async def _index_definitions(engine: AsyncEngine, table_name: str) -> list[dict[str, object]]:
    query = text(
        """
        SELECT
            indexname,
            indexdef
        FROM pg_indexes
        WHERE schemaname = 'public'
          AND tablename = :table_name
        ORDER BY indexname
        """
    )

    async with engine.connect() as connection:
        result = await connection.execute(query, {"table_name": table_name})
        return list(result.mappings().all())


async def _insert_theme_fixture(connection) -> tuple[object, object]:
    dream_id = (
        await connection.execute(
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
                "source_doc_id": "doc-1",
                "date": None,
                "title": "Dream title",
                "raw_text": "Dream body",
                "word_count": 2,
                "content_hash": "hash-1",
                "segmentation_confidence": "high",
            },
        )
    ).scalar_one()
    category_id = (
        await connection.execute(
            text(
                """
                INSERT INTO theme_categories (name, description, status)
                VALUES (:name, :description, :status)
                RETURNING id
                """
            ),
            {
                "name": "category-1",
                "description": "Category description",
                "status": "active",
            },
        )
    ).scalar_one()
    return dream_id, category_id


@pytest_asyncio.fixture
async def migrated_engine() -> AsyncEngine:
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url)

    await _reset_public_schema(engine)
    await asyncio.to_thread(command.upgrade, _alembic_config(), "head")

    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_migrations_apply_cleanly(migrated_engine: AsyncEngine) -> None:
    table_names = await _table_names(migrated_engine)

    assert "dream_entries" in table_names
    assert "dream_chunks" in table_names
    assert "theme_categories" in table_names
    assert "dream_themes" in table_names
    assert "annotation_versions" in table_names


@pytest.mark.anyio
async def test_dream_entries_schema(migrated_engine: AsyncEngine) -> None:
    columns = {column["name"] for column in await _columns(migrated_engine, "dream_entries")}

    assert columns == {
        "id",
        "source_doc_id",
        "date",
        "title",
        "raw_text",
        "word_count",
        "content_hash",
        "segmentation_confidence",
        "created_at",
    }


@pytest.mark.anyio
async def test_dream_chunks_schema(migrated_engine: AsyncEngine) -> None:
    columns = {column["name"] for column in await _columns(migrated_engine, "dream_chunks")}
    foreign_keys = await _foreign_keys(migrated_engine, "dream_chunks")
    column_types = await _column_types(migrated_engine, "dream_chunks")
    indexes = await _index_definitions(migrated_engine, "dream_chunks")

    assert columns == {
        "id",
        "dream_id",
        "chunk_index",
        "chunk_text",
        "embedding",
        "created_at",
    }
    assert foreign_keys[0]["referred_table"] == "dream_entries"
    assert foreign_keys[0]["options"]["ondelete"] == "CASCADE"
    assert column_types["embedding"] == "vector(1536)"
    assert any(
        index["indexname"] == "ix_dream_chunks_embedding_hnsw"
        and "USING hnsw" in str(index["indexdef"])
        and "(embedding vector_cosine_ops)" in str(index["indexdef"])
        for index in indexes
    )


@pytest.mark.anyio
async def test_theme_schema(migrated_engine: AsyncEngine) -> None:
    category_columns = {
        column["name"] for column in await _columns(migrated_engine, "theme_categories")
    }
    dream_theme_columns = {
        column["name"] for column in await _columns(migrated_engine, "dream_themes")
    }

    assert category_columns == {"id", "name", "description", "status", "created_at"}
    assert dream_theme_columns == {
        "id",
        "dream_id",
        "category_id",
        "salience",
        "status",
        "match_type",
        "fragments",
        "deprecated",
        "created_at",
    }


@pytest.mark.anyio
async def test_dream_themes_status_rejects_invalid_values(
    migrated_engine: AsyncEngine,
) -> None:
    async with migrated_engine.begin() as connection:
        dream_id, category_id = await _insert_theme_fixture(connection)

    with pytest.raises(IntegrityError):
        async with migrated_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO dream_themes (
                        dream_id,
                        category_id,
                        salience,
                        status,
                        match_type,
                        fragments
                    )
                    VALUES (
                        :dream_id,
                        :category_id,
                        :salience,
                        :status,
                        :match_type,
                        :fragments
                    )
                    """
                ),
                {
                    "dream_id": dream_id,
                    "category_id": category_id,
                    "salience": 0.5,
                    "status": "invalid",
                    "match_type": "semantic",
                    "fragments": "[]",
                },
            )


@pytest.mark.anyio
async def test_dream_themes_deprecated_column_defaults_false(
    migrated_engine: AsyncEngine,
) -> None:
    metadata = await _column_metadata(migrated_engine, "dream_themes", "deprecated")

    assert metadata is not None
    assert metadata["is_nullable"] == "NO"
    assert metadata["column_default"] is not None
    assert "false" in str(metadata["column_default"]).lower()


@pytest.mark.anyio
async def test_dream_themes_fragments_column_defaults_to_empty_jsonb(
    migrated_engine: AsyncEngine,
) -> None:
    metadata = await _column_metadata(migrated_engine, "dream_themes", "fragments")

    assert metadata is not None
    assert metadata["is_nullable"] == "NO"
    assert metadata["column_default"] == "'[]'::jsonb"


@pytest.mark.anyio
@pytest.mark.parametrize("status", ["draft", "confirmed", "rejected"])
async def test_dream_themes_status_accepts_valid_values(
    migrated_engine: AsyncEngine,
    status: str,
) -> None:
    async with migrated_engine.begin() as connection:
        dream_id, category_id = await _insert_theme_fixture(connection)
        await connection.execute(
            text(
                """
                INSERT INTO dream_themes (
                    dream_id,
                    category_id,
                    salience,
                    status,
                    match_type,
                    fragments
                )
                VALUES (
                    :dream_id,
                    :category_id,
                    :salience,
                    :status,
                    :match_type,
                    :fragments
                )
                """
            ),
            {
                "dream_id": dream_id,
                "category_id": category_id,
                "salience": 0.5,
                "status": status,
                "match_type": "semantic",
                "fragments": "[]",
            },
        )


@pytest.mark.anyio
async def test_annotation_versions_schema(migrated_engine: AsyncEngine) -> None:
    columns = {column["name"] for column in await _columns(migrated_engine, "annotation_versions")}
    column_types = await _column_types(migrated_engine, "annotation_versions")

    assert columns == {"id", "entity_type", "entity_id", "snapshot", "changed_by", "created_at"}
    assert column_types["snapshot"] == "jsonb"
