from __future__ import annotations

import json
import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.models.annotation import AnnotationVersion
from app.models.motif import MotifInduction
from app.services.dream_memory_graph import motif_to_dream_edge, motif_to_graph_node
from app.services.proof_receipts import (
    DreamMemoryActionReceipt,
    build_edge_memory_receipt,
    build_node_memory_receipt,
)
from app.services.versioning import _annotation_version
from app.shared.database import get_session_factory
from app.shared.tracing import get_tracer

router = APIRouter()

INTERPRETATION_NOTE = (
    "Inducted motifs are computational suggestions, not authoritative conclusions."
)


class MotifResponse(BaseModel):
    id: uuid.UUID
    dream_id: uuid.UUID
    label: str
    rationale: str | None
    confidence: str | None
    status: str
    fragments: list[dict[str, Any]]
    interpretation_note: Literal[
        "Inducted motifs are computational suggestions, not authoritative conclusions."
    ] = INTERPRETATION_NOTE


class MotifListResponse(BaseModel):
    dream_id: uuid.UUID
    # Rejected motifs are excluded from the default response.
    # Pass ?include_rejected=true to include them.
    items: list[MotifResponse]


class MotifStatusUpdateRequest(BaseModel):
    status: Literal["confirmed", "rejected"]


class MotifHistoryItem(BaseModel):
    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    snapshot: dict[str, Any]
    created_at: str


class MotifHistoryResponse(BaseModel):
    dream_id: uuid.UUID
    items: list[MotifHistoryItem]


@router.get("/dreams/{dream_id}/motifs", response_model=MotifListResponse)
async def list_motifs(
    dream_id: uuid.UUID,
    include_rejected: bool = False,
) -> MotifListResponse:
    tracer = get_tracer(__name__)
    async with get_session_factory()() as session:
        with tracer.start_as_current_span("db.query.motifs.list"):
            stmt = select(MotifInduction).where(MotifInduction.dream_id == dream_id)
            if not include_rejected:
                # AC-4: rejected motifs excluded from default response
                stmt = stmt.where(MotifInduction.status != "rejected")
            result = await session.execute(stmt)
        motifs = list(result.scalars().all())

    return MotifListResponse(
        dream_id=dream_id,
        items=[
            MotifResponse(
                id=m.id,
                dream_id=m.dream_id,
                label=m.label,
                rationale=m.rationale,
                confidence=m.confidence,
                status=m.status,
                fragments=m.fragments if isinstance(m.fragments, list) else [],
            )
            for m in motifs
        ],
    )


@router.patch(
    "/dreams/{dream_id}/motifs/{motif_id}",
    response_model=MotifResponse,
)
async def update_motif_status(
    dream_id: uuid.UUID,
    motif_id: uuid.UUID,
    payload: MotifStatusUpdateRequest,
) -> MotifResponse:
    tracer = get_tracer(__name__)
    async with get_session_factory()() as session:
        with tracer.start_as_current_span("db.query.motifs.load"):
            result = await session.execute(
                select(MotifInduction).where(
                    MotifInduction.id == motif_id,
                    MotifInduction.dream_id == dream_id,
                )
            )
        motif = result.scalar_one_or_none()

        if motif is None:
            raise HTTPException(status_code=404, detail="Motif not found")

        # AC-2: write AnnotationVersion before committing
        snapshot = {
            "entity_type": "motif_induction",
            "entity_id": str(motif.id),
            "dream_id": str(motif.dream_id),
            "label": motif.label,
            "status_before": motif.status,
            "status_after": payload.status,
            "changed_by": "user",
        }
        local_receipts = _build_local_memory_action_receipts(motif, payload.status)
        if local_receipts:
            snapshot["local_memory_action_receipts"] = [
                _receipt_payload(receipt) for receipt in local_receipts
            ]
        annotation = _annotation_version(
            entity_type="motif_induction",
            entity_id=motif.id,
            snapshot=snapshot,
            changed_by="user",
        )
        session.add(annotation)
        with tracer.start_as_current_span("db.query.motifs.flush_annotation"):
            await session.flush()

        motif.status = payload.status
        with tracer.start_as_current_span("db.query.motifs.commit"):
            await session.commit()

    return MotifResponse(
        id=motif.id,
        dream_id=motif.dream_id,
        label=motif.label,
        rationale=motif.rationale,
        confidence=motif.confidence,
        status=motif.status,
        fragments=motif.fragments if isinstance(motif.fragments, list) else [],
    )


def _build_local_memory_action_receipts(
    motif: MotifInduction,
    to_status: str,
) -> tuple[DreamMemoryActionReceipt, ...]:
    if to_status != "confirmed":
        return ()

    node = motif_to_graph_node(motif)
    edge = motif_to_dream_edge(motif)
    return (
        build_node_memory_receipt(node=node, action="node_confirmed"),
        build_edge_memory_receipt(edge=edge, action="edge_confirmed"),
    )


def _receipt_payload(receipt: DreamMemoryActionReceipt) -> dict[str, Any]:
    return {
        "receipt": json.loads(receipt.canonical_json()),
        "receipt_sha256": receipt.receipt_sha256(),
    }


@router.get(
    "/dreams/{dream_id}/motifs/history",
    response_model=MotifHistoryResponse,
)
async def get_motif_history(dream_id: uuid.UUID) -> MotifHistoryResponse:
    # AC-3: return annotation version history for motif status changes
    tracer = get_tracer(__name__)
    async with get_session_factory()() as session:
        with tracer.start_as_current_span("db.query.motifs.history"):
            result = await session.execute(
                select(AnnotationVersion)
                .join(
                    MotifInduction,
                    MotifInduction.id == AnnotationVersion.entity_id,
                )
                .where(
                    AnnotationVersion.entity_type == "motif_induction",
                    MotifInduction.dream_id == dream_id,
                )
                .order_by(
                    AnnotationVersion.created_at.desc(),
                    AnnotationVersion.id.desc(),
                )
            )
        versions = list(result.scalars().all())

    return MotifHistoryResponse(
        dream_id=dream_id,
        items=[
            MotifHistoryItem(
                id=v.id,
                entity_type=v.entity_type,
                entity_id=v.entity_id,
                snapshot=v.snapshot,
                created_at=v.created_at.isoformat(),
            )
            for v in versions
        ],
    )
