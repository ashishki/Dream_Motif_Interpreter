"""allow reject graph privacy controls

Revision ID: 020_allow_reject_graph_privacy_controls
Revises: 019_allow_hide_graph_privacy_controls
Create Date: 2026-05-31 00:00:02
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "020_allow_reject_graph_privacy_controls"
down_revision: Union[str, None] = "019_allow_hide_graph_privacy_controls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_dream_graph_privacy_controls_action",
        "dream_graph_privacy_controls",
        type_="check",
    )
    op.create_check_constraint(
        "ck_dream_graph_privacy_controls_action",
        "dream_graph_privacy_controls",
        "action IN ('delete', 'hide', 'reject')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_dream_graph_privacy_controls_action",
        "dream_graph_privacy_controls",
        type_="check",
    )
    op.create_check_constraint(
        "ck_dream_graph_privacy_controls_action",
        "dream_graph_privacy_controls",
        "action IN ('delete', 'hide')",
    )
