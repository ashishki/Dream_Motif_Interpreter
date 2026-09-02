from __future__ import annotations

import uuid

import pytest

from app.workers.ingest import (
    SourceDreamConflictError,
    _build_source_entry_key,
    _ensure_imported_note_index_job,
    _load_adoptable_telegram_dream,
    _load_dream_by_source_entry_key,
    _mark_google_doc_presence,
)


class _ScalarRows:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> "_ScalarRows":
        return self

    def all(self) -> list[object]:
        return self._rows

    def scalar_one_or_none(self) -> object | None:
        return self._rows[0] if self._rows else None


class _Session:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows
        self.statements: list[object] = []

    async def execute(self, statement: object) -> _ScalarRows:
        self.statements.append(statement)
        return _ScalarRows(self._rows)

    async def scalar(self, statement: object) -> object | None:
        self.statements.append(statement)
        return self._rows[0] if self._rows else None


def test_source_key_does_not_depend_on_global_document_position() -> None:
    assert _build_source_entry_key("doc", "2026-05-01:bridge", 0) == (
        _build_source_entry_key("doc", "2026-05-01:bridge", 0)
    )
    assert _build_source_entry_key("doc", "2026-05-01:bridge", 0) != (
        _build_source_entry_key("doc", "2026-05-01:bridge", 1)
    )


@pytest.mark.asyncio
async def test_single_unclaimed_telegram_hash_candidate_can_be_adopted() -> None:
    candidate = object()
    session = _Session([candidate])

    adopted = await _load_adoptable_telegram_dream(
        session=session,  # type: ignore[arg-type]
        content_hash="same-body",
    )

    assert adopted is candidate
    assert "FOR UPDATE" in str(session.statements[0])


@pytest.mark.asyncio
async def test_ambiguous_telegram_hash_candidates_are_not_adopted() -> None:
    adopted = await _load_adoptable_telegram_dream(
        session=_Session([object(), object()]),  # type: ignore[arg-type]
        content_hash="same-body",
    )

    assert adopted is None


@pytest.mark.asyncio
async def test_source_slot_lookup_locks_identity_row() -> None:
    candidate = object()
    session = _Session([candidate])

    loaded = await _load_dream_by_source_entry_key(
        session=session,  # type: ignore[arg-type]
        source_entry_key="stable-key",
    )

    assert loaded is candidate
    assert "FOR UPDATE" in str(session.statements[0])


@pytest.mark.asyncio
async def test_google_presence_does_not_steal_fresh_delivery_claim() -> None:
    with pytest.raises(SourceDreamConflictError, match="already in progress"):
        await _mark_google_doc_presence(
            session=_Session([]),  # type: ignore[arg-type]
            dream_id=uuid.uuid4(),
            target_doc_id="doc",
        )


@pytest.mark.asyncio
async def test_google_note_enqueues_only_safe_index_stage() -> None:
    session = _Session([])

    await _ensure_imported_note_index_job(
        session=session,  # type: ignore[arg-type]
        note_id=uuid.uuid4(),
        repair_succeeded=False,
    )

    assert len(session.statements) == 1
    params = session.statements[0].compile().params
    assert params["stage"] == "index"
    assert params["status"] == "pending"
    assert params["target_doc_id"] is None
    assert "gdocs" not in params.values()


@pytest.mark.asyncio
async def test_null_embedding_repair_rearms_only_succeeded_index_job() -> None:
    session = _Session([])

    await _ensure_imported_note_index_job(
        session=session,  # type: ignore[arg-type]
        note_id=uuid.uuid4(),
        repair_succeeded=True,
    )

    assert len(session.statements) == 2
    update_statement = session.statements[1]
    params = update_statement.compile().params
    assert "succeeded" in params.values()
    assert "retryable" in params.values()
    assert "failed" not in params.values()
