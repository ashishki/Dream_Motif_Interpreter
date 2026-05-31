from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.dream_memory import (
    DreamMemoryDeletionControlRequest,
    DreamMemoryExportResponse,
    DreamMemoryGraphStateResponse,
    DreamMemoryHideControlRequest,
    DreamMemoryRejectionControlRequest,
    DreamMemorySourceFragmentRequest,
    create_dream_memory_deletion_control,
    create_dream_memory_hide_control,
    create_dream_memory_rejection_control,
    export_dream_memory,
    read_dream_memory_state,
)
from app.models.dream_graph_privacy import DreamGraphExportScope

_NOW = datetime(2026, 5, 31, tzinfo=timezone.utc)


def _make_dream() -> SimpleNamespace:
    dream = SimpleNamespace()
    dream.id = uuid.uuid4()
    dream.title = "private flying dream"
    dream.raw_text = "I flew over a private city."
    dream.source_doc_id = "private-doc-id"
    dream.created_at = _NOW
    return dream


def _make_motif(*, dream_id: uuid.UUID, status: str = "confirmed") -> SimpleNamespace:
    motif = SimpleNamespace()
    motif.id = uuid.uuid4()
    motif.dream_id = dream_id
    motif.label = "flying"
    motif.status = status
    motif.confidence = "high"
    motif.model_version = "test-model-v1"
    motif.fragments = [
        {
            "text": "flew over",
            "start_offset": 2,
            "end_offset": 11,
        }
    ]
    motif.created_at = _NOW
    return motif


def _make_privacy_control(
    *,
    subject_type: str,
    subject_id: str,
    action: str = "delete",
) -> SimpleNamespace:
    control = SimpleNamespace()
    control.id = uuid.uuid4()
    control.subject_type = subject_type
    control.subject_id = subject_id
    control.action = action
    control.created_at = _NOW
    return control


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
    def __init__(self, execute_results: list[_FakeResult]) -> None:
        self._execute_results = list(execute_results)
        self.added: list[object] = []
        self.committed = False

    async def execute(self, stmt):
        del stmt
        return self._execute_results.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True


class _SessionCtx:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *args):
        return False


class _FakeSessionFactory:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def __call__(self):
        return _SessionCtx(self._session)


@pytest.mark.asyncio
async def test_export_dream_memory_returns_graph_export_with_receipt() -> None:
    dream = _make_dream()
    motif = _make_motif(dream_id=dream.id)
    session = _FakeSession(
        execute_results=[_FakeResult([dream]), _FakeResult([motif]), _FakeResult([])]
    )

    with patch(
        "app.api.dream_memory.get_session_factory",
        return_value=_FakeSessionFactory(session),
    ):
        response = await export_dream_memory(scope=DreamGraphExportScope.NORMAL_GRAPH_OUTPUT)

    assert isinstance(response, DreamMemoryExportResponse)
    assert response.export["format"] == "dream-memory-graph-export.v1"
    assert response.export["scope"] == "normal_graph_output"
    assert {node["id"] for node in response.export["nodes"]} == {
        f"dream:{dream.id}",
        f"motif_induction:{motif.id}",
    }
    assert response.export["edges"][0]["suggestion"]["source_fragments"] == [
        {
            "dream_id": str(dream.id),
            "chunk_id": None,
            "fragment_index": None,
            "start_char": 2,
            "end_char": 11,
        }
    ]
    assert response.receipt.receipt["type"] == "privacy_export_receipt"
    assert response.receipt.receipt["action"] == "graph_exported"
    assert len(response.receipt.receipt_sha256) == 64


@pytest.mark.asyncio
async def test_read_dream_memory_state_returns_filtered_graph_and_privacy_controls() -> None:
    dream = _make_dream()
    motif = _make_motif(dream_id=dream.id)
    subject_id = f"motif_induction:{motif.id}"
    control = _make_privacy_control(
        subject_type="graph_node",
        subject_id=subject_id,
        action="hide",
    )
    session = _FakeSession(
        execute_results=[
            _FakeResult([dream]),
            _FakeResult([motif]),
            _FakeResult([control]),
        ]
    )

    with patch(
        "app.api.dream_memory.get_session_factory",
        return_value=_FakeSessionFactory(session),
    ):
        response = await read_dream_memory_state(scope=DreamGraphExportScope.NORMAL_GRAPH_OUTPUT)

    assert isinstance(response, DreamMemoryGraphStateResponse)
    assert response.format == "dream-memory-mini-app-state.v1"
    assert response.scope == DreamGraphExportScope.NORMAL_GRAPH_OUTPUT
    assert subject_id not in {node["id"] for node in response.graph["nodes"]}
    assert response.graph["edges"] == []
    assert response.privacy_controls["hidden_node_ids"] == [subject_id]
    assert "receipt" not in response.model_dump()


