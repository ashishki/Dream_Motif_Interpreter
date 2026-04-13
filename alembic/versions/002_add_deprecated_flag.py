"""add deprecated flag to dream themes

Revision ID: 002_add_deprecated_flag
Revises: 001_initial_schema
Create Date: 2026-04-12 00:05:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002_add_deprecated_flag"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dream_themes",
        sa.Column(
            "deprecated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("dream_themes", "deprecated")
