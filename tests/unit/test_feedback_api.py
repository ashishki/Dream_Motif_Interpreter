from __future__ import annotations

import importlib
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient


def _make_feedback(
    *,
    created_at: datetime,
    score: int = 3,
    chat_id: str = "77",
    comment: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        chat_id=chat_id,
        context={
            "message_id": 9001,
            "response_summary": "Detailed interpretation",
            "tool_calls_made": ["search_dreams"],
        },
        score=score,
        comment=comment,
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
    def __init__(self, items: list[SimpleNamespace]):
        self._items = list(items)
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        ordered = sorted(
            self._items,
            key=lambda item: (item.created_at, str(item.id)),
            reverse=True,
        )
        limit = getattr(getattr(stmt, "_limit_clause", None), "value", None)
        offset = getattr(getattr(stmt, "_offset_clause", None), "value", 0) or 0
        paginated = ordered[offset:]
        if limit is not None:
            paginated = paginated[:limit]
        return _FakeResult(paginated)


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


def test_get_feedback_returns_list_ordered_by_created_at_desc() -> None:
    now = datetime(2026, 4, 17, 10, 0, 0, tzinfo=timezone.utc)
    oldest = _make_feedback(created_at=now - timedelta(hours=2), score=1)
    newest = _make_feedback(created_at=now, score=5, comment="helpful")
    middle = _make_feedback(created_at=now - timedelta(hours=1), score=3)
    session = _FakeSession([oldest, newest, middle])
    factory = _FakeSessionFactory(session)

    with patch("app.api.feedback.get_session_factory", return_value=factory):
        with _build_client() as client:
            response = client.get("/feedback", headers=_auth_headers())

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload] == [
        str(newest.id),
        str(middle.id),
        str(oldest.id),
    ]
    assert "ORDER BY assistant_feedback.created_at DESC" in str(session.statements[0])


def test_get_feedback_respects_limit_and_offset_pagination() -> None:
    now = datetime(2026, 4, 17, 10, 0, 0, tzinfo=timezone.utc)
    items = [
        _make_feedback(created_at=now - timedelta(minutes=index), score=index + 1)
        for index in range(5)
    ]
    session = _FakeSession(items)
    factory = _FakeSessionFactory(session)

    with patch("app.api.feedback.get_session_factory", return_value=factory):
        with _build_client() as client:
            response = client.get(
                "/feedback?limit=2&offset=1",
                headers=_auth_headers(),
            )

    assert response.status_code == 200
    payload = response.json()
    expected = sorted(items, key=lambda item: (item.created_at, str(item.id)), reverse=True)[
        1:3
    ]
    assert [item["id"] for item in payload] == [str(item.id) for item in expected]
    assert getattr(session.statements[0]._limit_clause, "value", None) == 2
    assert getattr(session.statements[0]._offset_clause, "value", None) == 1


def test_get_feedback_returns_401_without_api_key() -> None:
    with _build_client() as client:
        response = client.get("/feedback")

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
