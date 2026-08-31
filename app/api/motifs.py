from __future__ import annotations

import json
import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from app.models.annotation import AnnotationVersion
from app.models.dream import DreamEntry
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
    status: Literal["draft", "confirmed", "rejected"] | None = None
    label: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def validate_review_update(self) -> MotifStatusUpdateRequest:
        if self.status is None and self.label is None:
            raise ValueError("status or label is required")
        if self.label is not None:
            self.label = " ".join(self.label.split())
            if not self.label:
                raise ValueError("label must not be empty")
        return self


class MotifReviewItem(MotifResponse):
    dream_title: str
    dream_date: str | None
    can_research: bool


class MotifReviewListResponse(BaseModel):
    items: list[MotifReviewItem]
    draft_count: int
    confirmed_count: int
    rejected_count: int


class MotifHistoryItem(BaseModel):
    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    snapshot: dict[str, Any]
    created_at: str


class MotifHistoryResponse(BaseModel):
    dream_id: uuid.UUID
    items: list[MotifHistoryItem]


@router.get("/motifs/review", response_model=MotifReviewListResponse)
async def list_motifs_for_review(
    status: Literal["draft", "confirmed", "rejected", "all"] = "draft",
    limit: int = 100,
) -> MotifReviewListResponse:
    """Return an evidence-bearing review inbox for the authenticated mini app."""

    bounded_limit = max(1, min(limit, 200))
    tracer = get_tracer(__name__)
    async with get_session_factory()() as session:
        stmt = (
            select(MotifInduction, DreamEntry)
            .join(DreamEntry, DreamEntry.id == MotifInduction.dream_id)
            .order_by(MotifInduction.created_at.desc(), MotifInduction.id.desc())
            .limit(bounded_limit)
        )
        if status != "all":
            stmt = stmt.where(MotifInduction.status == status)
        with tracer.start_as_current_span("db.query.motifs.review"):
            result = await session.execute(stmt)
        rows = list(result.all())

    items = [_to_review_item(motif, dream) for motif, dream in rows]
    return MotifReviewListResponse(
        items=items,
        draft_count=sum(item.status == "draft" for item in items),
        confirmed_count=sum(item.status == "confirmed" for item in items),
        rejected_count=sum(item.status == "rejected" for item in items),
    )


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
        items=[_to_motif_response(motif) for motif in motifs],
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
                select(MotifInduction)
                .where(
                    MotifInduction.id == motif_id,
                    MotifInduction.dream_id == dream_id,
                )
                .with_for_update()
            )
        motif = result.scalar_one_or_none()

        if motif is None:
            raise HTTPException(status_code=404, detail="Motif not found")

        status_before = motif.status
        label_before = motif.label
        status_after = payload.status or status_before
        label_after = payload.label or label_before
        if status_after == status_before and label_after == label_before:
            return _to_motif_response(motif)

        # AC-2: write AnnotationVersion before committing
        snapshot = {
            "entity_type": "motif_induction",
            "entity_id": str(motif.id),
            "dream_id": str(motif.dream_id),
            "label_before": label_before,
            "label_after": label_after,
            "status_before": status_before,
            "status_after": status_after,
            "changed_by": "user",
        }
        # Receipts attest the committed graph projection, including a rename
        # submitted in the same request. Build them from the after-state.
        motif.status = status_after
        motif.label = label_after
        local_receipts = (
            _build_local_memory_action_receipts(motif, status_after)
            if status_before != "confirmed" and status_after == "confirmed"
            else ()
        )
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

        with tracer.start_as_current_span("db.query.motifs.commit"):
            await session.commit()

    return _to_motif_response(motif)


def _to_motif_response(motif: MotifInduction) -> MotifResponse:
    return MotifResponse(
        id=motif.id,
        dream_id=motif.dream_id,
        label=motif.label,
        rationale=motif.rationale,
        confidence=motif.confidence,
        status=motif.status,
        fragments=motif.fragments if isinstance(motif.fragments, list) else [],
    )


def _to_review_item(motif: MotifInduction, dream: DreamEntry) -> MotifReviewItem:
    data = _to_motif_response(motif).model_dump()
    data["fragments"] = _verified_review_fragments(motif.fragments, dream.raw_text)
    return MotifReviewItem(
        **data,
        dream_title=dream.title.strip() or "Без названия",
        dream_date=dream.date.isoformat() if dream.date is not None else None,
        can_research=motif.status == "confirmed",
    )


def _verified_review_fragments(
    fragments: object,
    raw_text: str,
) -> list[dict[str, Any]]:
    """Expose only excerpts that can be checked byte-for-byte against the dream."""

    if not isinstance(fragments, list):
        return []

    verified: list[dict[str, Any]] = []
    for fragment in fragments:
        if not isinstance(fragment, dict) or fragment.get("verified") is False:
            continue
        text = fragment.get("text")
        if not isinstance(text, str) or not text:
            continue
        start = fragment.get("start_offset", fragment.get("start_char"))
        end = fragment.get("end_offset", fragment.get("end_char"))
        if not (
            isinstance(start, int)
            and isinstance(end, int)
            and 0 <= start < end <= len(raw_text)
            and raw_text[start:end] == text
        ):
            start = raw_text.find(text)
            if start < 0:
                continue
            end = start + len(text)
        verified.append(
            {
                "text": text,
                "start_offset": start,
                "end_offset": end,
                "verified": True,
            }
        )
    return verified


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
