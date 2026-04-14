from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.dreams import _get_session_factory
from app.services.patterns import PatternService

router = APIRouter()

INTERPRETATION_NOTE = "These are computational patterns, not authoritative interpretations."


class PatternResponseEnvelope(BaseModel):
    interpretation_note: Literal[
        "These are computational patterns, not authoritative interpretations."
    ] = INTERPRETATION_NOTE
    generated_at: str


class RecurringPatternItem(BaseModel):
    category_id: uuid.UUID
    name: str
    count: int
    percentage_of_dreams: float


class RecurringPatternsResponse(PatternResponseEnvelope):
    patterns: list[RecurringPatternItem]


class CoOccurrencePatternItem(BaseModel):
    category_ids: list[uuid.UUID]
    count: int


class CoOccurrencePatternsResponse(PatternResponseEnvelope):
    pairs: list[CoOccurrencePatternItem]


class TimelinePointItem(BaseModel):
    date: str
    salience: float


class ThemeTimelineResponse(PatternResponseEnvelope):
    theme_id: uuid.UUID
    timeline: list[TimelinePointItem]


@router.get("/patterns/recurring", response_model=RecurringPatternsResponse)
async def get_recurring_patterns() -> RecurringPatternsResponse:
    async with _get_session_factory()() as session:
        patterns = await PatternService.list_recurring_patterns(session)

    return RecurringPatternsResponse(
        patterns=[
            RecurringPatternItem(
                category_id=pattern.category_id,
                name=pattern.name,
                count=pattern.count,
                percentage_of_dreams=pattern.percentage_of_dreams,
            )
            for pattern in patterns
        ],
        generated_at=_generated_at(),
    )


@router.get("/patterns/co-occurrence", response_model=CoOccurrencePatternsResponse)
async def get_co_occurrence_patterns() -> CoOccurrencePatternsResponse:
    async with _get_session_factory()() as session:
        patterns = await PatternService.list_co_occurrence_patterns(session)

    return CoOccurrencePatternsResponse(
        pairs=[
            CoOccurrencePatternItem(
                category_ids=sorted(pattern.category_ids, key=str),
                count=pattern.count,
            )
            for pattern in patterns
        ],
        generated_at=_generated_at(),
    )


@router.get("/patterns/timeline", response_model=ThemeTimelineResponse)
async def get_theme_timeline(
    theme_id: uuid.UUID = Query(...),
) -> ThemeTimelineResponse:
    async with _get_session_factory()() as session:
        timeline = await PatternService.get_theme_timeline(session, category_id=theme_id)

    return ThemeTimelineResponse(
        theme_id=theme_id,
        timeline=[
            TimelinePointItem(date=point.date, salience=point.salience) for point in timeline
        ],
        generated_at=_generated_at(),
    )


def _generated_at() -> str:
    return datetime.now(timezone.utc).isoformat()
