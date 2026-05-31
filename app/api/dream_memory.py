from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.models.dream import DreamEntry
from app.models.dream_graph_control import DreamGraphPrivacyControl
from app.models.dream_graph_privacy import (
    DreamGraphExportOptions,
    DreamGraphExportScope,
    DreamGraphPrivacyControls,
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
)
from app.shared.database import get_session_factory
from app.shared.tracing import get_tracer

router = APIRouter()
DELETION_CONTROL_EFFECT_NOTE = "This records a graph-output deletion control only; source archive deletion is not implemented by this route."


class DreamMemoryReceiptResponse(BaseModel):
    receipt: dict[str, Any]
    receipt_sha256: str


class DreamMemoryExportResponse(BaseModel):
    export: dict[str, Any]
    receipt: DreamMemoryReceiptResponse


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


@router.get("/dream-memory/export", response_model=DreamMemoryExportResponse)
async def export_dream_memory(
    scope: DreamGraphExportScope = Query(default=DreamGraphExportScope.NORMAL_GRAPH_OUTPUT),
) -> DreamMemoryExportResponse:
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

    export_payload = export_dream_graph(snapshot, DreamGraphExportOptions(scope=scope))
    receipt = build_privacy_export_receipt(export_payload=export_payload)
    return DreamMemoryExportResponse(
        export=export_payload,
        receipt=_receipt_payload(receipt),
    )


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


async def _persist_privacy_control(
    *,
    subject_type: Literal["dream", "graph_node", "graph_edge"],
    subject_id: str,
    action: Literal["delete", "hide"],
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
    for row in rows:
        if row.action == "delete":
            if row.subject_type == "dream":
                deleted_dream_ids.add(row.subject_id)
                hidden_dream_ids.discard(row.subject_id)
            elif row.subject_type == "graph_node":
                deleted_node_ids.add(row.subject_id)
                hidden_node_ids.discard(row.subject_id)
            elif row.subject_type == "graph_edge":
                deleted_edge_ids.add(row.subject_id)
                hidden_edge_ids.discard(row.subject_id)
        elif row.action == "hide":
            if row.subject_type == "dream" and row.subject_id not in deleted_dream_ids:
                hidden_dream_ids.add(row.subject_id)
            elif row.subject_type == "graph_node" and row.subject_id not in deleted_node_ids:
                hidden_node_ids.add(row.subject_id)
            elif row.subject_type == "graph_edge" and row.subject_id not in deleted_edge_ids:
                hidden_edge_ids.add(row.subject_id)
    return DreamGraphPrivacyControls(
        hidden_dream_ids=frozenset(hidden_dream_ids),
        deleted_dream_ids=frozenset(deleted_dream_ids),
        hidden_node_ids=frozenset(hidden_node_ids),
        deleted_node_ids=frozenset(deleted_node_ids),
        hidden_edge_ids=frozenset(hidden_edge_ids),
        deleted_edge_ids=frozenset(deleted_edge_ids),
    )


def _receipt_payload(receipt: DreamPrivacyActionReceipt) -> DreamMemoryReceiptResponse:
    return DreamMemoryReceiptResponse(
        receipt=json.loads(receipt.canonical_json()),
        receipt_sha256=receipt.receipt_sha256(),
    )
