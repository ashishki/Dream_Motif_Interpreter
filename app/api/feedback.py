from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.models.feedback import AssistantFeedback
from app.shared.database import get_session_factory
from app.shared.tracing import get_meter, get_tracer

router = APIRouter()
_feedback_list_counter = get_meter(__name__).create_counter(
    "feedback.list_total",
    description="Feedback list API calls",
)


class AssistantFeedbackResponse(BaseModel):
    id: uuid.UUID
    chat_id: str
    context: dict[str, Any]
    score: int
    comment: str | None
    created_at: str


@router.get("/feedback", response_model=list[AssistantFeedbackResponse])
async def list_feedback(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[AssistantFeedbackResponse]:
    tracer = get_tracer(__name__)
    try:
        async with get_session_factory()() as session:
            with tracer.start_as_current_span("db.query.feedback.list"):
                result = await session.execute(
                    select(AssistantFeedback)
                    .order_by(
                        AssistantFeedback.created_at.desc(),
                        AssistantFeedback.id.desc(),
                    )
                    .limit(limit)
                    .offset(offset)
                )
            feedback_rows = list(result.scalars().all())
    except Exception:
        _feedback_list_counter.add(1, {"status": "error"})
        raise

    _feedback_list_counter.add(1, {"status": "success"})

    return [_to_response(row) for row in feedback_rows]


def _to_response(feedback: AssistantFeedback) -> AssistantFeedbackResponse:
    return AssistantFeedbackResponse(
        id=feedback.id,
        chat_id=feedback.chat_id,
        context=feedback.context if isinstance(feedback.context, dict) else {},
        score=feedback.score,
        comment=feedback.comment,
        created_at=feedback.created_at.isoformat(),
    )
