from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.models.dream import DreamEntry
from app.models.dream_graph import SourceDreamFragmentRef
from app.models.dream_graph_control import DreamGraphPrivacyControl
from app.models.dream_graph_privacy import (
    DreamGraphExportOptions,
    DreamGraphExportScope,
    DreamGraphSnapshot,
    DreamGraphPrivacyControls,
    RejectedGraphSuggestion,
    RejectedSuggestionSubject,
    export_dream_graph,
    privacy_controls_to_dict,
)
from app.models.motif import MotifInduction
from app.services.dream_memory_graph import build_dream_memory_snapshot
from app.services.proof_receipts import (
    DreamPrivacyActionReceipt,
    build_deletion_receipt,
    build_hide_receipt,
    build_privacy_export_receipt,
    build_rejection_receipt,
)
from app.shared.database import get_session_factory
from app.shared.tracing import get_tracer

router = APIRouter()
DELETION_CONTROL_EFFECT_NOTE = "This records a graph-output deletion control only; source archive deletion is not implemented by this route."
MINI_APP_STATE_FORMAT = "dream-memory-mini-app-state.v1"
MINI_APP_HTML_PATH = Path(__file__).resolve().parents[1] / "static" / "dream_memory_map.html"


class DreamMemoryReceiptResponse(BaseModel):
    receipt: dict[str, Any]
    receipt_sha256: str


class DreamMemoryExportResponse(BaseModel):
    export: dict[str, Any]
    receipt: DreamMemoryReceiptResponse


class DreamMemoryGraphStateResponse(BaseModel):
    format: Literal["dream-memory-mini-app-state.v1"] = MINI_APP_STATE_FORMAT
    scope: DreamGraphExportScope
    graph: dict[str, Any]
    privacy_controls: dict[str, Any]


class DreamMemoryDeletionControlRequest(BaseModel):
    subject_type: Literal["dream", "graph_node", "graph_edge"]
    subject_id: str = Field(min_length=1)


class DreamMemoryDeletionControlResponse(BaseModel):
    subject_type: Literal["dream", "graph_node", "graph_edge"]
    subject_id: str
    privacy_controls: dict[str, Any]
    receipt: DreamMemoryReceiptResponse
    effect_note: Literal[
        "This records a graph-output deletion control only; source archive deletion is not implemented by this route."
    ] = DELETION_CONTROL_EFFECT_NOTE


class DreamMemoryHideControlRequest(BaseModel):
    subject_type: Literal["dream", "graph_node", "graph_edge"]
    subject_id: str = Field(min_length=1)


class DreamMemoryHideControlResponse(BaseModel):
    subject_type: Literal["dream", "graph_node", "graph_edge"]
    subject_id: str
    privacy_controls: dict[str, Any]
    receipt: DreamMemoryReceiptResponse


class DreamMemorySourceFragmentRequest(BaseModel):
    dream_id: str = Field(min_length=1)
    chunk_id: str | None = None
    fragment_index: int | None = Field(default=None, ge=0)
    start_char: int | None = Field(default=None, ge=0)
    end_char: int | None = Field(default=None, ge=1)


class DreamMemoryRejectionControlRequest(BaseModel):
    subject_type: Literal["graph_node", "graph_edge"]
    subject_id: str = Field(min_length=1)
    source_fragments: list[DreamMemorySourceFragmentRequest] = Field(min_length=1)


class DreamMemoryRejectionControlResponse(BaseModel):
    subject_type: Literal["graph_node", "graph_edge"]
    subject_id: str
    privacy_controls: dict[str, Any]
    receipt: DreamMemoryReceiptResponse


@router.get("/dream-memory/mini-app", response_class=FileResponse)
async def dream_memory_mini_app() -> FileResponse:
    return FileResponse(MINI_APP_HTML_PATH, media_type="text/html")


@router.get("/dream-memory/state", response_model=DreamMemoryGraphStateResponse)
async def read_dream_memory_state(
    scope: DreamGraphExportScope = Query(default=DreamGraphExportScope.NORMAL_GRAPH_OUTPUT),
) -> DreamMemoryGraphStateResponse:
    snapshot = await _load_dream_memory_snapshot()
    export_payload = export_dream_graph(snapshot, DreamGraphExportOptions(scope=scope))
    return DreamMemoryGraphStateResponse(
        scope=scope,
        graph={
            "source_dreams": export_payload["source_dreams"],
            "nodes": export_payload["nodes"],
            "edges": export_payload["edges"],
        },
        privacy_controls=export_payload["privacy_controls"],
    )


