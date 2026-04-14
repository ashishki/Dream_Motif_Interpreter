from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.versioning import VersioningService
from app.shared.database import get_session_factory

router = APIRouter()

INTERPRETATION_NOTE = (
    "These theme assignments are computational interpretations, not authoritative conclusions."
)


class AnnotationVersionHistoryItem(BaseModel):
    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    snapshot: dict[str, Any]
    created_at: str


class DreamThemeHistoryResponse(BaseModel):
    dream_id: uuid.UUID
    items: list[AnnotationVersionHistoryItem]


class ThemeRollbackResponse(BaseModel):
    dream_id: uuid.UUID
    theme_id: uuid.UUID
    category_id: uuid.UUID
    salience: float
    match_type: str
    status: str
    fragments: list[dict[str, Any]]
    deprecated: bool
    interpretation_note: Literal[
        "These theme assignments are computational interpretations, not authoritative conclusions."
    ] = INTERPRETATION_NOTE


@router.get("/dreams/{dream_id}/themes/history", response_model=DreamThemeHistoryResponse)
async def get_theme_history(dream_id: uuid.UUID) -> DreamThemeHistoryResponse:
    async with get_session_factory()() as session:
        dream, versions = await VersioningService.list_theme_history(session, dream_id=dream_id)

    return DreamThemeHistoryResponse(
        dream_id=dream.id,
        items=[
            AnnotationVersionHistoryItem(
                id=version.id,
                entity_type=version.entity_type,
                entity_id=version.entity_id,
                snapshot=version.snapshot,
                created_at=version.created_at.isoformat(),
            )
            for version in versions
        ],
    )


@router.post(
    "/dreams/{dream_id}/themes/{theme_id}/rollback/{version_id}",
    response_model=ThemeRollbackResponse,
)
async def rollback_theme(
    dream_id: uuid.UUID,
    theme_id: uuid.UUID,
    version_id: uuid.UUID,
) -> ThemeRollbackResponse:
    async with get_session_factory()() as session:
        theme = await VersioningService.rollback_theme(
            session,
            dream_id=dream_id,
            theme_id=theme_id,
            version_id=version_id,
            changed_by="user",
        )

    return ThemeRollbackResponse(
        dream_id=theme.dream_id,
        theme_id=theme.id,
        category_id=theme.category_id,
        salience=theme.salience,
        match_type=theme.match_type,
        status=theme.status,
        fragments=[fragment for fragment in theme.fragments if isinstance(fragment, dict)],
        deprecated=theme.deprecated,
        interpretation_note=INTERPRETATION_NOTE,
    )
