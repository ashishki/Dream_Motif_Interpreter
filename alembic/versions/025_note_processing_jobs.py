"""add durable note processing outbox

Revision ID: 025_note_processing_jobs
Revises: 024_restore_graph_controls
Create Date: 2026-08-30 00:00:04
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "025_note_processing_jobs"
down_revision: Union[str, None] = "024_restore_graph_controls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Take a transaction-scoped snapshot boundary before the legacy backfill.
    # In-flight legacy writers finish before the snapshot; deployment must not
    # keep pre-outbox writers running after this migration completes.
    op.execute("LOCK TABLE dream_notes, dream_chunks IN SHARE ROW EXCLUSIVE MODE")
    op.create_table(
        "note_processing_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "note_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dream_notes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(length=16), nullable=False, server_default="index"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lock_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_doc_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'retryable', 'succeeded', 'failed')",
            name="ck_note_processing_jobs_status",
        ),
        sa.CheckConstraint(
            "stage IN ('index', 'gdocs')",
            name="ck_note_processing_jobs_stage",
        ),
        sa.CheckConstraint(
            "(stage = 'gdocs' AND target_doc_id IS NOT NULL) "
            "OR (stage = 'index' AND target_doc_id IS NULL)",
            name="ck_note_processing_jobs_target",
        ),
        sa.UniqueConstraint(
            "note_id",
            "stage",
            name="uq_note_processing_jobs_note_stage",
        ),
    )
    op.create_index(
        "ix_note_processing_jobs_note_id",
        "note_processing_jobs",
        ["note_id"],
        unique=False,
    )
    op.create_index(
        "ix_note_processing_jobs_claim",
        "note_processing_jobs",
        ["status", "available_at", "locked_at"],
        unique=False,
    )

    # Legacy note writers released after the migration lock do not create an
    # outbox row.  Evaluate at transaction commit so an embedding inserted in
    # the same transaction is durable evidence of completed indexing.  Google
    # Docs delivery cannot be inferred safely for a legacy note and is never
    # manufactured by this compatibility trigger.
    op.execute(
        """
        CREATE FUNCTION ensure_note_processing_job_025()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $function$
        BEGIN
            INSERT INTO note_processing_jobs (
                note_id,
                stage,
                status,
                attempt_count,
                available_at,
                created_at,
                updated_at
            )
            SELECT
                note.id,
                'index',
                CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM dream_chunks AS chunk
                        WHERE chunk.note_id = note.id
                          AND chunk.embedding IS NOT NULL
                    ) THEN 'succeeded'
                    ELSE 'pending'
                END,
                0,
                now(),
                now(),
                now()
            FROM dream_notes AS note
            WHERE note.id = NEW.id
            ON CONFLICT (note_id, stage) DO NOTHING;

            RETURN NEW;
        END
        $function$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER ensure_note_processing_job_025
        AFTER INSERT ON dream_notes
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION ensure_note_processing_job_025()
        """
    )

    # Legacy notes need indexing recovery only.  Their Google Docs provenance
    # cannot be reconstructed safely, so this migration must never enqueue a
    # historical external write.
    op.execute(
        """
        INSERT INTO note_processing_jobs (
            note_id,
            stage,
            status,
            attempt_count,
            available_at,
            created_at,
            updated_at
        )
        SELECT
            note.id,
            'index',
            CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM dream_chunks AS chunk
                    WHERE chunk.note_id = note.id
                      AND chunk.embedding IS NOT NULL
                ) THEN 'succeeded'
                ELSE 'pending'
            END,
            0,
            now(),
            now(),
            now()
        FROM dream_notes AS note
        ON CONFLICT (note_id, stage) DO NOTHING
        """
    )


def downgrade() -> None:
    # Serialize the unfinished-work check with atomic note+job writers.  A
    # writer that started first becomes visible to the guard; a later writer
    # cannot commit a note after its outbox table has been removed.
    op.execute(
        "LOCK TABLE dream_chunks, dream_notes, note_processing_jobs IN SHARE ROW EXCLUSIVE MODE"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM note_processing_jobs
                WHERE status <> 'succeeded'
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade 025_note_processing_jobs while durable note work is unfinished';
            END IF;
        END
        $$
        """
    )
    op.execute("DROP TRIGGER IF EXISTS ensure_note_processing_job_025 ON dream_notes")
    op.execute("DROP FUNCTION IF EXISTS ensure_note_processing_job_025()")
    op.drop_index("ix_note_processing_jobs_claim", table_name="note_processing_jobs")
    op.drop_index("ix_note_processing_jobs_note_id", table_name="note_processing_jobs")
    op.drop_table("note_processing_jobs")