@router.get("/dream-memory/export", response_model=DreamMemoryExportResponse)
async def export_dream_memory(
    scope: DreamGraphExportScope = Query(default=DreamGraphExportScope.NORMAL_GRAPH_OUTPUT),
) -> DreamMemoryExportResponse:
    snapshot = await _load_dream_memory_snapshot()
    export_payload = export_dream_graph(snapshot, DreamGraphExportOptions(scope=scope))
    receipt = build_privacy_export_receipt(export_payload=export_payload)
    return DreamMemoryExportResponse(
        export=export_payload,
        receipt=_receipt_payload(receipt),
    )


async def _load_dream_memory_snapshot() -> DreamGraphSnapshot:
    tracer = get_tracer(__name__)
    async with get_session_factory()() as session:
        with tracer.start_as_current_span("db.query.dream_memory.load_dreams"):
            dream_result = await session.execute(
                select(DreamEntry).order_by(DreamEntry.created_at.asc(), DreamEntry.id.asc())
            )
        with tracer.start_as_current_span("db.query.dream_memory.load_motifs"):
            motif_result = await session.execute(
                select(MotifInduction).order_by(
                    MotifInduction.created_at.asc(),
                    MotifInduction.id.asc(),
                )
            )
        with tracer.start_as_current_span("db.query.dream_memory.load_privacy_controls"):
            control_result = await session.execute(
                select(DreamGraphPrivacyControl).order_by(
                    DreamGraphPrivacyControl.created_at.asc(),
                    DreamGraphPrivacyControl.id.asc(),
                )
            )

        snapshot = build_dream_memory_snapshot(
            dreams=list(dream_result.scalars().all()),
            motifs=list(motif_result.scalars().all()),
            privacy_controls=_privacy_controls_from_rows(list(control_result.scalars().all())),
        )

    return snapshot


@router.post(
    "/dream-memory/privacy/delete",
    response_model=DreamMemoryDeletionControlResponse,
)
async def create_dream_memory_deletion_control(
    payload: DreamMemoryDeletionControlRequest,
) -> DreamMemoryDeletionControlResponse:
    privacy_controls = _deletion_control_for(payload.subject_type, payload.subject_id)
    receipt = build_deletion_receipt(
        subject_id=payload.subject_id,
        subject_type=payload.subject_type,
        privacy_controls=privacy_controls,
    )
    receipt_payload = _receipt_payload(receipt)
    await _persist_privacy_control(
        subject_type=payload.subject_type,
        subject_id=payload.subject_id,
        action="delete",
        privacy_controls=privacy_controls,
        receipt_payload=receipt_payload,
    )
    return DreamMemoryDeletionControlResponse(
        subject_type=payload.subject_type,
        subject_id=payload.subject_id,
        privacy_controls=privacy_controls_to_dict(privacy_controls),
        receipt=receipt_payload,
    )


@router.post(
    "/dream-memory/privacy/hide",
    response_model=DreamMemoryHideControlResponse,
)
async def create_dream_memory_hide_control(
    payload: DreamMemoryHideControlRequest,
) -> DreamMemoryHideControlResponse:
    privacy_controls = _hide_control_for(payload.subject_type, payload.subject_id)
    receipt = build_hide_receipt(
        subject_id=payload.subject_id,
        subject_type=payload.subject_type,
        privacy_controls=privacy_controls,
    )
    receipt_payload = _receipt_payload(receipt)
    await _persist_privacy_control(
        subject_type=payload.subject_type,
        subject_id=payload.subject_id,
        action="hide",
        privacy_controls=privacy_controls,
        receipt_payload=receipt_payload,
    )
    return DreamMemoryHideControlResponse(
        subject_type=payload.subject_type,
        subject_id=payload.subject_id,
        privacy_controls=privacy_controls_to_dict(privacy_controls),
        receipt=receipt_payload,
    )


@router.post(
    "/dream-memory/privacy/reject",
    response_model=DreamMemoryRejectionControlResponse,
)
async def create_dream_memory_rejection_control(
    payload: DreamMemoryRejectionControlRequest,
) -> DreamMemoryRejectionControlResponse:
    source_fragments = _source_fragment_refs_from_request(payload.source_fragments)
    privacy_controls = _rejection_control_for(
        payload.subject_type,
        payload.subject_id,
        source_fragments,
    )
    receipt = build_rejection_receipt(
        subject_id=payload.subject_id,
        subject_type=payload.subject_type,
        privacy_controls=privacy_controls,
    )
    receipt_payload = _receipt_payload(receipt)
    await _persist_privacy_control(
        subject_type=payload.subject_type,
        subject_id=payload.subject_id,
        action="reject",
        privacy_controls=privacy_controls,
        receipt_payload=receipt_payload,
    )
    return DreamMemoryRejectionControlResponse(
        subject_type=payload.subject_type,
        subject_id=payload.subject_id,
        privacy_controls=privacy_controls_to_dict(privacy_controls),
        receipt=receipt_payload,
    )


