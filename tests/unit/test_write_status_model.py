from __future__ import annotations

from app.models.write_status import DreamWriteStatus


def test_write_status_model_declares_migration_indexes() -> None:
    indexes = {
        index.name: tuple(column.name for column in index.columns)
        for index in DreamWriteStatus.__table__.indexes
    }

    assert indexes["ix_dream_write_statuses_dream_id"] == ("dream_id",)
    assert indexes["ix_dream_write_statuses_status_updated_at"] == (
        "status",
        "updated_at",
    )
