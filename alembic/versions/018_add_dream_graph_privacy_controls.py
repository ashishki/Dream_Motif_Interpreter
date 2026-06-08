"""add dream graph privacy controls

Revision ID: 018_add_dream_graph_privacy_controls
Revises: 017_add_note_chunks
Create Date: 2026-05-31 00:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "018_add_dream_graph_privacy_controls"
down_revision: Union[str, None] = "017_add_note_chunks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=32),
        type_=sa.String(length=128),
        existing_nullable=False,
    )
    op.create_table(
        "dream_graph_privacy_controls",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column(
            "control_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "receipt_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("changed_by", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "subject_type IN ('dream', 'graph_node', 'graph_edge')",
            name="ck_dream_graph_privacy_controls_subject_type",
        ),
        sa.CheckConstraint(
            "action IN ('delete')",
            name="ck_dream_graph_privacy_controls_action",
        ),
    )
    op.create_index(
        "ix_dream_graph_privacy_controls_subject_type",
        "dream_graph_privacy_controls",
        ["subject_type"],
    )
    op.create_index(
        "ix_dream_graph_privacy_controls_subject_id",
        "dream_graph_privacy_controls",
        ["subject_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_dream_graph_privacy_controls_subject_id",
        table_name="dream_graph_privacy_controls",
    )
    op.drop_index(
        "ix_dream_graph_privacy_controls_subject_type",
        table_name="dream_graph_privacy_controls",
    )
    op.drop_table("dream_graph_privacy_controls")
