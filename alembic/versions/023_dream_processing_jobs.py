"""add durable dream processing outbox

Revision ID: 023_dream_processing_jobs
Revises: 022_capture_idempotency
Create Date: 2026-08-30 00:00:02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "023_dream_processing_jobs"
down_revision: Union[str, None] = "022_capture_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Hold a transaction-scoped writer barrier across dedupe, reference
    # preservation, and the outbox snapshot.  Without it an old application
    # process could commit a dream after the backfill or attach history/privacy
    # state to a duplicate after the survivor mapping was computed.
    op.execute(
        """
        LOCK TABLE
            annotation_versions,
            dream_chunks,
            dream_entries,
            dream_graph_privacy_controls,
            dream_themes,
            dream_write_statuses,
            motif_inductions,
            research_results
        IN SHARE ROW EXCLUSIVE MODE
        """
    )
    op.add_column(
        "motif_inductions",
        sa.Column("normalized_label", sa.Text(), nullable=True),
    )
    connection = op.get_bind()
    motif_rows = (
        connection.execute(sa.text("SELECT id, label FROM motif_inductions")).mappings().all()
    )
    for motif_row in motif_rows:
        normalized_label = " ".join(str(motif_row["label"]).casefold().split())
        connection.execute(
            sa.text(
                """
                UPDATE motif_inductions
                SET normalized_label = :normalized_label
                WHERE id = :motif_id
                """
            ),
            {
                "motif_id": motif_row["id"],
                "normalized_label": normalized_label,
            },
        )
    op.alter_column("motif_inductions", "normalized_label", nullable=False)
    # Concurrent/replayed enrichment must converge on one current row.  Keep
    # the strongest user decision before enforcing the identity constraints.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                first_value(id) OVER (
                    PARTITION BY dream_id, category_id
                    ORDER BY
                        CASE status
                            WHEN 'confirmed' THEN 3
                            WHEN 'rejected' THEN 2
                            ELSE 1
                        END DESC,
                        deprecated ASC,
                        created_at DESC,
                        id::text DESC
                ) AS keeper_id,
                row_number() OVER (
                    PARTITION BY dream_id, category_id
                    ORDER BY
                        CASE status
                            WHEN 'confirmed' THEN 3
                            WHEN 'rejected' THEN 2
                            ELSE 1
                        END DESC,
                        deprecated ASC,
                        created_at DESC,
                        id::text DESC
                ) AS row_rank
            FROM dream_themes
        )
        INSERT INTO annotation_versions (
            id,
            entity_type,
            entity_id,
            snapshot,
            changed_by,
            created_at
        )
        SELECT
            gen_random_uuid(),
            history.entity_type,
            ranked.keeper_id,
            jsonb_set(
                history.snapshot,
                '{entity_id}',
                to_jsonb(ranked.keeper_id::text),
                true
            ),
            history.changed_by,
            history.created_at
        FROM annotation_versions AS history
        JOIN ranked ON history.entity_id = ranked.id
        WHERE history.entity_type = 'dream_theme'
          AND ranked.row_rank > 1
        """
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY dream_id, category_id
                    ORDER BY
                        CASE status
                            WHEN 'confirmed' THEN 3
                            WHEN 'rejected' THEN 2
                            ELSE 1
                        END DESC,
                        deprecated ASC,
                        created_at DESC,
                        id::text DESC
                ) AS row_rank
            FROM dream_themes
        )
        DELETE FROM dream_themes AS duplicate
        USING ranked
        WHERE duplicate.id = ranked.id
          AND ranked.row_rank > 1
        """
    )
    op.create_unique_constraint(
        "uq_dream_themes_dream_category",
        "dream_themes",
        ["dream_id", "category_id"],
    )
    # Privacy controls are append-only signed receipts whose embedded motif
    # identifiers cannot be rewritten.  Abort before merging any referenced
    # duplicate rather than leaving a control attached to a deleted node.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                WITH ranked AS (
                    SELECT
                        id,
                        row_number() OVER (
                            PARTITION BY dream_id, normalized_label
                            ORDER BY
                                CASE status
                                    WHEN 'confirmed' THEN 3
                                    WHEN 'rejected' THEN 2
                                    ELSE 1
                                END DESC,
                                created_at DESC,
                                id::text DESC
                        ) AS row_rank
                    FROM motif_inductions
                )
                SELECT 1
                FROM ranked
                JOIN dream_graph_privacy_controls AS control
                  ON control.subject_id LIKE '%' || ranked.id::text || '%'
                  OR control.control_payload::text LIKE '%' || ranked.id::text || '%'
                  OR control.receipt_payload::text LIKE '%' || ranked.id::text || '%'
                WHERE ranked.row_rank > 1
            ) THEN
                RAISE EXCEPTION
                    'Cannot merge duplicate motif inductions referenced by append-only privacy controls';
            END IF;
        END
        $$
        """
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                first_value(id) OVER (
                    PARTITION BY dream_id, normalized_label
                    ORDER BY
                        CASE status
                            WHEN 'confirmed' THEN 3
                            WHEN 'rejected' THEN 2
                            ELSE 1
                        END DESC,
                        created_at DESC,
                        id::text DESC
                ) AS keeper_id,
                row_number() OVER (
                    PARTITION BY dream_id, normalized_label
                    ORDER BY
                        CASE status
                            WHEN 'confirmed' THEN 3
                            WHEN 'rejected' THEN 2
                            ELSE 1
                        END DESC,
                        created_at DESC,
                        id::text DESC
                ) AS row_rank
            FROM motif_inductions
        )
        UPDATE research_results AS research
        SET motif_id = ranked.keeper_id
        FROM ranked
        WHERE research.motif_id = ranked.id
          AND ranked.row_rank > 1
        """
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                first_value(id) OVER (
                    PARTITION BY dream_id, normalized_label
                    ORDER BY
                        CASE status
                            WHEN 'confirmed' THEN 3
                            WHEN 'rejected' THEN 2
                            ELSE 1
                        END DESC,
                        created_at DESC,
                        id::text DESC
                ) AS keeper_id,
                row_number() OVER (
                    PARTITION BY dream_id, normalized_label
                    ORDER BY
                        CASE status
                            WHEN 'confirmed' THEN 3
                            WHEN 'rejected' THEN 2
                            ELSE 1
                        END DESC,
                        created_at DESC,
                        id::text DESC
                ) AS row_rank
            FROM motif_inductions
        )
        INSERT INTO annotation_versions (
            id,
            entity_type,
            entity_id,
            snapshot,
            changed_by,
            created_at
        )
        SELECT
            gen_random_uuid(),
            history.entity_type,
            ranked.keeper_id,
            jsonb_set(
                history.snapshot,
                '{entity_id}',
                to_jsonb(ranked.keeper_id::text),
                true
            ),
            history.changed_by,
            history.created_at
        FROM annotation_versions AS history
        JOIN ranked ON history.entity_id = ranked.id
        WHERE history.entity_type = 'motif_induction'
          AND ranked.row_rank > 1
        """
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY dream_id, normalized_label
                    ORDER BY
                        CASE status
                            WHEN 'confirmed' THEN 3
                            WHEN 'rejected' THEN 2
                            ELSE 1
                        END DESC,
                        created_at DESC,
                        id::text DESC
                ) AS row_rank
            FROM motif_inductions
        )
        DELETE FROM motif_inductions AS duplicate
        USING ranked
        WHERE duplicate.id = ranked.id
          AND ranked.row_rank > 1
        """
    )
    op.create_unique_constraint(
        "uq_motif_inductions_dream_normalized_label",
        "motif_inductions",
        ["dream_id", "normalized_label"],
    )

    op.create_table(
        "dream_processing_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "dream_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dream_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("stage", sa.String(length=16), nullable=False, server_default="index"),
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
            name="ck_dream_processing_jobs_status",
        ),
        sa.CheckConstraint(
            "stage IN ('index', 'analysis', 'motif', 'gdocs')",
            name="ck_dream_processing_jobs_stage",
        ),
        sa.UniqueConstraint(
            "dream_id",
            "stage",
            name="uq_dream_processing_jobs_dream_stage",
        ),
    )
    op.create_index(
        "ix_dream_processing_jobs_dream_id",
        "dream_processing_jobs",
        ["dream_id"],
        unique=False,
    )
    op.create_index(
        "ix_dream_processing_jobs_claim",
        "dream_processing_jobs",
        ["status", "available_at", "locked_at"],
        unique=False,
    )

    # A rolling deployment can release a legacy INSERT only after this
    # migration commits.  That writer does not know about the outbox, so a
    # deferred constraint trigger fills only missing jobs from the complete
    # transaction state.  Imported Google Docs are already delivered; a new
    # Telegram capture is safe to enqueue because it has no legacy delivery
    # receipt at the INSERT boundary.
    op.execute(
        """
        CREATE FUNCTION ensure_dream_processing_jobs_023()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $function$
        BEGIN
            INSERT INTO dream_processing_jobs (
                dream_id,
                status,
                stage,
                attempt_count,
                available_at,
                created_at,
                updated_at
            )
            SELECT
                dream.id,
                CASE
                    WHEN stage.value = 'index' AND EXISTS (
                        SELECT 1
                        FROM dream_chunks AS chunk
                        WHERE chunk.dream_id = dream.id
                          AND chunk.source_kind = 'dream_text'
                          AND chunk.embedding IS NOT NULL
                    ) THEN 'succeeded'
                    WHEN stage.value = 'analysis' AND EXISTS (
                        SELECT 1
                        FROM dream_themes AS theme
                        WHERE theme.dream_id = dream.id
                    ) THEN 'succeeded'
                    WHEN stage.value = 'motif' AND EXISTS (
                        SELECT 1
                        FROM motif_inductions AS motif
                        WHERE motif.dream_id = dream.id
                    ) THEN 'succeeded'
                    WHEN stage.value = 'gdocs'
                     AND dream.source_doc_id NOT LIKE 'telegram:%'
                    THEN 'succeeded'
                    ELSE 'pending'
                END,
                stage.value,
                0,
                now(),
                now(),
                now()
            FROM dream_entries AS dream
            CROSS JOIN (
                VALUES ('index'), ('analysis'), ('motif'), ('gdocs')
            ) AS stage(value)
            WHERE dream.id = NEW.id
            ON CONFLICT (dream_id, stage) DO NOTHING;

            RETURN NEW;
        END
        $function$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER ensure_dream_processing_jobs_023
        AFTER INSERT ON dream_entries
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION ensure_dream_processing_jobs_023()
        """
    )

    # Source-aware recovery for rows captured before the durable outbox was
    # deployed.  Evidence of completed work wins; a dream read from a Google
    # Doc is already present there and must never be appended again.
    op.execute(
        """
        INSERT INTO dream_processing_jobs (
            dream_id,
            status,
            stage,
            attempt_count,
            last_error,
            available_at,
            created_at,
            updated_at
        )
        SELECT
            dream.id,
            CASE
                WHEN stage.value = 'index' AND EXISTS (
                    SELECT 1
                    FROM dream_chunks AS chunk
                    WHERE chunk.dream_id = dream.id
                      AND chunk.source_kind = 'dream_text'
                      AND chunk.embedding IS NOT NULL
                ) THEN 'succeeded'
                WHEN stage.value = 'analysis' AND EXISTS (
                    SELECT 1
                    FROM dream_themes AS theme
                    WHERE theme.dream_id = dream.id
                ) THEN 'succeeded'
                WHEN stage.value = 'motif' AND EXISTS (
                    SELECT 1
                    FROM motif_inductions AS motif
                    WHERE motif.dream_id = dream.id
                ) THEN 'succeeded'
                WHEN stage.value = 'gdocs' AND (
                    dream.source_doc_id NOT LIKE 'telegram:%'
                    OR EXISTS (
                        SELECT 1
                        FROM dream_write_statuses AS receipt
                        WHERE receipt.dream_id = dream.id
                          AND receipt.status = 'succeeded'
                    )
                ) THEN 'succeeded'
                WHEN stage.value = 'gdocs' THEN 'failed'
                ELSE 'pending'
            END,
            stage.value,
            0,
            CASE
                WHEN stage.value = 'gdocs'
                 AND dream.source_doc_id LIKE 'telegram:%'
                 AND NOT EXISTS (
                    SELECT 1
                    FROM dream_write_statuses AS receipt
                    WHERE receipt.dream_id = dream.id
                      AND receipt.status = 'succeeded'
                 )
                THEN 'Legacy Google Docs delivery requires explicit reconciliation'
                ELSE NULL
            END,
            now(),
            now(),
            now()
        FROM dream_entries AS dream
        CROSS JOIN (
            VALUES ('index'), ('analysis'), ('motif'), ('gdocs')
        ) AS stage(value)
        ON CONFLICT (dream_id, stage) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        LOCK TABLE
            dream_entries,
            dream_processing_jobs,
            dream_themes,
            motif_inductions
        IN SHARE ROW EXCLUSIVE MODE
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM dream_processing_jobs
                WHERE status <> 'succeeded'
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade 023_dream_processing_jobs while durable dream work is unfinished';
            END IF;
        END
        $$
        """
    )
    op.execute("DROP TRIGGER IF EXISTS ensure_dream_processing_jobs_023 ON dream_entries")
    op.execute("DROP FUNCTION IF EXISTS ensure_dream_processing_jobs_023()")
    op.drop_index("ix_dream_processing_jobs_claim", table_name="dream_processing_jobs")
    op.drop_index("ix_dream_processing_jobs_dream_id", table_name="dream_processing_jobs")
    op.drop_table("dream_processing_jobs")
    op.drop_constraint(
        "uq_motif_inductions_dream_normalized_label",
        "motif_inductions",
        type_="unique",
    )
    op.drop_column("motif_inductions", "normalized_label")
    op.drop_constraint(
        "uq_dream_themes_dream_category",
        "dream_themes",
        type_="unique",
    )
