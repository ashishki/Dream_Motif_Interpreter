"""add note chunk metadata

Revision ID: 017_add_note_chunks
Revises: 016_add_voice_transcript_text
Create Date: 2026-05-06 00:00:01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "017_add_note_chunks"
down_revision: Union[str, None] = "016_add_voice_transcript_text"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dream_chunks",
        sa.Column(
            "source_kind",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'dream_text'"),
        ),
    )
    op.add_column(
        "dream_chunks",
        sa.Column("note_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_dream_chunks_note_id_dream_notes",
        "dream_chunks",
        "dream_notes",
        ["note_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_dream_chunks_note_id",
        "dream_chunks",
        ["note_id"],
    )
    op.create_check_constraint(
        "ck_dream_chunks_source_kind",
        "dream_chunks",
        "source_kind IN ('dream_text', 'note')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_dream_chunks_source_kind", "dream_chunks", type_="check")
    op.drop_constraint("uq_dream_chunks_note_id", "dream_chunks", type_="unique")
    op.drop_constraint(
        "fk_dream_chunks_note_id_dream_notes",
        "dream_chunks",
        type_="foreignkey",
    )
    op.drop_column("dream_chunks", "note_id")
    op.drop_column("dream_chunks", "source_kind")
