from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.assistant.voice_media import (
    VoiceLeaseLost,
    claim_voice_media_event,
    get_or_create_voice_media_event,
    mark_voice_reply_failed,
    release_voice_media_lease,
    store_voice_delivery_progress,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config() -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    return config


def _load_voice_durability_migration() -> object:
    migration_path = PROJECT_ROOT / "alembic/versions/021_voice_delivery_durability.py"
    spec = importlib.util.spec_from_file_location("migration_021_voice_durability", migration_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[arg-type]
    return module


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


async def _check_constraints(engine: AsyncEngine, table_name: str) -> list[dict[str, object]]:
    async with engine.connect() as connection:
        return await connection.run_sync(
            lambda sync_connection: inspect(sync_connection).get_check_constraints(table_name)
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


async def _trigger_metadata(
    engine: AsyncEngine,
    table_name: str,
    trigger_name: str,
) -> dict[str, object] | None:
    query = text(
        """
        SELECT
            trg.tgdeferrable AS is_deferrable,
            trg.tginitdeferred AS is_initially_deferred
        FROM pg_trigger AS trg
        JOIN pg_class AS rel ON rel.oid = trg.tgrelid
        JOIN pg_namespace AS ns ON ns.oid = rel.relnamespace
        WHERE ns.nspname = 'public'
          AND rel.relname = :table_name
          AND trg.tgname = :trigger_name
          AND NOT trg.tgisinternal
        """
    )
    async with engine.connect() as connection:
        result = await connection.execute(
            query,
            {"table_name": table_name, "trigger_name": trigger_name},
        )
        return result.mappings().one_or_none()


async def _function_exists(engine: AsyncEngine, function_name: str) -> bool:
    query = text(
        """
        SELECT EXISTS (
            SELECT 1
            FROM pg_proc AS proc
            JOIN pg_namespace AS ns ON ns.oid = proc.pronamespace
            WHERE ns.nspname = 'public'
              AND proc.proname = :function_name
        )
        """
    )
    async with engine.connect() as connection:
        return bool(await connection.scalar(query, {"function_name": function_name}))


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
    assert "voice_media_events" in table_names
    assert "dream_write_statuses" in table_names
    assert "dream_processing_jobs" in table_names
    assert "note_processing_jobs" in table_names
    assert "manual_sync_jobs" in table_names


@pytest.mark.anyio
async def test_dream_entries_schema(migrated_engine: AsyncEngine) -> None:
    columns = {column["name"] for column in await _columns(migrated_engine, "dream_entries")}
    indexes = await _index_definitions(migrated_engine, "dream_entries")

    assert columns == {
        "id",
        "source_doc_id",
        "date",
        "title",
        "raw_text",
        "word_count",
        "content_hash",
        "source_event_key",
        "source_entry_key",
        "segmentation_confidence",
        "parser_profile",
        "parse_warnings",
        "created_at",
    }
    assert any(
        index["indexname"] == "ix_dream_entries_source_entry_key" and "UNIQUE" in index["indexdef"]
        for index in indexes
    )
    assert any(
        index["indexname"] == "ix_dream_entries_source_event_key" and "UNIQUE" in index["indexdef"]
        for index in indexes
    )
    assert any(
        index["indexname"] == "ix_dream_entries_content_hash" and "UNIQUE" not in index["indexdef"]
        for index in indexes
    )


@pytest.mark.anyio
async def test_dream_chunks_schema(migrated_engine: AsyncEngine) -> None:
    columns = {column["name"] for column in await _columns(migrated_engine, "dream_chunks")}
    foreign_keys = await _foreign_keys(migrated_engine, "dream_chunks")
    column_types = await _column_types(migrated_engine, "dream_chunks")
    indexes = await _index_definitions(migrated_engine, "dream_chunks")

    assert columns == {
        "id",
        "dream_id",
        "note_id",
        "source_kind",
        "chunk_index",
        "chunk_text",
        "embedding",
        "created_at",
    }
    assert any(
        key["referred_table"] == "dream_entries" and key["options"]["ondelete"] == "CASCADE"
        for key in foreign_keys
    )
    assert any(
        key["referred_table"] == "dream_notes" and key["options"]["ondelete"] == "CASCADE"
        for key in foreign_keys
    )
    assert column_types["embedding"] == "vector(1536)"
    assert any(
        index["indexname"] == "ix_dream_chunks_embedding_hnsw"
        and "USING hnsw" in str(index["indexdef"])
        and "(embedding vector_cosine_ops)" in str(index["indexdef"])
        for index in indexes
    )


@pytest.mark.anyio
async def test_dream_notes_have_durable_content_identity(
    migrated_engine: AsyncEngine,
) -> None:
    columns = {column["name"] for column in await _columns(migrated_engine, "dream_notes")}
    indexes = await _index_definitions(migrated_engine, "dream_notes")

    assert "content_hash" in columns
    assert any(
        index["indexname"] == "uq_dream_notes_dream_id_content_hash"
        and "UNIQUE" in index["indexdef"]
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
    dream_theme_indexes = await _index_definitions(migrated_engine, "dream_themes")

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
    assert any(
        index["indexname"] == "uq_dream_themes_dream_category" and "UNIQUE" in index["indexdef"]
        for index in dream_theme_indexes
    )


@pytest.mark.anyio
async def test_motif_schema_has_normalized_identity(
    migrated_engine: AsyncEngine,
) -> None:
    columns = {column["name"] for column in await _columns(migrated_engine, "motif_inductions")}
    indexes = await _index_definitions(migrated_engine, "motif_inductions")

    assert "normalized_label" in columns
    assert any(
        index["indexname"] == "uq_motif_inductions_dream_normalized_label"
        and "UNIQUE" in index["indexdef"]
        for index in indexes
    )


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


@pytest.mark.anyio
async def test_dream_write_statuses_schema(migrated_engine: AsyncEngine) -> None:
    columns = {column["name"] for column in await _columns(migrated_engine, "dream_write_statuses")}
    foreign_keys = await _foreign_keys(migrated_engine, "dream_write_statuses")
    indexes = await _index_definitions(migrated_engine, "dream_write_statuses")

    assert columns == {
        "id",
        "dream_id",
        "target_doc_id",
        "status",
        "attempt_count",
        "last_error",
        "claim_token",
        "created_at",
        "updated_at",
    }
    assert foreign_keys[0]["referred_table"] == "dream_entries"
    assert foreign_keys[0]["options"]["ondelete"] == "CASCADE"
    assert any(index["indexname"] == "ix_dream_write_statuses_dream_id" for index in indexes)
    assert any(
        index["indexname"] == "ix_dream_write_statuses_status_updated_at" for index in indexes
    )
    assert any(
        index["indexname"] == "uq_dream_write_statuses_dream_target"
        and "UNIQUE" in index["indexdef"]
        for index in indexes
    )


@pytest.mark.anyio
async def test_dream_processing_jobs_schema(migrated_engine: AsyncEngine) -> None:
    columns = {
        column["name"] for column in await _columns(migrated_engine, "dream_processing_jobs")
    }
    foreign_keys = await _foreign_keys(migrated_engine, "dream_processing_jobs")
    indexes = await _index_definitions(migrated_engine, "dream_processing_jobs")

    assert columns == {
        "id",
        "dream_id",
        "status",
        "stage",
        "attempt_count",
        "last_error",
        "available_at",
        "locked_at",
        "lock_token",
        "created_at",
        "updated_at",
    }
    assert foreign_keys[0]["referred_table"] == "dream_entries"
    assert foreign_keys[0]["options"]["ondelete"] == "CASCADE"
    assert any(index["indexname"] == "ix_dream_processing_jobs_claim" for index in indexes)
    assert any(
        index["indexname"] == "uq_dream_processing_jobs_dream_stage"
        and "UNIQUE" in index["indexdef"]
        for index in indexes
    )
    assert await _trigger_metadata(
        migrated_engine,
        "dream_entries",
        "ensure_dream_processing_jobs_023",
    ) == {
        "is_deferrable": True,
        "is_initially_deferred": True,
    }


@pytest.mark.anyio
async def test_manual_sync_jobs_schema(migrated_engine: AsyncEngine) -> None:
    columns = {column["name"] for column in await _columns(migrated_engine, "manual_sync_jobs")}
    indexes = await _index_definitions(migrated_engine, "manual_sync_jobs")
    constraints = {
        constraint["name"]
        for constraint in await _check_constraints(migrated_engine, "manual_sync_jobs")
    }

    assert columns == {
        "id",
        "doc_id",
        "status",
        "attempt_count",
        "last_error",
        "new_entries",
        "notify_chat_id",
        "available_at",
        "locked_at",
        "lock_token",
        "started_at",
        "finished_at",
        "created_at",
        "updated_at",
    }
    assert "ck_manual_sync_jobs_status" in constraints
    assert "ck_manual_sync_jobs_new_entries" in constraints
    assert any(index["indexname"] == "ix_manual_sync_jobs_claim" for index in indexes)
    assert any(index["indexname"] == "ix_manual_sync_jobs_doc_created" for index in indexes)


@pytest.mark.anyio
async def test_legacy_dream_insert_gets_missing_jobs_at_commit(
    migrated_engine: AsyncEngine,
) -> None:
    """The compatibility trigger covers rolling-deploy writers atomically."""
    async with migrated_engine.begin() as connection:
        inserted = (
            (
                await connection.execute(
                    text(
                        """
                        INSERT INTO dream_entries (
                            source_doc_id, date, title, raw_text, word_count,
                            content_hash, segmentation_confidence
                        ) VALUES
                            (
                                'native-compat-doc', NULL, 'Native', 'native body', 2,
                                'native-compat-trigger-hash', 'high'
                            ),
                            (
                                'telegram:compat', NULL, 'Telegram', 'telegram body', 2,
                                'telegram-compat-trigger-hash', 'low'
                            )
                        RETURNING id, source_doc_id
                        """
                    )
                )
            )
            .mappings()
            .all()
        )
        dream_ids = [row["id"] for row in inserted]
        # INITIALLY DEFERRED means application-owned jobs/evidence can still be
        # written later in this transaction before compatibility work is filled.
        before_commit = await connection.scalar(
            text(
                """
                SELECT count(*)
                FROM dream_processing_jobs
                WHERE dream_id = ANY(:dream_ids)
                """
            ),
            {"dream_ids": dream_ids},
        )
        assert before_commit == 0

    async with migrated_engine.connect() as connection:
        jobs = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT dream.source_doc_id, job.stage, job.status
                        FROM dream_processing_jobs AS job
                        JOIN dream_entries AS dream ON dream.id = job.dream_id
                        WHERE job.dream_id = ANY(:dream_ids)
                        ORDER BY dream.source_doc_id, job.stage
                        """
                    ),
                    {"dream_ids": dream_ids},
                )
            )
            .mappings()
            .all()
        )

    by_source = {
        source: {row["stage"]: row["status"] for row in jobs if row["source_doc_id"] == source}
        for source in {row["source_doc_id"] for row in inserted}
    }
    assert by_source == {
        "native-compat-doc": {
            "analysis": "pending",
            "gdocs": "succeeded",
            "index": "pending",
            "motif": "pending",
        },
        "telegram:compat": {
            "analysis": "pending",
            "gdocs": "pending",
            "index": "pending",
            "motif": "pending",
        },
    }


@pytest.mark.anyio
async def test_note_processing_jobs_schema(migrated_engine: AsyncEngine) -> None:
    columns = {column["name"] for column in await _columns(migrated_engine, "note_processing_jobs")}
    foreign_keys = await _foreign_keys(migrated_engine, "note_processing_jobs")
    indexes = await _index_definitions(migrated_engine, "note_processing_jobs")
    checks = await _check_constraints(migrated_engine, "note_processing_jobs")

    assert columns == {
        "id",
        "note_id",
        "stage",
        "status",
        "attempt_count",
        "last_error",
        "available_at",
        "locked_at",
        "lock_token",
        "target_doc_id",
        "created_at",
        "updated_at",
    }
    assert foreign_keys[0]["referred_table"] == "dream_notes"
    assert foreign_keys[0]["options"]["ondelete"] == "CASCADE"
    assert any(index["indexname"] == "ix_note_processing_jobs_claim" for index in indexes)
    assert any(
        index["indexname"] == "uq_note_processing_jobs_note_stage" and "UNIQUE" in index["indexdef"]
        for index in indexes
    )
    assert any(check["name"] == "ck_note_processing_jobs_target" for check in checks)
    assert await _trigger_metadata(
        migrated_engine,
        "dream_notes",
        "ensure_note_processing_job_025",
    ) == {
        "is_deferrable": True,
        "is_initially_deferred": True,
    }


@pytest.mark.anyio
async def test_legacy_note_insert_gets_safe_index_job_from_commit_evidence(
    migrated_engine: AsyncEngine,
) -> None:
    """Only a non-null embedding can mark legacy note indexing complete."""
    async with migrated_engine.begin() as connection:
        dream_id = (
            await connection.execute(
                text(
                    """
                    INSERT INTO dream_entries (
                        source_doc_id, date, title, raw_text, word_count,
                        content_hash, segmentation_confidence
                    ) VALUES (
                        'native-note-trigger-doc', NULL, 'Notes', 'dream body', 2,
                        'note-trigger-dream-hash', 'high'
                    )
                    RETURNING id
                    """
                )
            )
        ).scalar_one()
        notes = (
            (
                await connection.execute(
                    text(
                        """
                        INSERT INTO dream_notes (
                            dream_id, text, content_hash, source
                        ) VALUES
                            (:dream_id, 'null evidence', :null_hash, 'google_doc'),
                            (:dream_id, 'embedded evidence', :embedded_hash, 'google_doc')
                        RETURNING id, text
                        """
                    ),
                    {
                        "dream_id": dream_id,
                        "null_hash": "c" * 64,
                        "embedded_hash": "d" * 64,
                    },
                )
            )
            .mappings()
            .all()
        )
        note_ids = [row["id"] for row in notes]
        ids_by_text = {row["text"]: row["id"] for row in notes}
        await connection.execute(
            text(
                """
                INSERT INTO dream_chunks (
                    dream_id, note_id, source_kind, chunk_index, chunk_text, embedding
                ) VALUES
                    (
                        :dream_id, :null_note_id, 'note', 1000000001,
                        'null evidence', NULL
                    ),
                    (
                        :dream_id, :embedded_note_id, 'note', 1000000002,
                        'embedded evidence',
                        ('[' || repeat('0,', 1535) || '0]')::vector
                    )
                """
            ),
            {
                "dream_id": dream_id,
                "null_note_id": ids_by_text["null evidence"],
                "embedded_note_id": ids_by_text["embedded evidence"],
            },
        )
        before_commit = await connection.scalar(
            text(
                """
                SELECT count(*)
                FROM note_processing_jobs
                WHERE note_id = ANY(:note_ids)
                """
            ),
            {"note_ids": note_ids},
        )
        assert before_commit == 0

    async with migrated_engine.connect() as connection:
        jobs = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT note.text, job.stage, job.status, job.target_doc_id
                        FROM note_processing_jobs AS job
                        JOIN dream_notes AS note ON note.id = job.note_id
                        WHERE job.note_id = ANY(:note_ids)
                        ORDER BY note.text
                        """
                    ),
                    {"note_ids": note_ids},
                )
            )
            .mappings()
            .all()
        )

    assert jobs == [
        {
            "text": "embedded evidence",
            "stage": "index",
            "status": "succeeded",
            "target_doc_id": None,
        },
        {
            "text": "null evidence",
            "stage": "index",
            "status": "pending",
            "target_doc_id": None,
        },
    ]


