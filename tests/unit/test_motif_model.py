"""Unit tests for the MotifInduction ORM model and the 009 migration file.

These tests verify:
  (a) The ORM model columns match the expected names and types.
  (b) AnnotationVersion can be instantiated with entity_type='motif_induction'.
  (c) The migration file exists and imports cleanly.
  (d) The migration does not modify dream_themes or any existing table.
"""

from __future__ import annotations

import importlib
import uuid
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.models.annotation import AnnotationVersion
from app.models.motif import MotifInduction

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = PROJECT_ROOT / "alembic" / "versions" / "009_add_motif_inductions.py"


# ---------------------------------------------------------------------------
# AC-2: ORM model columns
# ---------------------------------------------------------------------------

def _column_map(model: type) -> dict[str, sa.Column]:
    """Return a name→Column mapping for a mapped ORM class."""
    mapper = sa.inspect(model)
    return {col.key: col for col in mapper.mapper.column_attrs}


def test_motif_induction_has_id_column() -> None:
    cols = _column_map(MotifInduction)
    assert "id" in cols
    col = cols["id"].columns[0]
    assert col.primary_key is True
    assert isinstance(col.type, UUID)


def test_motif_induction_has_dream_id_column() -> None:
    cols = _column_map(MotifInduction)
    assert "dream_id" in cols
    col = cols["dream_id"].columns[0]
    assert isinstance(col.type, UUID)
    assert col.nullable is False
    fks = list(col.foreign_keys)
    assert len(fks) == 1
    fk = next(iter(fks))
    assert fk.column.table.name == "dream_entries"


def test_motif_induction_has_label_column() -> None:
    cols = _column_map(MotifInduction)
    assert "label" in cols
    col = cols["label"].columns[0]
    assert isinstance(col.type, sa.Text)
    assert col.nullable is False


def test_motif_induction_has_rationale_column() -> None:
    cols = _column_map(MotifInduction)
    assert "rationale" in cols
    col = cols["rationale"].columns[0]
    assert isinstance(col.type, sa.Text)
    assert col.nullable is True


def test_motif_induction_has_confidence_column() -> None:
    cols = _column_map(MotifInduction)
    assert "confidence" in cols
    col = cols["confidence"].columns[0]
    assert isinstance(col.type, sa.String)
    assert col.type.length == 16


def test_motif_induction_has_status_column() -> None:
    cols = _column_map(MotifInduction)
    assert "status" in cols
    col = cols["status"].columns[0]
    assert isinstance(col.type, sa.String)
    assert col.type.length == 32
    assert col.nullable is False


def test_motif_induction_has_fragments_column() -> None:
    cols = _column_map(MotifInduction)
    assert "fragments" in cols
    col = cols["fragments"].columns[0]
    assert isinstance(col.type, JSONB)
    assert col.nullable is False


def test_motif_induction_has_model_version_column() -> None:
    cols = _column_map(MotifInduction)
    assert "model_version" in cols
    col = cols["model_version"].columns[0]
    assert isinstance(col.type, sa.String)
    assert col.type.length == 64


def test_motif_induction_has_created_at_column() -> None:
    cols = _column_map(MotifInduction)
    assert "created_at" in cols
    col = cols["created_at"].columns[0]
    assert isinstance(col.type, sa.DateTime)
    assert col.type.timezone is True


# ---------------------------------------------------------------------------
# AC-3: CHECK constraints on status
# ---------------------------------------------------------------------------

def test_motif_induction_status_check_constraint_present() -> None:
    table = MotifInduction.__table__
    constraint_exprs = [
        str(c.sqltext) if hasattr(c, "sqltext") else ""
        for c in table.constraints
        if isinstance(c, sa.CheckConstraint)
    ]
    status_constraints = [e for e in constraint_exprs if "status" in e]
    assert len(status_constraints) >= 1, (
        "Expected at least one CHECK constraint referencing 'status'"
    )
    combined = " ".join(status_constraints)
    for value in ("draft", "confirmed", "rejected"):
        assert value in combined, f"Expected '{value}' in status CHECK constraint"


