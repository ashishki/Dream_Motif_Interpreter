from __future__ import annotations

import importlib
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from app.models.dream_graph_control import DreamGraphPrivacyControl

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = PROJECT_ROOT / "alembic" / "versions" / "018_add_dream_graph_privacy_controls.py"
ALLOW_HIDE_MIGRATION_PATH = (
    PROJECT_ROOT / "alembic" / "versions" / "019_allow_hide_graph_privacy_controls.py"
)


def _column_map(model: type) -> dict[str, sa.Column]:
    mapper = sa.inspect(model)
    return {col.key: col for col in mapper.mapper.column_attrs}


def test_privacy_control_model_defines_required_columns() -> None:
    cols = _column_map(DreamGraphPrivacyControl)

    assert {
        "id",
        "subject_type",
        "subject_id",
        "action",
        "control_payload",
        "receipt_payload",
        "changed_by",
        "created_at",
    }.issubset(cols)
    assert isinstance(cols["subject_type"].columns[0].type, sa.String)
    assert cols["subject_type"].columns[0].type.length == 32
    assert isinstance(cols["subject_id"].columns[0].type, sa.Text)
    assert isinstance(cols["action"].columns[0].type, sa.String)
    assert isinstance(cols["control_payload"].columns[0].type, JSONB)
    assert isinstance(cols["receipt_payload"].columns[0].type, JSONB)


def test_privacy_control_model_limits_subject_types_and_actions() -> None:
    constraints = [
        str(constraint.sqltext)
        for constraint in DreamGraphPrivacyControl.__table__.constraints
        if isinstance(constraint, sa.CheckConstraint)
    ]
    combined = " ".join(constraints)

    for value in ("dream", "graph_node", "graph_edge"):
        assert value in combined
    assert "delete" in combined
    assert "hide" in combined


def test_privacy_control_migration_exists_and_imports_cleanly() -> None:
    assert MIGRATION_PATH.exists()

    spec = importlib.util.spec_from_file_location("migration_018", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[arg-type]

    assert module.revision == "018_add_dream_graph_privacy_controls"
    assert module.down_revision == "017_add_note_chunks"
    assert hasattr(module, "upgrade")
    assert hasattr(module, "downgrade")


def test_privacy_control_migration_only_creates_privacy_control_table() -> None:
    content = MIGRATION_PATH.read_text(encoding="utf-8")

    assert '"dream_graph_privacy_controls"' in content
    assert "op.create_table" in content
    assert "op.alter_table" not in content
    assert 'op.drop_table("dream_entries"' not in content
    assert 'op.drop_table("motif_inductions"' not in content


def test_allow_hide_migration_updates_action_constraint() -> None:
    assert ALLOW_HIDE_MIGRATION_PATH.exists()

    spec = importlib.util.spec_from_file_location("migration_019", ALLOW_HIDE_MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[arg-type]

    assert module.revision == "019_allow_hide_graph_privacy_controls"
    assert module.down_revision == "018_add_dream_graph_privacy_controls"
    content = ALLOW_HIDE_MIGRATION_PATH.read_text(encoding="utf-8")
    assert "action IN ('delete', 'hide')" in content
    assert "ck_dream_graph_privacy_controls_action" in content
