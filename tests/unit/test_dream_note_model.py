from __future__ import annotations

from app.models.note import DreamNote


def test_dream_note_tablename() -> None:
    assert DreamNote.__tablename__ == "dream_notes"


def test_dream_note_has_required_columns() -> None:
    columns = DreamNote.__table__.columns.keys()

    assert "id" in columns
    assert "dream_id" in columns
    assert "text" in columns
    assert "source" in columns
    assert "created_at" in columns
