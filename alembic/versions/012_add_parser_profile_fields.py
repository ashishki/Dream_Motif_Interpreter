"""add parser profile fields to dream entries

Revision ID: 012_add_parser_profile_fields
Revises: 011_add_feedback
Create Date: 2026-04-21 00:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "012_add_parser_profile_fields"
down_revision: Union[str, None] = "011_add_feedback"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dream_entries",
        sa.Column(
            "parser_profile",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'default'"),
        ),
    )
    op.add_column(
        "dream_entries",
        sa.Column(
            "parse_warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("dream_entries", "parse_warnings")
    op.drop_column("dream_entries", "parser_profile")
