"""add durable manual sync jobs

Revision ID: 026_manual_sync_jobs
Revises: 025_note_processing_jobs
Create Date: 2026-08-31 00:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "026_manual_sync_jobs"
down_revision: Union[str, None] = "025_note_processing_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "manual_sync_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("doc_id", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("new_entries", sa.Integer(), nullable=True),
        sa.Column("notify_chat_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lock_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
            name="ck_manual_sync_jobs_status",
        ),
        sa.CheckConstraint(
            "new_entries IS NULL OR new_entries >= 0",
            name="ck_manual_sync_jobs_new_entries",
        ),
    )
    op.create_index(
        "ix_manual_sync_jobs_claim",
        "manual_sync_jobs",
        ["status", "available_at", "locked_at"],
        unique=False,
    )
    op.create_index(
        "ix_manual_sync_jobs_doc_created",
        "manual_sync_jobs",
        ["doc_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM manual_sync_jobs
                WHERE status IN ('pending', 'running', 'retryable')
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade 026_manual_sync_jobs while durable manual sync work is unfinished';
            END IF;
        END
        $$
        """
    )
    op.drop_index("ix_manual_sync_jobs_doc_created", table_name="manual_sync_jobs")
    op.drop_index("ix_manual_sync_jobs_claim", table_name="manual_sync_jobs")
    op.drop_table("manual_sync_jobs")