"""add motif_inductions table for Phase 9 motif abstraction

Revision ID: 009_add_motif_inductions
Revises: 008_add_voice_media_events
Create Date: 2026-04-16 00:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "009_add_motif_inductions"
down_revision: Union[str, None] = "008_add_voice_media_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "motif_inductions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("dream_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(length=16), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "fragments",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("model_version", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "confidence IN ('high', 'moderate', 'low')",
            name="ck_motif_inductions_confidence",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'confirmed', 'rejected')",
            name="ck_motif_inductions_status",
        ),
        sa.ForeignKeyConstraint(
            ["dream_id"],
            ["dream_entries.id"],
            ondelete="RESTRICT",
            name="fk_motif_inductions_dream_id",
        ),
    )
    op.create_index("ix_motif_inductions_dream_id", "motif_inductions", ["dream_id"])


def downgrade() -> None:
    op.drop_index("ix_motif_inductions_dream_id", table_name="motif_inductions")
    op.drop_table("motif_inductions")
