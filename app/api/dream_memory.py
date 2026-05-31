from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.models.dream import DreamEntry
from app.models.dream_graph_privacy import (
    DreamGraphExportOptions,
    DreamGraphExportScope,
    export_dream_graph,
)
from app.models.motif import MotifInduction
from app.services.dream_memory_graph import build_dream_memory_snapshot
from app.services.proof_receipts import DreamPrivacyActionReceipt, build_privacy_export_receipt
from app.shared.database import get_session_factory
from app.shared.tracing import get_tracer

router = APIRouter()


class DreamMemoryReceiptResponse(BaseModel):
    receipt: dict[str, Any]
    receipt_sha256: str


class DreamMemoryExportResponse(BaseModel):
    export: dict[str, Any]
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


def _receipt_payload(receipt: DreamPrivacyActionReceipt) -> DreamMemoryReceiptResponse:
    return DreamMemoryReceiptResponse(
        receipt=json.loads(receipt.canonical_json()),
        receipt_sha256=receipt.receipt_sha256(),
    )