# ---------------------------------------------------------------------------
# AC-3: CHECK constraint on confidence
# ---------------------------------------------------------------------------

def test_motif_induction_confidence_check_constraint_present() -> None:
    table = MotifInduction.__table__
    constraint_exprs = [
        str(c.sqltext) if hasattr(c, "sqltext") else ""
        for c in table.constraints
        if isinstance(c, sa.CheckConstraint)
    ]
    confidence_constraints = [e for e in constraint_exprs if "confidence" in e]
    assert len(confidence_constraints) >= 1, (
        "Expected at least one CHECK constraint referencing 'confidence'"
    )
    combined = " ".join(confidence_constraints)
    for value in ("high", "moderate", "low"):
        assert value in combined, f"Expected '{value}' in confidence CHECK constraint"


# ---------------------------------------------------------------------------
# AC-4: AnnotationVersion can be instantiated with entity_type='motif_induction'
# ---------------------------------------------------------------------------

def test_annotation_version_supports_motif_induction_entity_type() -> None:
    entity_id = uuid.uuid4()
    av = AnnotationVersion(
        entity_type="motif_induction",
        entity_id=entity_id,
        snapshot={
            "entity_type": "motif_induction",
            "entity_id": str(entity_id),
            "status_before": "draft",
            "status_after": "confirmed",
            "changed_by": "test-user",
        },
        changed_by="test-user",
    )
    assert av.entity_type == "motif_induction"
    assert av.entity_id == entity_id
    assert av.snapshot["status_after"] == "confirmed"


# ---------------------------------------------------------------------------
# AC-1 / AC-5: Migration file exists, imports cleanly, and only touches
#               motif_inductions (not existing tables)
# ---------------------------------------------------------------------------

def test_migration_file_exists() -> None:
    assert MIGRATION_PATH.exists(), (
        f"Migration file not found at {MIGRATION_PATH}"
    )


def test_migration_file_imports_cleanly() -> None:
    spec = importlib.util.spec_from_file_location(
        "migration_009", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[arg-type]
    assert hasattr(module, "upgrade")
    assert hasattr(module, "downgrade")
    assert module.revision == "009_add_motif_inductions"
    assert module.down_revision == "008_add_voice_media_events"


def test_migration_does_not_alter_existing_tables() -> None:
    """AC-5: the migration must not ALTER or DROP existing tables.

    The migration may reference dream_entries via an FK constraint (expected),
    but it must not issue alter_table / drop_table for any existing table.
    """
    content = MIGRATION_PATH.read_text(encoding="utf-8")
    existing_tables = [
        "dream_themes",
        "theme_categories",
        "dream_chunks",
        "annotation_versions",
        "bot_sessions",
        "voice_media_events",
    ]
    for table_name in existing_tables:
        alter_call = f'op.alter_table("{table_name}"'
        drop_call = f'op.drop_table("{table_name}"'
        add_col_call = f'op.add_column("{table_name}"'
        drop_col_call = f'op.drop_column("{table_name}"'
        for forbidden in (alter_call, drop_call, add_col_call, drop_col_call):
            assert forbidden not in content, (
                f"Migration 009 must not modify existing table '{table_name}': "
                f"found '{forbidden}'"
            )
    assert "dream_themes" not in content, (
        "Migration 009 must not reference dream_themes at all"
    )


# ---------------------------------------------------------------------------
# Separation: motif_inductions table name must not appear in dream model
# ---------------------------------------------------------------------------

def test_motif_inductions_table_not_referenced_in_dream_themes_model() -> None:
    from app.models.theme import DreamTheme
    table = DreamTheme.__table__
    fk_targets = {
        fk.column.table.name
        for col in table.columns
        for fk in col.foreign_keys
    }
    assert "motif_inductions" not in fk_targets
