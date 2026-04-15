"""add bot_sessions table for persisted Telegram session state

Revision ID: 007_add_bot_sessions
Revises: 006_add_hnsw_index
Create Date: 2026-04-15 00:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007_add_bot_sessions"
down_revision: Union[str, None] = "006_add_hnsw_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bot_sessions",
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("history_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("chat_id"),
    )


def downgrade() -> None:
    op.drop_table("bot_sessions")
