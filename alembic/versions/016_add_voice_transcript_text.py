"""add transcript_text to voice_media_events

Revision ID: 016_add_voice_transcript_text
Revises: 015_add_dream_write_statuses
Create Date: 2026-05-01 00:00:02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "016_add_voice_transcript_text"
down_revision: Union[str, None] = "015_add_dream_write_statuses"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("voice_media_events", sa.Column("transcript_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("voice_media_events", "transcript_text")