def _deletion_control_for(
    subject_type: Literal["dream", "graph_node", "graph_edge"],
    subject_id: str,
) -> DreamGraphPrivacyControls:
    controls = DreamGraphPrivacyControls()
    if subject_type == "dream":
        return controls.delete_dream(subject_id)
    if subject_type == "graph_node":
        return controls.delete_node(subject_id)
    return controls.delete_edge(subject_id)


def _hide_control_for(
    subject_type: Literal["dream", "graph_node", "graph_edge"],
    subject_id: str,
) -> DreamGraphPrivacyControls:
    controls = DreamGraphPrivacyControls()
    if subject_type == "dream":
        return controls.hide_dream(subject_id)
    if subject_type == "graph_node":
        return controls.hide_node(subject_id)
    return controls.hide_edge(subject_id)


def _rejection_control_for(
    subject_type: Literal["graph_node", "graph_edge"],
    subject_id: str,
    source_fragments: tuple[SourceDreamFragmentRef, ...],
) -> DreamGraphPrivacyControls:
    if subject_type == "graph_node":
        return DreamGraphPrivacyControls(
            rejected_node_ids=frozenset((subject_id,)),
            rejected_suggestions=(
                RejectedGraphSuggestion(
                    subject_type=RejectedSuggestionSubject.NODE,
                    subject_id=subject_id,
                    source_fragments=source_fragments,
                ),
            ),
        )
    return DreamGraphPrivacyControls(
        rejected_edge_ids=frozenset((subject_id,)),
        rejected_suggestions=(
            RejectedGraphSuggestion(
                subject_type=RejectedSuggestionSubject.EDGE,
                subject_id=subject_id,
                source_fragments=source_fragments,
            ),
        ),
    )


async def _persist_privacy_control(
    *,
    subject_type: Literal["dream", "graph_node", "graph_edge"],
    subject_id: str,
    action: Literal["delete", "hide", "reject"],
    privacy_controls: DreamGraphPrivacyControls,
    receipt_payload: DreamMemoryReceiptResponse,
) -> None:
    async with get_session_factory()() as session:
        session.add(
            DreamGraphPrivacyControl(
                subject_type=subject_type,
                subject_id=subject_id,
                action=action,
                control_payload=privacy_controls_to_dict(privacy_controls),
                receipt_payload=receipt_payload.model_dump(),
                changed_by="user",
            )
        )
        await session.commit()


