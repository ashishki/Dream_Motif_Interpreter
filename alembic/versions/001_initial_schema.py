"""initial schema

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-04-12 00:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


class Vector1536(sa.types.UserDefinedType):
    def get_col_spec(self, **kw: object) -> str:
        return "vector(1536)"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "dream_entries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source_doc_id", sa.String(length=255), nullable=False),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("segmentation_confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("content_hash", name="uq_dream_entries_content_hash"),
    )

    op.create_table(
        "theme_categories",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN ('suggested', 'active', 'deprecated')",
            name="ck_theme_categories_status",
        ),
        sa.UniqueConstraint("name", name="uq_theme_categories_name"),
    )

    op.create_table(
        "annotation_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("changed_by", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_table(
        "dream_chunks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("dream_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector1536(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["dream_id"], ["dream_entries.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("dream_id", "chunk_index", name="uq_dream_chunks_dream_id_chunk_index"),
    )

    op.create_table(
        "dream_themes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("dream_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("salience", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("match_type", sa.String(length=64), nullable=False),
        sa.Column("fragments", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["category_id"], ["theme_categories.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["dream_id"], ["dream_entries.id"], ondelete="RESTRICT"),
    )

    op.create_index("ix_dream_entries_source_doc_id", "dream_entries", ["source_doc_id"])
    op.create_index("ix_dream_entries_date", "dream_entries", ["date"])
    op.create_index("ix_dream_chunks_dream_id", "dream_chunks", ["dream_id"])
    op.create_index("ix_dream_themes_dream_id", "dream_themes", ["dream_id"])
    op.create_index("ix_dream_themes_category_id", "dream_themes", ["category_id"])
    op.create_index("ix_annotation_versions_entity", "annotation_versions", ["entity_type", "entity_id"])


def downgrade() -> None:
    op.drop_index("ix_annotation_versions_entity", table_name="annotation_versions")
    op.drop_index("ix_dream_themes_category_id", table_name="dream_themes")
    op.drop_index("ix_dream_themes_dream_id", table_name="dream_themes")
    op.drop_index("ix_dream_chunks_dream_id", table_name="dream_chunks")
    op.drop_index("ix_dream_entries_date", table_name="dream_entries")
    op.drop_index("ix_dream_entries_source_doc_id", table_name="dream_entries")
    op.drop_table("dream_themes")
    op.drop_table("dream_chunks")
    op.drop_table("annotation_versions")
    op.drop_table("theme_categories")
    op.drop_table("dream_entries")