@pytest.mark.anyio
async def test_note_processing_migration_backfills_index_only_and_downgrades() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url)
    await _reset_public_schema(engine)
    await engine.dispose()
    config = _alembic_config()
    await asyncio.to_thread(command.upgrade, config, "024_restore_graph_controls")

    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        dream_id = (
            await connection.execute(
                text(
                    """
                    INSERT INTO dream_entries (
                        source_doc_id, date, title, raw_text, word_count,
                        content_hash, segmentation_confidence
                    ) VALUES (
                        'doc-note-outbox', NULL, 'Outbox', 'Dream body', 2,
                        'note-outbox-dream-hash', 'high'
                    )
                    RETURNING id
                    """
                )
            )
        ).scalar_one()
        pending_note_id = (
            await connection.execute(
                text(
                    """
                    INSERT INTO dream_notes (dream_id, text, content_hash, source)
                    VALUES (:dream_id, 'pending note', :content_hash, 'telegram')
                    RETURNING id
                    """
                ),
                {"dream_id": dream_id, "content_hash": "a" * 64},
            )
        ).scalar_one()
        indexed_note_id = (
            await connection.execute(
                text(
                    """
                    INSERT INTO dream_notes (dream_id, text, content_hash, source)
                    VALUES (:dream_id, 'indexed note', :content_hash, 'google_doc')
                    RETURNING id
                    """
                ),
                {"dream_id": dream_id, "content_hash": "b" * 64},
            )
        ).scalar_one()
        await connection.execute(
            text(
                """
                INSERT INTO dream_chunks (
                    dream_id, note_id, source_kind, chunk_index, chunk_text, embedding
                ) VALUES (
                    :dream_id, :note_id, 'note', 1000000000, 'indexed note',
                    ('[' || repeat('0,', 1535) || '0]')::vector
                )
                """
            ),
            {"dream_id": dream_id, "note_id": indexed_note_id},
        )
    await engine.dispose()

    await asyncio.to_thread(command.upgrade, config, "025_note_processing_jobs")
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT note_id, stage, status, target_doc_id
                            FROM note_processing_jobs
                            ORDER BY note_id
                            """
                        )
                    )
                )
                .mappings()
                .all()
            )

        assert len(rows) == 2
        statuses = {row["note_id"]: row["status"] for row in rows}
        assert statuses == {
            pending_note_id: "pending",
            indexed_note_id: "succeeded",
        }
        assert {row["stage"] for row in rows} == {"index"}
        assert all(row["target_doc_id"] is None for row in rows)
    finally:
        await engine.dispose()

    with pytest.raises(DBAPIError, match="durable note work is unfinished"):
        await asyncio.to_thread(command.downgrade, config, "024_restore_graph_controls")

    engine = create_async_engine(database_url)
    assert await _trigger_metadata(
        engine,
        "dream_notes",
        "ensure_note_processing_job_025",
    ) == {
        "is_deferrable": True,
        "is_initially_deferred": True,
    }
    assert await _function_exists(engine, "ensure_note_processing_job_025")
    async with engine.begin() as connection:
        await connection.execute(text("UPDATE note_processing_jobs SET status = 'succeeded'"))
    await engine.dispose()

    await asyncio.to_thread(command.downgrade, config, "024_restore_graph_controls")
    engine = create_async_engine(database_url)
    try:
        assert "note_processing_jobs" not in await _table_names(engine)
        assert (
            await _trigger_metadata(
                engine,
                "dream_notes",
                "ensure_note_processing_job_025",
            )
            is None
        )
        assert not await _function_exists(engine, "ensure_note_processing_job_025")
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_manual_sync_downgrade_blocks_unfinished_durable_work() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url)
    await _reset_public_schema(engine)
    await engine.dispose()
    config = _alembic_config()
    await asyncio.to_thread(command.upgrade, config, "026_manual_sync_jobs")

    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO manual_sync_jobs (doc_id, status)
                VALUES ('doc-manual-sync', 'pending')
                """
            )
        )
    await engine.dispose()

    with pytest.raises(DBAPIError, match="durable manual sync work is unfinished"):
        await asyncio.to_thread(command.downgrade, config, "025_note_processing_jobs")

    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(text("UPDATE manual_sync_jobs SET status = 'succeeded'"))
    await engine.dispose()

    await asyncio.to_thread(command.downgrade, config, "025_note_processing_jobs")
    engine = create_async_engine(database_url)
    try:
        assert "manual_sync_jobs" not in await _table_names(engine)
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_voice_media_events_schema_includes_transcript_text(
    migrated_engine: AsyncEngine,
) -> None:
    columns = {column["name"] for column in await _columns(migrated_engine, "voice_media_events")}
    indexes = await _index_definitions(migrated_engine, "voice_media_events")

    assert "transcript_text" in columns
    assert "reply_text" in columns
    assert "transcription_attempt_count" in columns
    assert "reply_chunks_delivered" in columns
    assert "delivery_attempt_count" in columns
    assert "next_attempt_at" in columns
    assert "lease_owner" in columns
    assert "lease_expires_at" in columns
    assert any(
        index["indexname"] == "uq_voice_media_events_chat_message" and "UNIQUE" in index["indexdef"]
        for index in indexes
    )
    assert any(index["indexname"] == "ix_voice_media_events_recovery" for index in indexes)