def _privacy_controls_from_rows(
    rows: list[DreamGraphPrivacyControl],
) -> DreamGraphPrivacyControls:
    hidden_dream_ids: set[str] = set()
    deleted_dream_ids: set[str] = set()
    hidden_node_ids: set[str] = set()
    deleted_node_ids: set[str] = set()
    hidden_edge_ids: set[str] = set()
    deleted_edge_ids: set[str] = set()
    rejected_node_ids: set[str] = set()
    rejected_edge_ids: set[str] = set()
    rejected_suggestions: dict[tuple[str, str], RejectedGraphSuggestion] = {}
    for row in rows:
        if row.action == "delete":
            if row.subject_type == "dream":
                deleted_dream_ids.add(row.subject_id)
                hidden_dream_ids.discard(row.subject_id)
            elif row.subject_type == "graph_node":
                deleted_node_ids.add(row.subject_id)
                hidden_node_ids.discard(row.subject_id)
                rejected_node_ids.discard(row.subject_id)
                rejected_suggestions.pop(("node", row.subject_id), None)
            elif row.subject_type == "graph_edge":
                deleted_edge_ids.add(row.subject_id)
                hidden_edge_ids.discard(row.subject_id)
                rejected_edge_ids.discard(row.subject_id)
                rejected_suggestions.pop(("edge", row.subject_id), None)
        elif row.action == "hide":
            if row.subject_type == "dream" and row.subject_id not in deleted_dream_ids:
                hidden_dream_ids.add(row.subject_id)
            elif (
                row.subject_type == "graph_node"
                and row.subject_id not in deleted_node_ids
                and row.subject_id not in rejected_node_ids
            ):
                hidden_node_ids.add(row.subject_id)
            elif (
                row.subject_type == "graph_edge"
                and row.subject_id not in deleted_edge_ids
                and row.subject_id not in rejected_edge_ids
            ):
                hidden_edge_ids.add(row.subject_id)
        elif row.action == "reject":
            for suggestion in _rejected_suggestions_from_payload(row.control_payload):
                if (
                    suggestion.subject_type is RejectedSuggestionSubject.NODE
                    and suggestion.subject_id not in deleted_node_ids
                ):
                    rejected_node_ids.add(suggestion.subject_id)
                    hidden_node_ids.discard(suggestion.subject_id)
                    rejected_suggestions[("node", suggestion.subject_id)] = suggestion
                elif (
                    suggestion.subject_type is RejectedSuggestionSubject.EDGE
                    and suggestion.subject_id not in deleted_edge_ids
                ):
                    rejected_edge_ids.add(suggestion.subject_id)
                    hidden_edge_ids.discard(suggestion.subject_id)
                    rejected_suggestions[("edge", suggestion.subject_id)] = suggestion
    return DreamGraphPrivacyControls(
        hidden_dream_ids=frozenset(hidden_dream_ids),
        deleted_dream_ids=frozenset(deleted_dream_ids),
        hidden_node_ids=frozenset(hidden_node_ids),
        deleted_node_ids=frozenset(deleted_node_ids),
        hidden_edge_ids=frozenset(hidden_edge_ids),
        deleted_edge_ids=frozenset(deleted_edge_ids),
        rejected_node_ids=frozenset(rejected_node_ids),
        rejected_edge_ids=frozenset(rejected_edge_ids),
        rejected_suggestions=tuple(rejected_suggestions.values()),
    )


def _source_fragment_refs_from_request(
    fragments: list[DreamMemorySourceFragmentRequest],
) -> tuple[SourceDreamFragmentRef, ...]:
    refs: list[SourceDreamFragmentRef] = []
    for fragment in fragments:
        try:
            refs.append(
                SourceDreamFragmentRef(
                    dream_id=fragment.dream_id,
                    chunk_id=fragment.chunk_id,
                    fragment_index=fragment.fragment_index,
                    start_char=fragment.start_char,
                    end_char=fragment.end_char,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return tuple(refs)


def _rejected_suggestions_from_payload(
    payload: dict[str, Any],
) -> tuple[RejectedGraphSuggestion, ...]:
    suggestions = payload.get("rejected_suggestions", [])
    if not isinstance(suggestions, list):
        return ()

    parsed: list[RejectedGraphSuggestion] = []
    for suggestion in suggestions:
        if not isinstance(suggestion, dict):
            continue
        subject_type = suggestion.get("subject_type")
        subject_id = suggestion.get("subject_id")
        source_fragments = suggestion.get("source_fragments")
        if subject_type not in {"node", "edge"} or not isinstance(subject_id, str):
            continue
        if not isinstance(source_fragments, list):
            continue
        fragment_refs = _source_fragment_refs_from_payload(source_fragments)
        if not fragment_refs:
            continue
        parsed.append(
            RejectedGraphSuggestion(
                subject_type=RejectedSuggestionSubject(subject_type),
                subject_id=subject_id,
                source_fragments=fragment_refs,
            )
        )
    return tuple(parsed)


def _source_fragment_refs_from_payload(
    fragments: list[object],
) -> tuple[SourceDreamFragmentRef, ...]:
    refs: list[SourceDreamFragmentRef] = []
    for fragment in fragments:
        if not isinstance(fragment, dict):
            continue
        try:
            refs.append(
                SourceDreamFragmentRef(
                    dream_id=str(fragment.get("dream_id") or ""),
                    chunk_id=fragment.get("chunk_id")
                    if isinstance(fragment.get("chunk_id"), str)
                    else None,
                    fragment_index=fragment.get("fragment_index")
                    if isinstance(fragment.get("fragment_index"), int)
                    else None,
                    start_char=fragment.get("start_char")
                    if isinstance(fragment.get("start_char"), int)
                    else None,
                    end_char=fragment.get("end_char")
                    if isinstance(fragment.get("end_char"), int)
                    else None,
                )
            )
        except ValueError:
            continue
    return tuple(refs)


def _receipt_payload(receipt: DreamPrivacyActionReceipt) -> DreamMemoryReceiptResponse:
    return DreamMemoryReceiptResponse(
        receipt=json.loads(receipt.canonical_json()),
        receipt_sha256=receipt.receipt_sha256(),
    )
