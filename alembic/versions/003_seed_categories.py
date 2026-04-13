"""seed starter theme categories

Revision ID: 003_seed_categories
Revises: 002_add_deprecated_flag
Create Date: 2026-04-12 00:10:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import bindparam

revision: str = "003_seed_categories"
down_revision: Union[str, None] = "002_add_deprecated_flag"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STARTER_CATEGORIES = (
    ("separation", "Dreams involving rupture, distance, or emotional separation."),
    ("mother_figure", "Images of mothers, caregivers, or maternal authority."),
    ("shadow", "Dark doubles, feared traits, or rejected parts of the self."),
    ("inner_child", "Childhood self-states, tenderness, vulnerability, or play."),
    ("transformation", "Metamorphosis, initiation, or major inner change."),
    ("water", "Oceans, rain, flooding, immersion, or emotional depth."),
    ("flying", "Flight, levitation, release, or altered perspective."),
    ("pursuit", "Chasing, being chased, escape, or relentless pressure."),
    ("house_rooms", "Homes, rooms, basements, attics, and interior architecture."),
    ("death_rebirth", "Endings, funerals, resurrection, and symbolic renewal."),
)


def upgrade() -> None:
    theme_categories = sa.table(
        "theme_categories",
        sa.column("name", sa.String(length=255)),
        sa.column("description", sa.Text()),
        sa.column("status", sa.String(length=32)),
    )

    op.bulk_insert(
        theme_categories,
        [
            {"name": name, "description": description, "status": "active"}
            for name, description in _STARTER_CATEGORIES
        ],
    )

    # Write AnnotationVersion records for each seed category per contract:
    # "Every mutation to a ThemeCategory record must write an AnnotationVersion snapshot."
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, name FROM theme_categories WHERE name IN :names").bindparams(
            sa.bindparam("names", [name for name, _ in _STARTER_CATEGORIES], expanding=True)
        )
    ).fetchall()

    import json as _json

    for row in rows:
        conn.execute(
            sa.text(
                "INSERT INTO annotation_versions (entity_type, entity_id, snapshot, changed_by)"
                " VALUES (:entity_type, :entity_id, cast(:snapshot as jsonb), :changed_by)"
            ),
            {
                "entity_type": "theme_category",
                "entity_id": row[0],  # already a UUID from the DB
                "snapshot": _json.dumps(
                    {
                        "status_before": None,
                        "status_after": "active",
                        "changed_by": "seed",
                        "name": row[1],
                    }
                ),
                "changed_by": "seed",
            },
        )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM theme_categories WHERE name IN :names").bindparams(
            bindparam("names", [name for name, _ in _STARTER_CATEGORIES], expanding=True)
        )
    )
