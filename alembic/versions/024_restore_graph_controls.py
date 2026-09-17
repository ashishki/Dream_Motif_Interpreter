"""allow append-only restore graph privacy controls

Revision ID: 024_restore_graph_controls
Revises: 023_dream_processing_jobs
Create Date: 2026-08-30 00:00:03
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "024_restore_graph_controls"
down_revision: Union[str, None] = "023_dream_processing_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Keep the constraint replacement atomic with append-only receipt writers.
    op.execute("LOCK TABLE dream_graph_privacy_controls IN SHARE ROW EXCLUSIVE MODE")
    op.drop_constraint(
        "ck_dream_graph_privacy_controls_action",
        "dream_graph_privacy_controls",
        type_="check",
    )
    op.create_check_constraint(
        "ck_dream_graph_privacy_controls_action",
        "dream_graph_privacy_controls",
        "action IN ('delete', 'hide', 'restore', 'reject')",
    )


def downgrade() -> None:
    # Close the preflight/constraint-replacement race.  Otherwise a restore
    # receipt could commit after the check and before the legacy constraint is
    # reinstated, producing an opaque DDL failure instead of the guard below.
    op.execute("LOCK TABLE dream_graph_privacy_controls IN SHARE ROW EXCLUSIVE MODE")
    has_restore_rows = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS ("
                "SELECT 1 FROM dream_graph_privacy_controls WHERE action = 'restore'"
                ")"
            )
        )
        .scalar_one()
    )
    if has_restore_rows:
        raise RuntimeError(
            "Cannot downgrade restore graph controls while append-only restore receipts exist"
        )
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