@pytest.mark.asyncio
async def test_export_dream_memory_does_not_include_raw_dream_text_or_titles() -> None:
    dream = _make_dream()
    motif = _make_motif(dream_id=dream.id)
    session = _FakeSession(
        execute_results=[_FakeResult([dream]), _FakeResult([motif]), _FakeResult([])]
    )

    with patch(
        "app.api.dream_memory.get_session_factory",
        return_value=_FakeSessionFactory(session),
    ):
        response = await export_dream_memory(scope=DreamGraphExportScope.NORMAL_GRAPH_OUTPUT)

    serialized_export = json.dumps(response.export, sort_keys=True)
    assert dream.title not in serialized_export
    assert dream.raw_text not in serialized_export
    assert dream.source_doc_id not in serialized_export


@pytest.mark.asyncio
async def test_export_dream_memory_applies_persisted_deletion_controls() -> None:
    dream = _make_dream()
    motif = _make_motif(dream_id=dream.id)
    control = _make_privacy_control(
        subject_type="graph_node",
        subject_id=f"motif_induction:{motif.id}",
    )
    session = _FakeSession(
        execute_results=[
            _FakeResult([dream]),
            _FakeResult([motif]),
            _FakeResult([control]),
        ]
    )

    with patch(
        "app.api.dream_memory.get_session_factory",
        return_value=_FakeSessionFactory(session),
    ):
        response = await export_dream_memory(scope=DreamGraphExportScope.NORMAL_GRAPH_OUTPUT)

    assert f"motif_induction:{motif.id}" not in {node["id"] for node in response.export["nodes"]}
    assert response.export["edges"] == []
    assert response.export["privacy_controls"]["deleted_node_ids"] == [
        f"motif_induction:{motif.id}"
    ]


@pytest.mark.asyncio
async def test_export_dream_memory_applies_persisted_hide_controls() -> None:
    dream = _make_dream()
    motif = _make_motif(dream_id=dream.id)
    control = _make_privacy_control(
        subject_type="graph_node",
        subject_id=f"motif_induction:{motif.id}",
        action="hide",
    )
    session = _FakeSession(
        execute_results=[
            _FakeResult([dream]),
            _FakeResult([motif]),
            _FakeResult([control]),
        ]
    )

    with patch(
        "app.api.dream_memory.get_session_factory",
        return_value=_FakeSessionFactory(session),
    ):
        response = await export_dream_memory(scope=DreamGraphExportScope.NORMAL_GRAPH_OUTPUT)

    assert f"motif_induction:{motif.id}" not in {node["id"] for node in response.export["nodes"]}
    assert response.export["edges"] == []
    assert response.export["privacy_controls"]["hidden_node_ids"] == [f"motif_induction:{motif.id}"]


@pytest.mark.asyncio
async def test_export_dream_memory_delete_overrides_prior_hide_control() -> None:
    dream = _make_dream()
    motif = _make_motif(dream_id=dream.id)
    subject_id = f"motif_induction:{motif.id}"
    session = _FakeSession(
        execute_results=[
            _FakeResult([dream]),
            _FakeResult([motif]),
            _FakeResult(
                [
                    _make_privacy_control(
                        subject_type="graph_node",
                        subject_id=subject_id,
                        action="hide",
                    ),
                    _make_privacy_control(
                        subject_type="graph_node",
                        subject_id=subject_id,
                        action="delete",
                    ),
                ]
            ),
        ]
    )

    with patch(
        "app.api.dream_memory.get_session_factory",
        return_value=_FakeSessionFactory(session),
    ):
        response = await export_dream_memory(scope=DreamGraphExportScope.NORMAL_GRAPH_OUTPUT)

    assert response.export["privacy_controls"]["hidden_node_ids"] == []
    assert response.export["privacy_controls"]["deleted_node_ids"] == [subject_id]


