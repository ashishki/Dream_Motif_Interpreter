"""make archive capture and Google Docs writes idempotent

Revision ID: 022_capture_idempotency
Revises: 021_voice_delivery_durability
Create Date: 2026-08-30 00:00:01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "022_capture_idempotency"
down_revision: Union[str, None] = "021_voice_delivery_durability"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Keep the hash backfill/dedupe and the new uniqueness contracts on one
    # stable writer snapshot while an older application version may still be
    # shutting down.
    op.execute(
        """
        LOCK TABLE
            dream_chunks,
            dream_entries,
            dream_notes,
            dream_write_statuses
        IN SHARE ROW EXCLUSIVE MODE
        """
    )
    op.add_column(
        "dream_entries",
        sa.Column("source_event_key", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "ix_dream_entries_source_event_key",
        "dream_entries",
        ["source_event_key"],
        unique=True,
    )
    op.drop_constraint(
        "uq_dream_entries_content_hash",
        "dream_entries",
        type_="unique",
    )
    op.create_index(
        "ix_dream_entries_content_hash",
        "dream_entries",
        ["content_hash"],
        unique=False,
    )
    op.add_column(
        "dream_entries",
        sa.Column("source_entry_key", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "ix_dream_entries_source_entry_key",
        "dream_entries",
        ["source_entry_key"],
        unique=True,
    )

    op.add_column(
        "dream_notes",
        sa.Column("content_hash", sa.String(length=64), nullable=True),
    )
    op.execute(
        """
        UPDATE dream_notes
        SET content_hash = encode(
            digest(
                btrim(
                    text,
                    ' '
                    || chr(9) || chr(10) || chr(11) || chr(12) || chr(13)
                    || chr(28) || chr(29) || chr(30) || chr(31)
                    || chr(133) || chr(160) || chr(5760)
                    || chr(8192) || chr(8193) || chr(8194) || chr(8195)
                    || chr(8196) || chr(8197) || chr(8198) || chr(8199)
                    || chr(8200) || chr(8201) || chr(8202)
                    || chr(8232) || chr(8233) || chr(8239)
                    || chr(8287) || chr(12288)
                ),
                'sha256'
            ),
            'hex'
        )
        WHERE content_hash IS NULL
        """
    )
    # Older versions performed an application-level lookup only.  Prefer a
    # duplicate that already owns a semantic chunk, then the oldest row, so
    # the cleanup does not discard completed indexing work.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                note.id,
                row_number() OVER (
                    PARTITION BY note.dream_id, note.content_hash
                    ORDER BY
                        EXISTS (
                            SELECT 1
                            FROM dream_chunks AS chunk
                            WHERE chunk.note_id = note.id
                              AND chunk.embedding IS NOT NULL
                        ) DESC,
                        EXISTS (
                            SELECT 1
                            FROM dream_chunks AS chunk
                            WHERE chunk.note_id = note.id
                        ) DESC,
                        note.created_at ASC,
                        note.id::text ASC
                ) AS row_rank
            FROM dream_notes AS note
        )
        DELETE FROM dream_notes AS duplicate
        USING ranked
        WHERE duplicate.id = ranked.id
          AND ranked.row_rank > 1
        """
    )
    op.alter_column("dream_notes", "content_hash", nullable=False)
    op.create_unique_constraint(
        "uq_dream_notes_dream_id_content_hash",
        "dream_notes",
        ["dream_id", "content_hash"],
    )

    # Collapse historical per-attempt rows into one durable receipt per
    # dream/document.  Preserve evidence of any completed write even when a
    # newer retry failed; otherwise a backfill could append the same dream.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY dream_id, target_doc_id
                    ORDER BY
                        (status = 'succeeded') DESC,
                        updated_at DESC,
                        id::text DESC
                ) AS row_rank
            FROM dream_write_statuses
        )
        DELETE FROM dream_write_statuses AS duplicate
        USING ranked
        WHERE duplicate.id = ranked.id
          AND ranked.row_rank > 1
        """
    )
    op.create_unique_constraint(
        "uq_dream_write_statuses_dream_target",
        "dream_write_statuses",
        ["dream_id", "target_doc_id"],
    )
    op.add_column(
        "dream_write_statuses",
        sa.Column("claim_token", sa.UUID(), nullable=True),
    )


def downgrade() -> None:
    op.execute(
        """
        LOCK TABLE dream_entries, dream_notes, dream_write_statuses
        IN SHARE ROW EXCLUSIVE MODE
        """
    )
    # The old schema treated the body hash as global identity.  Once the new
    # ingress/source identities have admitted legitimate repeated text, blindly
    # recreating that constraint would fail halfway through a downgrade with an
    # opaque IntegrityError.  Stop before any columns are removed and require
    # an explicit data export/reconciliation decision.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM dream_write_statuses
                WHERE status = 'pending'
                   OR claim_token IS NOT NULL
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade 022_capture_idempotency while a Google Docs write is pending or claimed';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM dream_entries
                GROUP BY content_hash
                HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade 022_capture_idempotency: repeated dream bodies '
                    'use source_event_key/source_entry_key identity; reconcile them explicitly first';
            END IF;
        END
        $$
        """
    )
    op.drop_column("dream_write_statuses", "claim_token")
    op.drop_constraint(
        "uq_dream_write_statuses_dream_target",
        "dream_write_statuses",
        type_="unique",
    )
    op.drop_constraint(
        "uq_dream_notes_dream_id_content_hash",
        "dream_notes",
        type_="unique",
    )
    op.drop_column("dream_notes", "content_hash")
    op.drop_index("ix_dream_entries_source_entry_key", table_name="dream_entries")
    op.drop_column("dream_entries", "source_entry_key")
    op.drop_index("ix_dream_entries_content_hash", table_name="dream_entries")
    op.create_unique_constraint(
        "uq_dream_entries_content_hash",
        "dream_entries",
        ["content_hash"],
    )
    op.drop_index("ix_dream_entries_source_event_key", table_name="dream_entries")
    op.drop_column("dream_entries", "source_event_key")
