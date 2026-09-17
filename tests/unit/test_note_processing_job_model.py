from __future__ import annotations

from app.models.processing import NoteProcessingJob


def test_note_processing_job_model_contract() -> None:
    columns = set(NoteProcessingJob.__table__.columns.keys())
    indexes = {index.name for index in NoteProcessingJob.__table__.indexes}
    constraints = {constraint.name for constraint in NoteProcessingJob.__table__.constraints}

    assert columns == {
        "id",
        "note_id",
        "stage",
        "status",
        "attempt_count",
        "last_error",
        "available_at",
        "locked_at",
        "lock_token",
        "target_doc_id",
        "created_at",
        "updated_at",
    }
    assert "ix_note_processing_jobs_note_id" in indexes
    assert "ix_note_processing_jobs_claim" in indexes
    assert "uq_note_processing_jobs_note_stage" in constraints
    assert "ck_note_processing_jobs_stage" in constraints
    assert "ck_note_processing_jobs_status" in constraints
    assert "ck_note_processing_jobs_target" in constraints