@pytest.mark.asyncio
async def test_export_dream_memory_applies_persisted_rejection_controls() -> None:
    dream = _make_dream()
    motif = _make_motif(dream_id=dream.id)
    subject_id = f"motif_induction:{motif.id}"
    control = _make_privacy_control(
        subject_type="graph_node",
        subject_id=subject_id,
        action="reject",
    )
    control.control_payload = {
        "rejected_suggestions": [
            {
                "subject_type": "node",
                "subject_id": subject_id,
                "source_fragments": [
                    {
                        "dream_id": str(dream.id),
                        "chunk_id": None,
                        "fragment_index": 0,
                        "start_char": None,
                        "end_char": None,
                    }
                ],
            }
        ]
    }
    session = _FakeSession(
        execute_results=[
            _FakeResult([dream]),
            _FakeResult([motif]),
            _FakeResult([control]),
        ]
    )

    with patch(
        "app.api.dream_memory.get_session_factory",
        return_value=_FakeSessionFactory(session),
    ):
        response = await export_dream_memory(scope=DreamGraphExportScope.NORMAL_GRAPH_OUTPUT)

    assert subject_id not in {node["id"] for node in response.export["nodes"]}
    assert response.export["privacy_controls"]["rejected_node_ids"] == [subject_id]
    assert response.export["privacy_controls"]["rejected_suggestions"][0]["source_fragments"] == [
        {
            "dream_id": str(dream.id),
            "chunk_id": None,
            "fragment_index": 0,
            "start_char": None,
            "end_char": None,
        }
    ]


def test_dream_memory_export_router_registered_in_app() -> None:
    import importlib
    import sys

    sys.modules.pop("app.main", None)
    main_module = importlib.import_module("app.main")
    app = main_module.app

    paths = [route.path for route in app.routes if hasattr(route, "path")]
    assert "/dream-memory/state" in paths
    assert "/dream-memory/export" in paths


def test_dream_memory_state_requires_api_key() -> None:
    import importlib
    import sys

    sys.modules.pop("app.main", None)
    main_module = importlib.import_module("app.main")

    with TestClient(main_module.app) as client:
        response = client.get("/dream-memory/state")

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_dream_memory_export_requires_api_key() -> None:
    import importlib
    import sys

    sys.modules.pop("app.main", None)
    main_module = importlib.import_module("app.main")

    with TestClient(main_module.app) as client:
        response = client.get("/dream-memory/export")

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


@pytest.mark.asyncio
async def test_create_deletion_control_returns_receipt_for_deleted_dream() -> None:
    session = _FakeSession(execute_results=[])

    with patch(
        "app.api.dream_memory.get_session_factory",
        return_value=_FakeSessionFactory(session),
    ):
        response = await create_dream_memory_deletion_control(
            DreamMemoryDeletionControlRequest(
                subject_type="dream",
                subject_id="dream-1",
            )
        )

    assert response.subject_type == "dream"
    assert response.subject_id == "dream-1"
    assert response.privacy_controls["deleted_dream_ids"] == ["dream-1"]
    assert response.receipt.receipt["type"] == "deletion_receipt"
    assert response.receipt.receipt["action"] == "dream_deleted"
    assert response.receipt.receipt["verifier_status"] == "passed"
    assert "source archive deletion is not implemented" in response.effect_note
    assert session.committed is True
    persisted = session.added[0]
    assert persisted.subject_type == "dream"
    assert persisted.subject_id == "dream-1"
    assert persisted.action == "delete"
    assert persisted.control_payload["deleted_dream_ids"] == ["dream-1"]
    assert persisted.receipt_payload["receipt"]["type"] == "deletion_receipt"


@pytest.mark.asyncio
async def test_create_deletion_control_supports_graph_node_and_edge_subjects() -> None:
    node_session = _FakeSession(execute_results=[])
    edge_session = _FakeSession(execute_results=[])

    with patch(
        "app.api.dream_memory.get_session_factory",
        return_value=_FakeSessionFactory(node_session),
    ):
        node_response = await create_dream_memory_deletion_control(
            DreamMemoryDeletionControlRequest(
                subject_type="graph_node",
                subject_id="motif_induction:1",
            )
        )
    with patch(
        "app.api.dream_memory.get_session_factory",
        return_value=_FakeSessionFactory(edge_session),
    ):
        edge_response = await create_dream_memory_deletion_control(
            DreamMemoryDeletionControlRequest(
                subject_type="graph_edge",
                subject_id="edge:1",
            )
        )

    assert node_response.privacy_controls["deleted_node_ids"] == ["motif_induction:1"]
    assert node_response.receipt.receipt["action"] == "node_deleted"
    assert edge_response.privacy_controls["deleted_edge_ids"] == ["edge:1"]
    assert edge_response.receipt.receipt["action"] == "edge_deleted"
    assert node_session.added[0].control_payload["deleted_node_ids"] == ["motif_induction:1"]
    assert edge_session.added[0].control_payload["deleted_edge_ids"] == ["edge:1"]


