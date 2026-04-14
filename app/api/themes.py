from __future__ import annotations

import json
import uuid
from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.dreams import _get_session_factory
from app.models.theme import DreamTheme, ThemeCategory
from app.services.taxonomy import TaxonomyService
from app.services.versioning import build_dream_theme_transition_version
from app.shared.config import get_settings
from app.shared.tracing import get_tracer

router = APIRouter()

INTERPRETATION_NOTE = (
    "These theme assignments are computational interpretations, not authoritative conclusions."
)


class ThemeMutationResponse(BaseModel):
    dream_id: uuid.UUID
    theme_id: uuid.UUID
    category_id: uuid.UUID
    status: str
    interpretation_note: Literal[
        "These theme assignments are computational interpretations, not authoritative conclusions."
    ] = INTERPRETATION_NOTE


class ThemeCategoryResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    status: str


class BulkConfirmRequest(BaseModel):
    dream_ids: list[uuid.UUID] = Field(min_length=1)


class BulkConfirmResponse(BaseModel):
    requires_approval: bool
    token: str | None = None
    confirmed_count: int = 0


@router.patch(
    "/dreams/{dream_id}/themes/{theme_id}/confirm",
    response_model=ThemeMutationResponse,
)
async def confirm_theme(dream_id: uuid.UUID, theme_id: uuid.UUID) -> ThemeMutationResponse:
    theme = await _transition_theme_status(
        dream_id=dream_id,
        theme_id=theme_id,
        to_status="confirmed",
    )
    return ThemeMutationResponse(
        dream_id=theme.dream_id,
        theme_id=theme.id,
        category_id=theme.category_id,
        status=theme.status,
    )


@router.patch(
    "/dreams/{dream_id}/themes/{theme_id}/reject",
    response_model=ThemeMutationResponse,
)
async def reject_theme(dream_id: uuid.UUID, theme_id: uuid.UUID) -> ThemeMutationResponse:
    theme = await _transition_theme_status(
        dream_id=dream_id,
        theme_id=theme_id,
        to_status="rejected",
    )
    return ThemeMutationResponse(
        dream_id=theme.dream_id,
        theme_id=theme.id,
        category_id=theme.category_id,
        status=theme.status,
    )


@router.post("/curate/bulk-confirm", response_model=BulkConfirmResponse)
async def bulk_confirm_themes(payload: BulkConfirmRequest) -> BulkConfirmResponse:
    if len(payload.dream_ids) == 1:
        confirmed_count = await _confirm_draft_themes(payload.dream_ids)
        return BulkConfirmResponse(requires_approval=False, confirmed_count=confirmed_count)

    token = str(uuid.uuid4())
    redis_client = _get_redis_client()
    tracer = get_tracer(__name__)
    with tracer.start_as_current_span("redis.themes.bulk_confirm.store"):
        await redis_client.set(
            _bulk_confirm_key(token),
            json.dumps({"dream_ids": [str(dream_id) for dream_id in payload.dream_ids]}),
            ex=get_settings().BULK_CONFIRM_TOKEN_TTL_SECONDS,
        )
    return BulkConfirmResponse(requires_approval=True, token=token, confirmed_count=0)


@router.post("/curate/bulk-confirm/{token}/approve", response_model=BulkConfirmResponse)
async def approve_bulk_confirm(token: str) -> BulkConfirmResponse:
    redis_client = _get_redis_client()
    tracer = get_tracer(__name__)
    with tracer.start_as_current_span("redis.themes.bulk_confirm.load"):
        payload = await redis_client.get(_bulk_confirm_key(token))

    if payload is None:
        raise HTTPException(status_code=410, detail="Bulk confirmation token has expired")

    try:
        parsed_payload = json.loads(payload)
        dream_ids = [uuid.UUID(value) for value in parsed_payload["dream_ids"]]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=410, detail="Bulk confirmation token has expired") from exc

    confirmed_count = await _confirm_draft_themes(dream_ids)

    with tracer.start_as_current_span("redis.themes.bulk_confirm.delete"):
        await redis_client.delete(_bulk_confirm_key(token))

    return BulkConfirmResponse(
        requires_approval=False,
        token=token,
        confirmed_count=confirmed_count,
    )


@router.patch("/themes/categories/{category_id}/approve", response_model=ThemeCategoryResponse)
async def approve_theme_category(category_id: uuid.UUID) -> ThemeCategoryResponse:
    async with _get_session_factory()() as session:
        try:
            await TaxonomyService.approve_category(
                session,
                category_id,
                changed_by="user",
            )
        except ValueError as exc:
            error_message = str(exc)
            if "does not exist" in error_message:
                raise HTTPException(status_code=404, detail="Theme category not found") from exc
            raise HTTPException(status_code=409, detail=error_message) from exc

        category = await session.get(ThemeCategory, category_id)

    if category is None:
        raise HTTPException(status_code=404, detail="Theme category not found")

    return ThemeCategoryResponse(
        id=category.id,
        name=category.name,
        description=category.description,
        status=category.status,
    )


async def _transition_theme_status(
    *,
    dream_id: uuid.UUID,
    theme_id: uuid.UUID,
    to_status: str,
) -> DreamTheme:
    tracer = get_tracer(__name__)
    async with _get_session_factory()() as session:
        with tracer.start_as_current_span("db.query.themes.load_theme"):
            result = await session.execute(
                select(DreamTheme).where(
                    DreamTheme.id == theme_id,
                    DreamTheme.dream_id == dream_id,
                    DreamTheme.deprecated.is_(False),
                )
            )
        theme = result.scalar_one_or_none()

        if theme is None:
            raise HTTPException(status_code=404, detail="Theme not found")
        if theme.status != "draft":
            raise HTTPException(status_code=409, detail="Theme must be draft before curation")

        session.add(
            build_dream_theme_transition_version(
                theme=theme,
                to_status=to_status,
                changed_by="user",
            )
        )
        with tracer.start_as_current_span("db.query.themes.flush_annotation_version"):
            await session.flush()

        theme.status = to_status
        with tracer.start_as_current_span("db.query.themes.commit_transition"):
            await session.commit()
        return theme


async def _confirm_draft_themes(dream_ids: list[uuid.UUID]) -> int:
    if not dream_ids:
        return 0

    tracer = get_tracer(__name__)
    async with _get_session_factory()() as session:
        with tracer.start_as_current_span("db.query.themes.load_bulk_confirm"):
            result = await session.execute(
                select(DreamTheme).where(
                    DreamTheme.dream_id.in_(dream_ids),
                    DreamTheme.status == "draft",
                    DreamTheme.deprecated.is_(False),
                )
            )
        themes = list(result.scalars().all())

        for theme in themes:
            session.add(
                build_dream_theme_transition_version(
                    theme=theme,
                    to_status="confirmed",
                    changed_by="user",
                )
            )

        if themes:
            with tracer.start_as_current_span("db.query.themes.flush_bulk_annotation_versions"):
                await session.flush()

        for theme in themes:
            theme.status = "confirmed"

        with tracer.start_as_current_span("db.query.themes.commit_bulk_confirm"):
            await session.commit()
        return len(themes)


def _bulk_confirm_key(token: str) -> str:
    return f"bulk_confirm:{token}"


@lru_cache(maxsize=1)
def _get_redis_client():
    from redis import asyncio as redis_asyncio

    return redis_asyncio.from_url(get_settings().REDIS_URL, decode_responses=True)
