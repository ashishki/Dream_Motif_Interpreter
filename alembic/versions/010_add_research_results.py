"""add research_results table for Phase 10 research augmentation

Revision ID: 010
Revises: 009
Create Date: 2026-04-17 00:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "010_add_research_results"
down_revision: Union[str, None] = "009_add_motif_inductions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "research_results",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("motif_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dream_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("query_label", sa.Text(), nullable=False),
        sa.Column(
            "parallels",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "sources",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("triggered_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["motif_id"],
            ["motif_inductions.id"],
            ondelete="CASCADE",
            name="fk_research_results_motif_id",
        ),
        sa.ForeignKeyConstraint(
            ["dream_id"],
            ["dream_entries.id"],
            ondelete="CASCADE",
            name="fk_research_results_dream_id",
        ),
    )


def downgrade() -> None:
    op.drop_table("research_results")