def test_dream_memory_delete_control_requires_api_key() -> None:
    import importlib
    import sys

    sys.modules.pop("app.main", None)
    main_module = importlib.import_module("app.main")

    with TestClient(main_module.app) as client:
        response = client.post(
            "/dream-memory/privacy/delete",
            json={"subject_type": "dream", "subject_id": "dream-1"},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


@pytest.mark.asyncio
async def test_create_hide_control_returns_receipt_for_hidden_node() -> None:
    session = _FakeSession(execute_results=[])

    with patch(
        "app.api.dream_memory.get_session_factory",
        return_value=_FakeSessionFactory(session),
    ):
        response = await create_dream_memory_hide_control(
            DreamMemoryHideControlRequest(
                subject_type="graph_node",
                subject_id="motif_induction:1",
            )
        )

    assert response.subject_type == "graph_node"
    assert response.subject_id == "motif_induction:1"
    assert response.privacy_controls["hidden_node_ids"] == ["motif_induction:1"]
    assert response.receipt.receipt["type"] == "privacy_control_receipt"
    assert response.receipt.receipt["action"] == "node_hidden"
    assert response.receipt.receipt["verifier_status"] == "passed"
    assert session.committed is True
    persisted = session.added[0]
    assert persisted.subject_type == "graph_node"
    assert persisted.subject_id == "motif_induction:1"
    assert persisted.action == "hide"
    assert persisted.control_payload["hidden_node_ids"] == ["motif_induction:1"]


def test_dream_memory_hide_control_requires_api_key() -> None:
    import importlib
    import sys

    sys.modules.pop("app.main", None)
    main_module = importlib.import_module("app.main")

    with TestClient(main_module.app) as client:
        response = client.post(
            "/dream-memory/privacy/hide",
            json={"subject_type": "graph_node", "subject_id": "motif_induction:1"},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


@pytest.mark.asyncio
async def test_create_rejection_control_returns_receipt_for_rejected_edge() -> None:
    session = _FakeSession(execute_results=[])

    with patch(
        "app.api.dream_memory.get_session_factory",
        return_value=_FakeSessionFactory(session),
    ):
        response = await create_dream_memory_rejection_control(
            DreamMemoryRejectionControlRequest(
                subject_type="graph_edge",
                subject_id="edge:1",
                source_fragments=[
                    DreamMemorySourceFragmentRequest(
                        dream_id="dream-1",
                        chunk_id="chunk-1",
                    )
                ],
            )
        )

    assert response.subject_type == "graph_edge"
    assert response.subject_id == "edge:1"
    assert response.privacy_controls["rejected_edge_ids"] == ["edge:1"]
    assert response.receipt.receipt["type"] == "privacy_control_receipt"
    assert response.receipt.receipt["action"] == "edge_rejected"
    assert response.receipt.receipt["verifier_status"] == "passed"
    assert session.committed is True
    persisted = session.added[0]
    assert persisted.subject_type == "graph_edge"
    assert persisted.subject_id == "edge:1"
    assert persisted.action == "reject"
    assert persisted.control_payload["rejected_suggestions"][0]["source_fragments"][0] == {
        "dream_id": "dream-1",
        "chunk_id": "chunk-1",
        "fragment_index": None,
        "start_char": None,
        "end_char": None,
    }


def test_dream_memory_reject_control_requires_api_key() -> None:
    import importlib
    import sys

    sys.modules.pop("app.main", None)
    main_module = importlib.import_module("app.main")

    with TestClient(main_module.app) as client:
        response = client.post(
            "/dream-memory/privacy/reject",
            json={
                "subject_type": "graph_edge",
                "subject_id": "edge:1",
                "source_fragments": [{"dream_id": "dream-1", "chunk_id": "chunk-1"}],
            },
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
