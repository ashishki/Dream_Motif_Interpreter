"""add server default for dream_themes.fragments

Revision ID: 005_add_fragments_default
Revises: 004_fix_status_ck
Create Date: 2026-04-12 18:30:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "005_add_fragments_default"
down_revision: Union[str, None] = "004_fix_status_ck"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE dream_themes ALTER COLUMN fragments SET DEFAULT '[]'::jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE dream_themes ALTER COLUMN fragments DROP DEFAULT")
