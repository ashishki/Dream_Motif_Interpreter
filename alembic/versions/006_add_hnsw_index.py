"""add hnsw index for dream chunk embeddings

Revision ID: 006_add_hnsw_index
Revises: 005_add_fragments_default
Create Date: 2026-04-13 10:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "006_add_hnsw_index"
down_revision: Union[str, None] = "005_add_fragments_default"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "ix_dream_chunks_embedding_hnsw"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY {INDEX_NAME}
            ON dream_chunks USING hnsw (embedding vector_cosine_ops)
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}")
