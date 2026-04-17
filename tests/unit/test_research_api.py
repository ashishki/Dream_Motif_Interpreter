from __future__ import annotations

import importlib
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.api.research import INTERPRETATION_NOTE


def _make_research_result(
    *,
    motif_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> SimpleNamespace:
    created_at = created_at or datetime(2026, 4, 17, 10, 0, 0, tzinfo=timezone.utc)
    return SimpleNamespace(
        id=uuid.uuid4(),
        motif_id=motif_id or uuid.uuid4(),
        dream_id=uuid.uuid4(),
        query_label="black river",
        parallels=[
            {
                "domain": "folklore",
                "label": "crossing the dark water",
                "source_url": "https://example.com/river",
                "relevance_note": "Both invoke a threshold crossing image.",
                "confidence": "plausible",
            }
        ],
        sources=[
            {
                "url": "https://example.com/river",
                "retrieved_at": "2026-04-17T10:00:00+00:00",
            }
        ],
        triggered_by="user",
        created_at=created_at,
    )


class _FakeScalars:
    def __init__(self, items):
        self._items = list(items)

    def all(self):
        return list(self._items)


class _FakeResult:
    def __init__(self, items):
        self._items = list(items)

    def scalars(self):
        return _FakeScalars(self._items)


class _FakeSession:
    def __init__(self, *, execute_results: list | None = None):
        self._execute_results = list(execute_results or [])
        self.commit = AsyncMock()
        self.refresh = AsyncMock()

    async def execute(self, stmt):
        del stmt
        return self._execute_results.pop(0)


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


def _build_client():
    sys.modules.pop("app.main", None)
    main_module = importlib.import_module("app.main")
    return TestClient(main_module.app)


def _auth_headers() -> dict[str, str]:
    return {"X-API-Key": os.environ["SECRET_KEY"]}


def test_get_research_returns_list_with_interpretation_note() -> None:
    motif_id = uuid.uuid4()
    newer = _make_research_result(motif_id=motif_id)
    older = _make_research_result(
        motif_id=motif_id,
        created_at=newer.created_at - timedelta(hours=1),
    )
    session = _FakeSession(execute_results=[_FakeResult([newer, older])])
    factory = _FakeSessionFactory(session)

    with patch("app.api.research.get_session_factory", return_value=factory):
        with _build_client() as client:
            response = client.get(f"/motifs/{motif_id}/research", headers=_auth_headers())

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload] == [str(newer.id), str(older.id)]
    assert all(item["interpretation_note"] == INTERPRETATION_NOTE for item in payload)


def test_post_research_returns_503_when_disabled() -> None:
    motif_id = uuid.uuid4()
    session = _FakeSession()
    factory = _FakeSessionFactory(session)

    with patch("app.api.research.get_session_factory", return_value=factory):
        with patch("app.api.research.get_settings") as mock_get_settings:
            mock_get_settings.return_value = SimpleNamespace(
                RESEARCH_AUGMENTATION_ENABLED=False
            )
            with _build_client() as client:
                response = client.post(
                    f"/motifs/{motif_id}/research",
                    headers=_auth_headers(),
                )

    assert response.status_code == 503
    assert response.json() == {"detail": "Research augmentation is disabled"}
    session.commit.assert_not_awaited()


def test_post_research_returns_result_with_interpretation_note_when_enabled() -> None:
    motif_id = uuid.uuid4()
    research_result = _make_research_result(motif_id=motif_id)
    session = _FakeSession()
    factory = _FakeSessionFactory(session)

    with patch("app.api.research.get_session_factory", return_value=factory):
        with patch("app.api.research.get_settings") as mock_get_settings:
            mock_get_settings.return_value = SimpleNamespace(
                RESEARCH_AUGMENTATION_ENABLED=True
            )
            with patch("app.api.research.ResearchService") as mock_service_cls:
                service = mock_service_cls.return_value
                service.run = AsyncMock(return_value=research_result)
                with _build_client() as client:
                    response = client.post(
                        f"/motifs/{motif_id}/research",
                        headers=_auth_headers(),
                    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(research_result.id)
    assert payload["motif_id"] == str(motif_id)
    assert payload["interpretation_note"] == INTERPRETATION_NOTE
    service.run.assert_awaited_once_with(motif_id, session, triggered_by="user")
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(research_result)