@pytest.mark.anyio
async def test_voice_durability_migration_keeps_most_complete_duplicate() -> None:
    """Complementary legacy state is merged before duplicate rows are removed."""
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url)
    await _reset_public_schema(engine)
    await engine.dispose()
    config = _alembic_config()
    await asyncio.to_thread(
        command.upgrade,
        config,
        "020_allow_reject_graph_privacy_controls",
    )

    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO voice_media_events (
                    chat_id, telegram_message_id, telegram_file_id, duration_seconds,
                    local_path, transcript_text, status, created_at, updated_at
                ) VALUES
                    (
                        88, 123, 'transcript', 9, '',
                        'durable transcript', 'transcribed', NOW() - INTERVAL '2 minutes',
                        NOW() - INTERVAL '2 minutes'
                    ),
                    (
                        88, 123, 'download', 9, '/tmp/dream_voice/complete.ogg', NULL,
                        'received',
                        NOW() - INTERVAL '1 minute', NOW() - INTERVAL '1 minute'
                    )
                """
            )
        )
    await engine.dispose()

    await asyncio.to_thread(command.upgrade, config, "021_voice_delivery_durability")
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        text(
                            """
                        SELECT telegram_file_id, local_path, transcript_text, status
                        FROM voice_media_events
                        WHERE chat_id = 88 AND telegram_message_id = 123
                        """
                        )
                    )
                )
                .mappings()
                .all()
            )
        assert rows == [
            {
                "telegram_file_id": "transcript",
                "local_path": "/tmp/dream_voice/complete.ogg",
                "transcript_text": "durable transcript",
                "status": "transcribed",
            }
        ]
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_voice_duplicate_merge_preserves_coupled_durable_state() -> None:
    """The 021 merge keeps complementary values without mixing coupled pairs."""
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url)
    await _reset_public_schema(engine)
    await engine.dispose()
    config = _alembic_config()
    await asyncio.to_thread(command.upgrade, config, "021_voice_delivery_durability")
    migration = _load_voice_durability_migration()

    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    ALTER TABLE voice_media_events
                    DROP CONSTRAINT uq_voice_media_events_chat_message
                    """
                )
            )
            inserted = (
                (
                    await connection.execute(
                        text(
                            """
                            INSERT INTO voice_media_events (
                                chat_id, telegram_message_id, telegram_file_id,
                                duration_seconds, local_path, transcript_text, status,
                                reply_text, transcription_attempt_count,
                                reply_chunks_delivered, delivery_attempt_count,
                                next_attempt_at, lease_owner, lease_expires_at,
                                created_at, updated_at
                            ) VALUES
                                (
                                    89, 124, 'transcript', 9, '', 'durable transcript',
                                    'transcribed', NULL, 5, 0, 1,
                                    TIMESTAMPTZ '2099-01-02 00:00:00+00', NULL, NULL,
                                    TIMESTAMPTZ '2026-01-01 00:00:00+00',
                                    TIMESTAMPTZ '2026-01-01 00:01:00+00'
                                ),
                                (
                                    89, 124, 'path', 9, '/tmp/dream_voice/merged.ogg', NULL,
                                    'downloaded', NULL, 2, 0, 8,
                                    TIMESTAMPTZ '2099-01-03 00:00:00+00', NULL, NULL,
                                    TIMESTAMPTZ '2026-01-01 00:00:00+00',
                                    TIMESTAMPTZ '2026-01-01 00:02:00+00'
                                ),
                                (
                                    89, 124, 'reply-progress', 9, '', NULL,
                                    'reply_pending', 'reply with progress', 1, 3, 2,
                                    TIMESTAMPTZ '2099-01-04 00:00:00+00', NULL, NULL,
                                    TIMESTAMPTZ '2026-01-01 00:00:00+00',
                                    TIMESTAMPTZ '2026-01-01 00:03:00+00'
                                ),
                                (
                                    89, 124, 'reply-attempts', 9, '', NULL,
                                    'reply_pending', 'different reply', 1, 1, 9,
                                    TIMESTAMPTZ '2099-01-01 00:00:00+00', NULL, NULL,
                                    TIMESTAMPTZ '2026-01-01 00:00:00+00',
                                    TIMESTAMPTZ '2026-01-01 00:04:00+00'
                                ),
                                (
                                    89, 124, 'lease-old', 9, '', NULL, 'processing',
                                    NULL, 1, 0, 0, NULL, 'worker-old',
                                    TIMESTAMPTZ '2999-01-01 00:00:00+00',
                                    TIMESTAMPTZ '2026-01-01 00:00:00+00',
                                    TIMESTAMPTZ '2026-01-01 00:05:00+00'
                                ),
                                (
                                    89, 124, 'lease-latest', 9, '', NULL, 'processing',
                                    NULL, 1, 0, 0, NULL, 'worker-latest',
                                    TIMESTAMPTZ '2999-02-01 00:00:00+00',
                                    TIMESTAMPTZ '2026-01-01 00:00:00+00',
                                    TIMESTAMPTZ '2026-01-01 00:01:00+00'
                                ),
                                (
                                    89, 124, 'expired-lease', 9, '', NULL, 'processing',
                                    NULL, 1, 0, 0, NULL, 'worker-expired',
                                    TIMESTAMPTZ '2000-01-01 00:00:00+00',
                                    TIMESTAMPTZ '2026-01-01 00:00:00+00',
                                    TIMESTAMPTZ '2026-01-01 00:06:00+00'
                                ),
                                (
                                    90, 125, 'delivered', 9, '', NULL, 'delivered',
                                    NULL, 1, 0, 1, NULL, NULL, NULL,
                                    TIMESTAMPTZ '2026-01-01 00:00:00+00',
                                    TIMESTAMPTZ '2026-01-01 00:01:00+00'
                                ),
                                (
                                    90, 125, 'pending-loser', 9,
                                    '/tmp/dream_voice/terminal.ogg', 'terminal transcript',
                                    'reply_pending', 'must not be resent', 6, 4, 7,
                                    TIMESTAMPTZ '2099-01-01 00:00:00+00',
                                    'worker-pending', TIMESTAMPTZ '2999-01-01 00:00:00+00',
                                    TIMESTAMPTZ '2026-01-01 00:00:00+00',
                                    TIMESTAMPTZ '2026-01-01 00:02:00+00'
                                )
                            RETURNING id, telegram_file_id
                            """
                        )
                    )
                )
                .mappings()
                .all()
            )
            ids_by_file = {row["telegram_file_id"]: row["id"] for row in inserted}

            for statement_name in (
                "_CREATE_DUPLICATE_MERGE_TABLE_SQL",
                "_UPDATE_DUPLICATE_SURVIVORS_SQL",
                "_DELETE_MERGED_DUPLICATES_SQL",
                "_DROP_DUPLICATE_MERGE_TABLE_SQL",
            ):
                await connection.execute(text(getattr(migration, statement_name)))

            recoverable = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT
                                id, telegram_file_id, local_path, transcript_text, status,
                                reply_text, transcription_attempt_count,
                                reply_chunks_delivered, delivery_attempt_count,
                                next_attempt_at IS NULL AS is_due_now,
                                lease_owner,
                                lease_expires_at = TIMESTAMPTZ '2999-02-01 00:00:00+00'
                                    AS has_latest_lease
                            FROM voice_media_events
                            WHERE chat_id = 89 AND telegram_message_id = 124
                            """
                        )
                    )
                )
                .mappings()
                .one()
            )
            terminal = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT
                                id, telegram_file_id, local_path, transcript_text, status,
                                reply_text, transcription_attempt_count,
                                reply_chunks_delivered, delivery_attempt_count,
                                next_attempt_at, lease_owner, lease_expires_at
                            FROM voice_media_events
                            WHERE chat_id = 90 AND telegram_message_id = 125
                            """
                        )
                    )
                )
                .mappings()
                .one()
            )

        assert recoverable == {
            "id": ids_by_file["lease-latest"],
            "telegram_file_id": "lease-latest",
            "local_path": "/tmp/dream_voice/merged.ogg",
            "transcript_text": "durable transcript",
            "status": "reply_pending",
            "reply_text": "reply with progress",
            "transcription_attempt_count": 5,
            "reply_chunks_delivered": 3,
            "delivery_attempt_count": 9,
            "is_due_now": True,
            "lease_owner": "worker-latest",
            "has_latest_lease": True,
        }
        assert terminal == {
            "id": ids_by_file["delivered"],
            "telegram_file_id": "delivered",
            "local_path": "/tmp/dream_voice/terminal.ogg",
            "transcript_text": "terminal transcript",
            "status": "delivered",
            "reply_text": None,
            "transcription_attempt_count": 6,
            "reply_chunks_delivered": 0,
            "delivery_attempt_count": 7,
            "next_attempt_at": None,
            "lease_owner": None,
            "lease_expires_at": None,
        }
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_voice_durability_downgrade_blocks_unfinished_work() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url)
    await _reset_public_schema(engine)
    await engine.dispose()
    config = _alembic_config()
    await asyncio.to_thread(command.upgrade, config, "021_voice_delivery_durability")

    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        event_id = (
            await connection.execute(
                text(
                    """
                    INSERT INTO voice_media_events (
                        chat_id, telegram_message_id, telegram_file_id,
                        duration_seconds, status
                    ) VALUES (91, 126, 'unsafe-downgrade', 9, 'reply_pending')
                    RETURNING id
                    """
                )
            )
        ).scalar_one()
    await engine.dispose()

    with pytest.raises(DBAPIError, match="durable voice work is unfinished"):
        await asyncio.to_thread(
            command.downgrade,
            config,
            "020_allow_reject_graph_privacy_controls",
        )

    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                UPDATE voice_media_events
                SET
                    status = 'delivered',
                    reply_text = 'durable reply',
                    reply_chunks_delivered = 1,
                    next_attempt_at = TIMESTAMPTZ '2099-01-01 00:00:00+00',
                    lease_owner = 'worker-a',
                    lease_expires_at = TIMESTAMPTZ '2999-01-01 00:00:00+00'
                WHERE id = :event_id
                """
            ),
            {"event_id": event_id},
        )
    await engine.dispose()

    with pytest.raises(DBAPIError, match="durable voice work is unfinished"):
        await asyncio.to_thread(
            command.downgrade,
            config,
            "020_allow_reject_graph_privacy_controls",
        )

    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                UPDATE voice_media_events
                SET
                    reply_text = NULL,
                    reply_chunks_delivered = 0,
                    next_attempt_at = NULL,
                    lease_owner = NULL,
                    lease_expires_at = NULL
                WHERE id = :event_id
                """
            ),
            {"event_id": event_id},
        )
    await engine.dispose()

    await asyncio.to_thread(
        command.downgrade,
        config,
        "020_allow_reject_graph_privacy_controls",
    )
    engine = create_async_engine(database_url)
    try:
        columns = {column["name"] for column in await _columns(engine, "voice_media_events")}
        async with engine.connect() as connection:
            status = (
                await connection.execute(
                    text("SELECT status FROM voice_media_events WHERE id = :event_id"),
                    {"event_id": event_id},
                )
            ).scalar_one()

        assert {
            "reply_text",
            "transcription_attempt_count",
            "reply_chunks_delivered",
            "delivery_attempt_count",
            "next_attempt_at",
            "lease_owner",
            "lease_expires_at",
        }.isdisjoint(columns)
        assert status == "done"
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_note_identity_migration_preserves_indexed_duplicate() -> None:
    """When only a later duplicate has a chunk, 022 must keep that indexed row."""
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url)
    await _reset_public_schema(engine)
    await engine.dispose()
    config = _alembic_config()
    await asyncio.to_thread(command.upgrade, config, "021_voice_delivery_durability")

    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        dream_id = (
            await connection.execute(
                text(
                    """
                    INSERT INTO dream_entries (
                        source_doc_id, date, title, raw_text, word_count,
                        content_hash, segmentation_confidence
                    ) VALUES (
                        'doc-note-migration', NULL, 'Bridge', 'Dream body', 2,
                        'note-migration-dream-hash', 'high'
                    )
                    RETURNING id
                    """
                )
            )
        ).scalar_one()
        older_note_id = (
            await connection.execute(
                text(
                    """
                    INSERT INTO dream_notes (dream_id, text, source, created_at)
                    VALUES (:dream_id, 'same note', 'telegram', NOW() - INTERVAL '2 minutes')
                    RETURNING id
                    """
                ),
                {"dream_id": dream_id},
            )
        ).scalar_one()
        indexed_note_id = (
            await connection.execute(
                text(
                    """
                    INSERT INTO dream_notes (dream_id, text, source, created_at)
                    VALUES (
                        :dream_id,
                        chr(160) || 'same note' || chr(160),
                        'telegram',
                        NOW() - INTERVAL '1 minute'
                    )
                    RETURNING id
                    """
                ),
                {"dream_id": dream_id},
            )
        ).scalar_one()
        await connection.execute(
            text(
                """
                INSERT INTO dream_chunks (
                    dream_id, note_id, source_kind, chunk_index, chunk_text, embedding
                ) VALUES (
                    :dream_id, :note_id, 'note', 1, 'same note (incomplete)', NULL
                )
                """
            ),
            {"dream_id": dream_id, "note_id": older_note_id},
        )
        await connection.execute(
            text(
                """
                INSERT INTO dream_chunks (
                    dream_id, note_id, source_kind, chunk_index, chunk_text, embedding
                ) VALUES (
                    :dream_id, :note_id, 'note', 0, 'same note',
                    CAST(:embedding AS vector)
                )
                """
            ),
            {
                "dream_id": dream_id,
                "note_id": indexed_note_id,
                "embedding": "[" + ",".join(["0.1"] * 1536) + "]",
            },
        )
    await engine.dispose()

    await asyncio.to_thread(command.upgrade, config, "022_capture_idempotency")
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            notes = (
                (
                    await connection.execute(
                        text(
                            """
                        SELECT
                            note.id,
                            chunk.note_id AS indexed_note_id,
                            chunk.embedding IS NOT NULL AS has_embedding
                        FROM dream_notes AS note
                        LEFT JOIN dream_chunks AS chunk ON chunk.note_id = note.id
                        WHERE note.dream_id = :dream_id
                        """
                        ),
                        {"dream_id": dream_id},
                    )
                )
                .mappings()
                .all()
            )

        assert notes == [
            {
                "id": indexed_note_id,
                "indexed_note_id": indexed_note_id,
                "has_embedding": True,
            }
        ]
        assert indexed_note_id != older_note_id
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_write_receipt_migration_preserves_success_over_newer_failure() -> None:
    """A failed retry must not erase older proof that the document write landed."""
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url)
    await _reset_public_schema(engine)
    await engine.dispose()
    config = _alembic_config()
    await asyncio.to_thread(command.upgrade, config, "021_voice_delivery_durability")

    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        dream_id = (
            await connection.execute(
                text(
                    """
                    INSERT INTO dream_entries (
                        source_doc_id, date, title, raw_text, word_count,
                        content_hash, segmentation_confidence
                    ) VALUES (
                        'doc-receipt-migration', NULL, 'River', 'Dream body', 2,
                        'receipt-migration-dream-hash', 'high'
                    )
                    RETURNING id
                    """
                )
            )
        ).scalar_one()
        await connection.execute(
            text(
                """
                INSERT INTO dream_write_statuses (
                    dream_id, target_doc_id, status, attempt_count,
                    last_error, created_at, updated_at
                ) VALUES
                    (
                        :dream_id, 'target-doc', 'succeeded', 1, NULL,
                        NOW() - INTERVAL '2 minutes', NOW() - INTERVAL '2 minutes'
                    ),
                    (
                        :dream_id, 'target-doc', 'failed', 2, 'timeout',
                        NOW() - INTERVAL '1 minute', NOW() - INTERVAL '1 minute'
                    )
                """
            ),
            {"dream_id": dream_id},
        )
    await engine.dispose()

    await asyncio.to_thread(command.upgrade, config, "022_capture_idempotency")
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            statuses = (
                (
                    await connection.execute(
                        text(
                            """
                        SELECT status
                        FROM dream_write_statuses
                        WHERE dream_id = :dream_id AND target_doc_id = 'target-doc'
                        """
                        ),
                        {"dream_id": dream_id},
                    )
                )
                .scalars()
                .all()
            )

        assert statuses == ["succeeded"]
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_capture_identity_downgrade_explains_repeated_body_conflict() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url)
    await _reset_public_schema(engine)
    await engine.dispose()
    config = _alembic_config()
    await asyncio.to_thread(command.upgrade, config, "022_capture_idempotency")

    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO dream_entries (
                    source_doc_id, date, title, raw_text, word_count,
                    content_hash, source_event_key, segmentation_confidence
                ) VALUES
                    ('telegram:1', NULL, 'First', 'same body', 2,
                     'same-legitimate-hash', 'event-one', 'low'),
                    ('telegram:1', NULL, 'Second', 'same body', 2,
                     'same-legitimate-hash', 'event-two', 'low')
                """
            )
        )
    await engine.dispose()

    with pytest.raises(Exception, match="repeated dream bodies"):
        await asyncio.to_thread(
            command.downgrade,
            config,
            "021_voice_delivery_durability",
        )


@pytest.mark.anyio
async def test_capture_identity_downgrade_blocks_claimed_google_write() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url)
    await _reset_public_schema(engine)
    await engine.dispose()
    config = _alembic_config()
    await asyncio.to_thread(command.upgrade, config, "022_capture_idempotency")

    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        dream_id = (
            await connection.execute(
                text(
                    """
                    INSERT INTO dream_entries (
                        source_doc_id, date, title, raw_text, word_count,
                        content_hash, segmentation_confidence
                    ) VALUES (
                        'telegram:1', NULL, 'Claimed', 'body', 1,
                        'claimed-write-hash', 'low'
                    ) RETURNING id
                    """
                )
            )
        ).scalar_one()
        await connection.execute(
            text(
                """
                INSERT INTO dream_write_statuses (
                    dream_id, target_doc_id, status, attempt_count, claim_token,
                    created_at, updated_at
                ) VALUES (
                    :dream_id, 'target-doc', 'pending', 1, gen_random_uuid(),
                    now(), now()
                )
                """
            ),
            {"dream_id": dream_id},
        )
    await engine.dispose()

    with pytest.raises(Exception, match="Google Docs write is pending or claimed"):
        await asyncio.to_thread(
            command.downgrade,
            config,
            "021_voice_delivery_durability",
        )


@pytest.mark.anyio
async def test_processing_backfill_respects_google_doc_source_and_receipts() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url)
    await _reset_public_schema(engine)
    await engine.dispose()
    config = _alembic_config()
    await asyncio.to_thread(command.upgrade, config, "022_capture_idempotency")

    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        rows = (
            (
                await connection.execute(
                    text(
                        """
                        INSERT INTO dream_entries (
                            source_doc_id, date, title, raw_text, word_count,
                            content_hash, segmentation_confidence
                        ) VALUES
                            ('native-doc', NULL, 'Native', 'native body', 2,
                             'native-backfill-hash', 'high'),
                            ('telegram:1', NULL, 'Pending', 'pending body', 2,
                             'pending-backfill-hash', 'low'),
                            ('telegram:2', NULL, 'Written', 'written body', 2,
                             'written-backfill-hash', 'low')
                        RETURNING id, source_doc_id
                        """
                    )
                )
            )
            .mappings()
            .all()
        )
        ids_by_source = {row["source_doc_id"]: row["id"] for row in rows}
        await connection.execute(
            text(
                """
                INSERT INTO dream_write_statuses (
                    dream_id, target_doc_id, status, attempt_count,
                    created_at, updated_at
                ) VALUES (:dream_id, 'target-doc', 'succeeded', 1, now(), now())
                """
            ),
            {"dream_id": ids_by_source["telegram:2"]},
        )
    await engine.dispose()

    await asyncio.to_thread(command.upgrade, config, "023_dream_processing_jobs")
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            jobs = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT dream_id, stage, status
                            FROM dream_processing_jobs
                            ORDER BY dream_id, stage
                            """
                        )
                    )
                )
                .mappings()
                .all()
            )

        jobs_by_dream = {
            dream_id: {row["stage"]: row["status"] for row in jobs if row["dream_id"] == dream_id}
            for dream_id in ids_by_source.values()
        }
        assert all(len(stages) == 4 for stages in jobs_by_dream.values())
        assert jobs_by_dream[ids_by_source["native-doc"]]["gdocs"] == "succeeded"
        # Legacy Telegram rows without a success receipt are ambiguous: the
        # write may have landed before a crash.  They require explicit retry,
        # never an automatic startup append.
        assert jobs_by_dream[ids_by_source["telegram:1"]]["gdocs"] == "failed"
        assert jobs_by_dream[ids_by_source["telegram:2"]]["gdocs"] == "succeeded"
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_dream_processing_downgrade_blocks_unfinished_durable_work() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url)
    await _reset_public_schema(engine)
    await engine.dispose()
    config = _alembic_config()
    await asyncio.to_thread(command.upgrade, config, "022_capture_idempotency")

    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO dream_entries (
                    source_doc_id, date, title, raw_text, word_count,
                    content_hash, segmentation_confidence
                ) VALUES (
                    'telegram:99', NULL, 'Pending dream', 'pending body', 2,
                    'pending-downgrade-hash', 'low'
                )
                """
            )
        )
    await engine.dispose()

    await asyncio.to_thread(command.upgrade, config, "023_dream_processing_jobs")
    with pytest.raises(Exception, match="durable dream work is unfinished"):
        await asyncio.to_thread(
            command.downgrade,
            config,
            "022_capture_idempotency",
        )

    engine = create_async_engine(database_url)
    assert await _trigger_metadata(
        engine,
        "dream_entries",
        "ensure_dream_processing_jobs_023",
    ) == {
        "is_deferrable": True,
        "is_initially_deferred": True,
    }
    assert await _function_exists(engine, "ensure_dream_processing_jobs_023")
    async with engine.begin() as connection:
        await connection.execute(text("UPDATE dream_processing_jobs SET status = 'succeeded'"))
    await engine.dispose()

    await asyncio.to_thread(
        command.downgrade,
        config,
        "022_capture_idempotency",
    )
    engine = create_async_engine(database_url)
    try:
        assert "dream_processing_jobs" not in await _table_names(engine)
        assert (
            await _trigger_metadata(
                engine,
                "dream_entries",
                "ensure_dream_processing_jobs_023",
            )
            is None
        )
        assert not await _function_exists(engine, "ensure_dream_processing_jobs_023")
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_enrichment_dedupe_repoints_history_and_research() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url)
    await _reset_public_schema(engine)
    await engine.dispose()
    config = _alembic_config()
    await asyncio.to_thread(command.upgrade, config, "022_capture_idempotency")

    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        dream_id = (
            await connection.execute(
                text(
                    """
                    INSERT INTO dream_entries (
                        source_doc_id, date, title, raw_text, word_count,
                        content_hash, segmentation_confidence
                    ) VALUES (
                        'doc-dedupe', NULL, 'Dedupe', 'body', 1,
                        'enrichment-dedupe-hash', 'high'
                    ) RETURNING id
                    """
                )
            )
        ).scalar_one()
        category_id = (
            await connection.execute(
                text(
                    """
                    INSERT INTO theme_categories (name, status)
                    VALUES ('dedupe-category', 'active') RETURNING id
                    """
                )
            )
        ).scalar_one()
        theme_loser = (
            await connection.execute(
                text(
                    """
                    INSERT INTO dream_themes (
                        dream_id, category_id, salience, status, match_type, fragments
                    ) VALUES (
                        :dream_id, :category_id, 0.2, 'draft', 'semantic', '[]'::jsonb
                    ) RETURNING id
                    """
                ),
                {"dream_id": dream_id, "category_id": category_id},
            )
        ).scalar_one()
        theme_keeper = (
            await connection.execute(
                text(
                    """
                    INSERT INTO dream_themes (
                        dream_id, category_id, salience, status, match_type, fragments
                    ) VALUES (
                        :dream_id, :category_id, 0.9, 'confirmed', 'literal', '[]'::jsonb
                    ) RETURNING id
                    """
                ),
                {"dream_id": dream_id, "category_id": category_id},
            )
        ).scalar_one()
        await connection.execute(
            text(
                """
                INSERT INTO annotation_versions (
                    entity_type, entity_id, snapshot, changed_by
                ) VALUES ('dream_theme', :entity_id, '{}'::jsonb, 'migration-test')
                """
            ),
            {"entity_id": theme_loser},
        )
        motif_loser = (
            await connection.execute(
                text(
                    """
                    INSERT INTO motif_inductions (
                        dream_id, label, rationale, confidence, status, fragments
                    ) VALUES (
                        :dream_id, '  SAME   MOTIF ', 'draft', 'low', 'draft', '[]'::jsonb
                    ) RETURNING id
                    """
                ),
                {"dream_id": dream_id},
            )
        ).scalar_one()
        motif_keeper = (
            await connection.execute(
                text(
                    """
                    INSERT INTO motif_inductions (
                        dream_id, label, rationale, confidence, status, fragments
                    ) VALUES (
                        :dream_id, 'same motif', 'confirmed', 'high', 'confirmed', '[]'::jsonb
                    ) RETURNING id
                    """
                ),
                {"dream_id": dream_id},
            )
        ).scalar_one()
        await connection.execute(
            text(
                """
                INSERT INTO annotation_versions (
                    entity_type, entity_id, snapshot, changed_by
                ) VALUES ('motif_induction', :entity_id, '{}'::jsonb, 'migration-test')
                """
            ),
            {"entity_id": motif_loser},
        )
        await connection.execute(
            text(
                """
                INSERT INTO research_results (
                    motif_id, dream_id, query_label, triggered_by
                ) VALUES (:motif_id, :dream_id, 'same motif', 'migration-test')
                """
            ),
            {"motif_id": motif_loser, "dream_id": dream_id},
        )
    await engine.dispose()

    await asyncio.to_thread(command.upgrade, config, "023_dream_processing_jobs")
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            theme_ids = (
                (
                    await connection.execute(
                        text("SELECT id FROM dream_themes WHERE dream_id = :dream_id"),
                        {"dream_id": dream_id},
                    )
                )
                .scalars()
                .all()
            )
            motif_ids = (
                (
                    await connection.execute(
                        text("SELECT id FROM motif_inductions WHERE dream_id = :dream_id"),
                        {"dream_id": dream_id},
                    )
                )
                .scalars()
                .all()
            )
            history_rows = (
                (
                    await connection.execute(
                        text(
                            """
                        SELECT entity_type, entity_id, snapshot
                        FROM annotation_versions
                        WHERE changed_by = 'migration-test'
                        """
                        )
                    )
                )
                .mappings()
                .all()
            )
            research_motif_id = await connection.scalar(
                text("SELECT motif_id FROM research_results WHERE dream_id = :dream_id"),
                {"dream_id": dream_id},
            )

        assert theme_ids == [theme_keeper]
        assert motif_ids == [motif_keeper]
        assert {(row["entity_type"], row["entity_id"]) for row in history_rows} == {
            ("dream_theme", theme_loser),
            ("dream_theme", theme_keeper),
            ("motif_induction", motif_loser),
            ("motif_induction", motif_keeper),
        }
        keeper_history = [
            row for row in history_rows if row["entity_id"] in {theme_keeper, motif_keeper}
        ]
        assert len(keeper_history) == 2
        assert all(row["snapshot"]["entity_id"] == str(row["entity_id"]) for row in keeper_history)
        assert research_motif_id == motif_keeper
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_motif_dedupe_aborts_for_append_only_privacy_receipt() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url)
    await _reset_public_schema(engine)
    await engine.dispose()
    config = _alembic_config()
    await asyncio.to_thread(command.upgrade, config, "022_capture_idempotency")

    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        dream_id = (
            await connection.execute(
                text(
                    """
                    INSERT INTO dream_entries (
                        source_doc_id, date, title, raw_text, word_count,
                        content_hash, segmentation_confidence
                    ) VALUES (
                        'doc-private-motif', NULL, 'Private', 'body', 1,
                        'private-motif-hash', 'high'
                    ) RETURNING id
                    """
                )
            )
        ).scalar_one()
        loser_id = (
            await connection.execute(
                text(
                    """
                    INSERT INTO motif_inductions (
                        dream_id, label, confidence, status, fragments
                    ) VALUES (
                        :dream_id, 'Private   Duplicate', 'low', 'draft', '[]'::jsonb
                    ) RETURNING id
                    """
                ),
                {"dream_id": dream_id},
            )
        ).scalar_one()
        await connection.execute(
            text(
                """
                INSERT INTO motif_inductions (
                    dream_id, label, confidence, status, fragments
                ) VALUES (
                    :dream_id, 'private duplicate', 'high', 'confirmed', '[]'::jsonb
                )
                """
            ),
            {"dream_id": dream_id},
        )
        await connection.execute(
            text(
                """
                INSERT INTO dream_graph_privacy_controls (
                    subject_type, subject_id, action, control_payload,
                    receipt_payload, changed_by
                ) VALUES (
                    'graph_node', :subject_id, 'delete', '{}'::jsonb,
                    '{}'::jsonb, 'migration-test'
                )
                """
            ),
            {"subject_id": f"motif_induction:{loser_id}"},
        )
    await engine.dispose()

    with pytest.raises(Exception, match="append-only privacy controls"):
        await asyncio.to_thread(
            command.upgrade,
            config,
            "023_dream_processing_jobs",
        )


@pytest.mark.anyio
async def test_voice_media_events_reject_duplicate_telegram_update(
    migrated_engine: AsyncEngine,
) -> None:
    insert_voice = text(
        """
        INSERT INTO voice_media_events (
            chat_id, telegram_message_id, telegram_file_id, duration_seconds
        ) VALUES (77, 99, :file_id, 5)
        """
    )
    async with migrated_engine.begin() as connection:
        await connection.execute(insert_voice, {"file_id": "voice-a"})
    with pytest.raises(IntegrityError):
        async with migrated_engine.begin() as connection:
            await connection.execute(insert_voice, {"file_id": "voice-b"})


@pytest.mark.anyio
async def test_voice_ingress_get_or_create_is_idempotent(
    migrated_engine: AsyncEngine,
) -> None:
    session_factory = async_sessionmaker(migrated_engine, expire_on_commit=False)
    first, first_created = await get_or_create_voice_media_event(
        session_factory,
        chat_id=77,
        telegram_message_id=101,
        telegram_file_id="voice-a",
        duration_seconds=5,
    )
    duplicate, duplicate_created = await get_or_create_voice_media_event(
        session_factory,
        chat_id=77,
        telegram_message_id=101,
        telegram_file_id="voice-a",
        duration_seconds=5,
    )

    assert first_created is True
    assert duplicate_created is False
    assert duplicate.id == first.id


@pytest.mark.anyio
async def test_voice_event_claim_is_exclusive_and_stale_owner_cannot_mutate(
    migrated_engine: AsyncEngine,
) -> None:
    session_factory = async_sessionmaker(migrated_engine, expire_on_commit=False)
    event, _created = await get_or_create_voice_media_event(
        session_factory,
        chat_id=77,
        telegram_message_id=202,
        telegram_file_id="voice-lease",
        duration_seconds=5,
    )

    first_claim = await claim_voice_media_event(
        session_factory,
        event.id,
        lease_owner="worker-a",
        lease_seconds=60,
    )
    overlapping_claim = await claim_voice_media_event(
        session_factory,
        event.id,
        lease_owner="worker-b",
        lease_seconds=60,
    )
    assert first_claim is not None
    assert overlapping_claim is None

    assert await release_voice_media_lease(
        session_factory,
        event.id,
        lease_owner="worker-a",
        retry_delay_seconds=0,
    )
    second_claim = await claim_voice_media_event(
        session_factory,
        event.id,
        lease_owner="worker-b",
        lease_seconds=60,
    )
    assert second_claim is not None
    with pytest.raises(VoiceLeaseLost):
        await store_voice_delivery_progress(
            session_factory,
            event.id,
            1,
            lease_owner="worker-a",
        )


@pytest.mark.anyio
async def test_voice_malformed_reply_failure_exits_recovery_queue(
    migrated_engine: AsyncEngine,
) -> None:
    session_factory = async_sessionmaker(migrated_engine, expire_on_commit=False)
    event, _created = await get_or_create_voice_media_event(
        session_factory,
        chat_id=77,
        telegram_message_id=303,
        telegram_file_id="voice-malformed-reply",
        duration_seconds=5,
    )
    claimed = await claim_voice_media_event(
        session_factory,
        event.id,
        lease_owner="worker-a",
        lease_seconds=60,
    )
    assert claimed is not None
    async with migrated_engine.begin() as connection:
        await connection.execute(
            text(
                """
                UPDATE voice_media_events
                SET status = 'reply_pending',
                    reply_text = NULL,
                    reply_chunks_delivered = 2,
                    next_attempt_at = NULL
                WHERE id = :event_id
                """
            ),
            {"event_id": event.id},
        )

    await mark_voice_reply_failed(session_factory, event.id, lease_owner="worker-a")

    async with migrated_engine.connect() as connection:
        row = (
            (
                await connection.execute(
                    text(
                        """
                    SELECT status, reply_text, reply_chunks_delivered,
                           next_attempt_at, lease_owner, lease_expires_at
                    FROM voice_media_events
                    WHERE id = :event_id
                    """
                    ),
                    {"event_id": event.id},
                )
            )
            .mappings()
            .one()
        )
    assert row["status"] == "failed"
    assert row["reply_text"] is None
    assert row["reply_chunks_delivered"] == 0
    assert row["next_attempt_at"] is None
    assert row["lease_owner"] is None
    assert row["lease_expires_at"] is None
    assert (
        await claim_voice_media_event(
            session_factory,
            event.id,
            lease_owner="worker-b",
            lease_seconds=60,
        )
        is None
    )


@pytest.mark.anyio
async def test_restore_privacy_action_is_validated_and_blocks_unsafe_downgrade(
    migrated_engine: AsyncEngine,
) -> None:
    insert_control = text(
        """
        INSERT INTO dream_graph_privacy_controls (
            subject_type, subject_id, action, control_payload,
            receipt_payload, changed_by
        ) VALUES (
            'graph_node', :subject_id, :action, '{}'::jsonb, '{}'::jsonb, 'test'
        )
        """
    )
    async with migrated_engine.begin() as connection:
        await connection.execute(
            insert_control,
            {"subject_id": "motif:restored", "action": "restore"},
        )

    with pytest.raises(IntegrityError):
        async with migrated_engine.begin() as connection:
            await connection.execute(
                insert_control,
                {"subject_id": "motif:invalid", "action": "unknown"},
            )

    with pytest.raises(
        RuntimeError,
        match="append-only restore receipts exist",
    ):
        await asyncio.to_thread(
            command.downgrade,
            _alembic_config(),
            "023_dream_processing_jobs",
        )
