"""fix dream_themes status CHECK constraint to correct domain values

Revision ID: 004_fix_status_ck
Revises: 003_seed_categories
Create Date: 2026-04-12 00:20:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "004_fix_status_ck"
down_revision: Union[str, None] = "003_seed_categories"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # CODE-1 incorrectly constrained dream_themes.status to ('active','deprecated').
    # Per spec §3 and T08-AC3, valid values are: draft, confirmed, rejected.
    op.drop_constraint("ck_dream_themes_status", "dream_themes", type_="check")
    op.create_check_constraint(
        "ck_dream_themes_status",
        "dream_themes",
        "status IN ('draft', 'confirmed', 'rejected')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_dream_themes_status", "dream_themes", type_="check")
    op.create_check_constraint(
        "ck_dream_themes_status",
        "dream_themes",
        "status IN ('active', 'deprecated')",
    )
