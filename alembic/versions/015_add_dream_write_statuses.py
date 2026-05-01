"""add dream_write_statuses table

Revision ID: 015_add_dream_write_statuses
Revises: 014_add_dream_notes
Create Date: 2026-05-01 00:00:01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "015_add_dream_write_statuses"
down_revision: Union[str, None] = "014_add_dream_notes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dream_write_statuses",
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
        sa.Column("target_doc_id", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text(), nullable=True),
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
            "status IN ('pending', 'succeeded', 'failed')",
            name="ck_dream_write_statuses_status",
        ),
    )
    op.create_index(
        op.f("ix_dream_write_statuses_dream_id"),
        "dream_write_statuses",
        ["dream_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dream_write_statuses_status_updated_at"),
        "dream_write_statuses",
        ["status", "updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_dream_write_statuses_status_updated_at"), table_name="dream_write_statuses"
    )
    op.drop_index(op.f("ix_dream_write_statuses_dream_id"), table_name="dream_write_statuses")
    op.drop_table("dream_write_statuses")
