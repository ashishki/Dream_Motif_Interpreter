from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.models.research import ResearchResult
from app.services.research_service import ResearchService
from app.shared.config import get_settings
from app.shared.database import get_session_factory
from app.shared.tracing import get_tracer

router = APIRouter()

INTERPRETATION_NOTE = (
    "Research results are external suggestions. They have not been verified and do not "
    "constitute claims about the dream."
)


class ResearchResultResponse(BaseModel):
    id: uuid.UUID
    motif_id: uuid.UUID
    dream_id: uuid.UUID
    query_label: str
    parallels: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    triggered_by: str
    created_at: str
    interpretation_note: Literal[
        "Research results are external suggestions. They have not been verified and do not constitute claims about the dream."
    ] = INTERPRETATION_NOTE


@router.get(
    "/motifs/{motif_id}/research",
    response_model=list[ResearchResultResponse],
)
async def list_research_results(motif_id: uuid.UUID) -> list[ResearchResultResponse]:
    tracer = get_tracer(__name__)
    async with get_session_factory()() as session:
        with tracer.start_as_current_span("db.query.research.list"):
            result = await session.execute(
                select(ResearchResult)
                .where(ResearchResult.motif_id == motif_id)
                .order_by(ResearchResult.created_at.desc(), ResearchResult.id.desc())
            )
        research_results = list(result.scalars().all())

    return [_to_response(item) for item in research_results]


@router.post(
    "/motifs/{motif_id}/research",
    response_model=ResearchResultResponse,
)
async def create_research_result(motif_id: uuid.UUID) -> ResearchResultResponse:
    if not get_settings().RESEARCH_AUGMENTATION_ENABLED:
        raise HTTPException(status_code=503, detail="Research augmentation is disabled")

    tracer = get_tracer(__name__)
    async with get_session_factory()() as session:
        service = ResearchService()
        try:
            research_result = await service.run(
                motif_id,
                session,
                triggered_by="user",
            )
        except ValueError as exc:
            error_message = str(exc)
            if "not found" in error_message:
                raise HTTPException(status_code=404, detail="Motif not found") from exc
            if "confirmed motifs" in error_message:
                raise HTTPException(status_code=409, detail=error_message) from exc
            raise

        with tracer.start_as_current_span("db.query.research.commit"):
            await session.commit()
        with tracer.start_as_current_span("db.query.research.refresh"):
            await session.refresh(research_result)

    return _to_response(research_result)


def _to_response(research_result: ResearchResult) -> ResearchResultResponse:
    return ResearchResultResponse(
        id=research_result.id,
        motif_id=research_result.motif_id,
        dream_id=research_result.dream_id,
        query_label=research_result.query_label,
        parallels=(
            research_result.parallels if isinstance(research_result.parallels, list) else []
        ),
        sources=research_result.sources if isinstance(research_result.sources, list) else [],
        triggered_by=research_result.triggered_by,
        created_at=research_result.created_at.isoformat(),
    )
