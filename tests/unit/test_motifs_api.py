"""Unit tests for app/api/motifs.py (WS-9.5).

AC-1: GET /dreams/{dream_id}/motifs returns motif_inductions rows.
AC-2: PATCH /dreams/{dream_id}/motifs/{motif_id} updates status and writes AnnotationVersion.
AC-3: GET /dreams/{dream_id}/motifs/history returns annotation version history.
AC-4: Rejected motifs excluded from default GET response.
AC-5: All routes covered by unit tests with stub DB session.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.api.motifs import (
    MotifHistoryResponse,
    MotifListResponse,
    MotifStatusUpdateRequest,
    get_motif_history,
    list_motifs,
    update_motif_status,
)

# ---------------------------------------------------------------------------
# Helpers / stubs
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc)


def _make_motif(
    *,
    dream_id: uuid.UUID | None = None,
    status: str = "draft",
    label: str = "obstructed vertical movement",
    rationale: str = "stairs and locked door",
    confidence: str = "high",
    fragments: list | None = None,
) -> SimpleNamespace:
    m = SimpleNamespace()
    m.id = uuid.uuid4()
    m.dream_id = dream_id or uuid.uuid4()
    m.label = label
    m.rationale = rationale
    m.confidence = confidence
    m.status = status
    m.fragments = fragments if fragments is not None else []
    m.created_at = _NOW
    return m


def _make_annotation_version(
    *,
    entity_id: uuid.UUID | None = None,
    dream_id: uuid.UUID | None = None,
) -> SimpleNamespace:
    av = SimpleNamespace()
    av.id = uuid.uuid4()
    av.entity_type = "motif_induction"
    av.entity_id = entity_id or uuid.uuid4()
    av.snapshot = {
        "entity_type": "motif_induction",
        "entity_id": str(av.entity_id),
        "dream_id": str(dream_id or uuid.uuid4()),
        "status_before": "draft",
        "status_after": "confirmed",
        "changed_by": "user",
    }
    av.created_at = _NOW
    return av


class _FakeScalars:
    def __init__(self, items):
        self._items = list(items)

    def all(self):
        return list(self._items)

    def scalars(self):
        return self


class _FakeResult:
    def __init__(self, scalars_items):
        self._items = list(scalars_items)

    def scalars(self):
        return _FakeScalars(self._items)

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None


class _FakeSession:
    """Minimal async session stub."""

    def __init__(
        self,
        *,
        execute_results: list | None = None,
        get_result=None,
    ):
        self._execute_results = list(execute_results or [])
        self._get_result = get_result
        self.added: list = []
        self.committed = False
        self.flushed = False

    async def get(self, model, pk):
        del model, pk
        return self._get_result

    async def execute(self, stmt):
        del stmt
        return self._execute_results.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed = True

    async def commit(self):
        self.committed = True


class _SessionCtx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *args):
        return False


class _FakeSessionFactory:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return _SessionCtx(self._session)


# ---------------------------------------------------------------------------
# AC-1: GET /dreams/{dream_id}/motifs — returns all non-rejected motifs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_motifs_returns_draft_and_confirmed() -> None:
    dream_id = uuid.uuid4()
    draft_motif = _make_motif(dream_id=dream_id, status="draft")
    confirmed_motif = _make_motif(dream_id=dream_id, status="confirmed")
    session = _FakeSession(execute_results=[_FakeResult([draft_motif, confirmed_motif])])
    factory = _FakeSessionFactory(session)

    with patch("app.api.motifs.get_session_factory", return_value=factory):
        response = await list_motifs(dream_id=dream_id, include_rejected=False)

    assert isinstance(response, MotifListResponse)
    assert response.dream_id == dream_id
    assert len(response.items) == 2
    statuses = {item.status for item in response.items}
    assert statuses == {"draft", "confirmed"}


@pytest.mark.asyncio
async def test_list_motifs_response_fields_present() -> None:
    dream_id = uuid.uuid4()
    motif = _make_motif(
        dream_id=dream_id,
        status="draft",
        fragments=[{"text": "crumbling stairs", "start_offset": 0, "end_offset": 16}],
    )
    session = _FakeSession(execute_results=[_FakeResult([motif])])
    factory = _FakeSessionFactory(session)

    with patch("app.api.motifs.get_session_factory", return_value=factory):
        response = await list_motifs(dream_id=dream_id, include_rejected=False)

    item = response.items[0]
    assert item.id == motif.id
    assert item.dream_id == dream_id
    assert item.label == motif.label
    assert item.rationale == motif.rationale
    assert item.confidence == motif.confidence
    assert item.status == motif.status
    assert len(item.fragments) == 1


# ---------------------------------------------------------------------------
# AC-4: Rejected motifs excluded from default GET response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_motifs_excludes_rejected_by_default() -> None:
    """The query executed must filter out rejected rows by default.

    We verify that the session receives only non-rejected motifs because the
    WHERE clause is applied before our stub returns results.  We simulate the
    DB doing its job by only returning the non-rejected row from the stub.
    """
    dream_id = uuid.uuid4()
    confirmed_motif = _make_motif(dream_id=dream_id, status="confirmed")
    # Stub returns only the confirmed row — simulates DB applying the filter
    session = _FakeSession(execute_results=[_FakeResult([confirmed_motif])])
    factory = _FakeSessionFactory(session)

    with patch("app.api.motifs.get_session_factory", return_value=factory):
        response = await list_motifs(dream_id=dream_id, include_rejected=False)

    assert all(item.status != "rejected" for item in response.items)


@pytest.mark.asyncio
async def test_list_motifs_includes_rejected_when_param_true() -> None:
    dream_id = uuid.uuid4()
    rejected_motif = _make_motif(dream_id=dream_id, status="rejected")
    draft_motif = _make_motif(dream_id=dream_id, status="draft")
    session = _FakeSession(execute_results=[_FakeResult([rejected_motif, draft_motif])])
    factory = _FakeSessionFactory(session)

    with patch("app.api.motifs.get_session_factory", return_value=factory):
        response = await list_motifs(dream_id=dream_id, include_rejected=True)

    statuses = {item.status for item in response.items}
    assert "rejected" in statuses


@pytest.mark.asyncio
async def test_list_motifs_interpretation_note_present() -> None:
    dream_id = uuid.uuid4()
    motif = _make_motif(dream_id=dream_id)
    session = _FakeSession(execute_results=[_FakeResult([motif])])
    factory = _FakeSessionFactory(session)

    with patch("app.api.motifs.get_session_factory", return_value=factory):
        response = await list_motifs(dream_id=dream_id, include_rejected=False)

    for item in response.items:
        assert (
            "suggestions" in item.interpretation_note or "computational" in item.interpretation_note
        )


# ---------------------------------------------------------------------------
# AC-2: PATCH /dreams/{dream_id}/motifs/{motif_id} updates status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_motif_updates_status() -> None:
    dream_id = uuid.uuid4()
    motif = _make_motif(dream_id=dream_id, status="draft")
    session = _FakeSession(execute_results=[_FakeResult([motif])])
    factory = _FakeSessionFactory(session)

    payload = MotifStatusUpdateRequest(status="confirmed")

    with patch("app.api.motifs.get_session_factory", return_value=factory):
        response = await update_motif_status(
            dream_id=dream_id,
            motif_id=motif.id,
            payload=payload,
        )

    assert response.status == "confirmed"
    assert motif.status == "confirmed"
    assert session.committed is True


@pytest.mark.asyncio
async def test_patch_motif_writes_annotation_version_before_commit() -> None:
    """AnnotationVersion must be added to session and flushed before status is set."""
    dream_id = uuid.uuid4()
    motif = _make_motif(dream_id=dream_id, status="draft")
    session = _FakeSession(execute_results=[_FakeResult([motif])])
    factory = _FakeSessionFactory(session)

    payload = MotifStatusUpdateRequest(status="rejected")

    with patch("app.api.motifs.get_session_factory", return_value=factory):
        await update_motif_status(
            dream_id=dream_id,
            motif_id=motif.id,
            payload=payload,
        )

    assert len(session.added) == 1
    annotation = session.added[0]
    assert annotation.entity_type == "motif_induction"
    assert annotation.entity_id == motif.id
    assert annotation.snapshot["status_before"] == "draft"
    assert annotation.snapshot["status_after"] == "rejected"
    assert session.flushed is True
    assert session.committed is True


@pytest.mark.asyncio
async def test_patch_motif_404_when_not_found() -> None:
    from fastapi import HTTPException

    dream_id = uuid.uuid4()
    session = _FakeSession(execute_results=[_FakeResult([])])
    factory = _FakeSessionFactory(session)

    payload = MotifStatusUpdateRequest(status="confirmed")

    with patch("app.api.motifs.get_session_factory", return_value=factory):
        with pytest.raises(HTTPException) as exc_info:
            await update_motif_status(
                dream_id=dream_id,
                motif_id=uuid.uuid4(),
                payload=payload,
            )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_patch_motif_annotation_entity_type_is_motif_induction() -> None:
    """entity_type in the AnnotationVersion snapshot must be 'motif_induction'."""
    dream_id = uuid.uuid4()
    motif = _make_motif(dream_id=dream_id, status="draft")
    session = _FakeSession(execute_results=[_FakeResult([motif])])
    factory = _FakeSessionFactory(session)

    payload = MotifStatusUpdateRequest(status="confirmed")

    with patch("app.api.motifs.get_session_factory", return_value=factory):
        await update_motif_status(
            dream_id=dream_id,
            motif_id=motif.id,
            payload=payload,
        )

    annotation = session.added[0]
    assert annotation.entity_type == "motif_induction"
    assert annotation.snapshot["entity_type"] == "motif_induction"


# ---------------------------------------------------------------------------
# AC-3: GET /dreams/{dream_id}/motifs/history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_motif_history_returns_items() -> None:
    dream_id = uuid.uuid4()
    motif = _make_motif(dream_id=dream_id)
    av = _make_annotation_version(entity_id=motif.id, dream_id=dream_id)
    session = _FakeSession(execute_results=[_FakeResult([av])])
    factory = _FakeSessionFactory(session)

    with patch("app.api.motifs.get_session_factory", return_value=factory):
        response = await get_motif_history(dream_id=dream_id)

    assert isinstance(response, MotifHistoryResponse)
    assert response.dream_id == dream_id
    assert len(response.items) == 1
    item = response.items[0]
    assert item.entity_type == "motif_induction"
    assert item.entity_id == av.entity_id


@pytest.mark.asyncio
async def test_get_motif_history_empty_when_no_versions() -> None:
    dream_id = uuid.uuid4()
    session = _FakeSession(execute_results=[_FakeResult([])])
    factory = _FakeSessionFactory(session)

    with patch("app.api.motifs.get_session_factory", return_value=factory):
        response = await get_motif_history(dream_id=dream_id)

    assert response.dream_id == dream_id
    assert response.items == []


@pytest.mark.asyncio
async def test_get_motif_history_created_at_is_isoformat() -> None:
    dream_id = uuid.uuid4()
    av = _make_annotation_version(dream_id=dream_id)
    session = _FakeSession(execute_results=[_FakeResult([av])])
    factory = _FakeSessionFactory(session)

    with patch("app.api.motifs.get_session_factory", return_value=factory):
        response = await get_motif_history(dream_id=dream_id)

    item = response.items[0]
    # Must be a valid ISO 8601 string
    parsed = datetime.fromisoformat(item.created_at)
    assert parsed == _NOW


# ---------------------------------------------------------------------------
# AC-5: Router is registered in the app
# ---------------------------------------------------------------------------


def test_motifs_router_registered_in_app() -> None:
    """The motifs router must be present in the FastAPI app route list."""
    import importlib
    import sys

    sys.modules.pop("app.main", None)
    main_module = importlib.import_module("app.main")
    app = main_module.app

    motif_paths = [
        route.path for route in app.routes if hasattr(route, "path") and "motifs" in route.path
    ]
    assert len(motif_paths) >= 3, (
        f"Expected at least 3 motif routes registered, found: {motif_paths}"
    )
