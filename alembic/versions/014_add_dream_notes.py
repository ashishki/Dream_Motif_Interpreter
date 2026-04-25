"""add dream_notes table

Revision ID: 014_add_dream_notes
Revises: 013_add_message_reactions
Create Date: 2026-04-25 00:00:01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "014_add_dream_notes"
down_revision: Union[str, None] = "013_add_message_reactions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dream_notes",
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
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "source",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'telegram'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(op.f("ix_dream_notes_dream_id"), "dream_notes", ["dream_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_dream_notes_dream_id"), table_name="dream_notes")
    op.drop_table("dream_notes")
