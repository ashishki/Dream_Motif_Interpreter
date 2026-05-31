from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.models.dream import DreamEntry
from app.models.dream_graph_privacy import (
    DreamGraphPrivacyControls,
    DreamGraphExportOptions,
    DreamGraphExportScope,
    export_dream_graph,
    privacy_controls_to_dict,
)
from app.models.motif import MotifInduction
from app.services.dream_memory_graph import build_dream_memory_snapshot
from app.services.proof_receipts import (
    DreamPrivacyActionReceipt,
    build_deletion_receipt,
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

        snapshot = build_dream_memory_snapshot(
            dreams=list(dream_result.scalars().all()),
            motifs=list(motif_result.scalars().all()),
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
    return DreamMemoryDeletionControlResponse(
        subject_type=payload.subject_type,
        subject_id=payload.subject_id,
        privacy_controls=privacy_controls_to_dict(privacy_controls),
        receipt=_receipt_payload(receipt),
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


def _receipt_payload(receipt: DreamPrivacyActionReceipt) -> DreamMemoryReceiptResponse:
    return DreamMemoryReceiptResponse(
        receipt=json.loads(receipt.canonical_json()),
        receipt_sha256=receipt.receipt_sha256(),
    )
