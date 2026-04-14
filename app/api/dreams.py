from __future__ import annotations

import hmac
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.models.dream import DreamEntry
from app.models.theme import DreamTheme
from app.shared.config import get_settings
from app.shared.tracing import get_tracer

router = APIRouter()


class DreamListItem(BaseModel):
    id: uuid.UUID
    date: str | None
    title: str
    word_count: int
    source_doc_id: str
    created_at: str


class DreamsPageResponse(BaseModel):
    items: list[DreamListItem]
    total: int
    page: int


class DreamMetadata(BaseModel):
    segmentation_confidence: str
    theme_count: int


class DreamDetailResponse(BaseModel):
    id: uuid.UUID
    date: str | None
    title: str
    raw_text: str
    word_count: int
    source_doc_id: str
    created_at: str
    metadata: DreamMetadata


class SyncQueuedResponse(BaseModel):
    job_id: uuid.UUID
    status: str


class SyncJobStatusResponse(BaseModel):
    job_id: uuid.UUID
    status: str
    new_entries: int | None = None


@dataclass(frozen=True)
class SyncJobState:
    status: str
    new_entries: int | None = None


class SyncBackend(Protocol):
    async def enqueue_sync(self) -> uuid.UUID: ...

    async def get_status(self, job_id: uuid.UUID) -> SyncJobState | None: ...


class InMemorySyncBackend:
    def __init__(self) -> None:
        self._jobs: dict[uuid.UUID, SyncJobState] = {}

    async def enqueue_sync(self) -> uuid.UUID:
        job_id = uuid.uuid4()
        self._jobs[job_id] = SyncJobState(status="queued")
        return job_id

    async def get_status(self, job_id: uuid.UUID) -> SyncJobState | None:
        return self._jobs.get(job_id)


@router.post("/sync", response_model=SyncQueuedResponse, status_code=202)
async def post_sync(response: Response) -> SyncQueuedResponse:
    del response
    job_id = await _get_sync_backend().enqueue_sync()
    return SyncQueuedResponse(job_id=job_id, status="queued")


@router.get("/sync/{job_id}", response_model=SyncJobStatusResponse)
async def get_sync_status(job_id: uuid.UUID) -> SyncJobStatusResponse:
    job_state = await _get_sync_backend().get_status(job_id)
    if job_state is None:
        raise HTTPException(status_code=404, detail="Sync job not found")

    return SyncJobStatusResponse(
        job_id=job_id,
        status=job_state.status,
        new_entries=job_state.new_entries,
    )


@router.get("/dreams", response_model=DreamsPageResponse)
async def list_dreams(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> DreamsPageResponse:
    tracer = get_tracer(__name__)
    offset = (page - 1) * page_size

    async with _get_session_factory()() as session:
        with tracer.start_as_current_span("db.query.dreams.list.total"):
            total = await session.scalar(select(func.count()).select_from(DreamEntry))

        with tracer.start_as_current_span("db.query.dreams.list.page"):
            result = await session.execute(
                select(DreamEntry)
                .order_by(DreamEntry.date.desc(), DreamEntry.created_at.desc())
                .offset(offset)
                .limit(page_size)
            )

    items = [
        DreamListItem(
            id=dream.id,
            date=dream.date.isoformat() if dream.date is not None else None,
            title=dream.title,
            word_count=dream.word_count,
            source_doc_id=dream.source_doc_id,
            created_at=dream.created_at.isoformat(),
        )
        for dream in result.scalars().all()
    ]
    return DreamsPageResponse(items=items, total=total or 0, page=page)


@router.get("/dreams/{dream_id}", response_model=DreamDetailResponse)
async def get_dream(dream_id: uuid.UUID) -> DreamDetailResponse:
    tracer = get_tracer(__name__)

    async with _get_session_factory()() as session:
        dream = await _load_dream(session, dream_id, tracer=tracer)
        theme_count = await _count_themes(session, dream_id, tracer=tracer)

    return DreamDetailResponse(
        id=dream.id,
        date=dream.date.isoformat() if dream.date is not None else None,
        title=dream.title,
        raw_text=dream.raw_text,
        word_count=dream.word_count,
        source_doc_id=dream.source_doc_id,
        created_at=dream.created_at.isoformat(),
        metadata=DreamMetadata(
            segmentation_confidence=dream.segmentation_confidence,
            theme_count=theme_count,
        ),
    )


@lru_cache(maxsize=1)
def _get_engine() -> AsyncEngine:
    return create_async_engine(get_settings().DATABASE_URL)


@lru_cache(maxsize=1)
def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(_get_engine(), expire_on_commit=False)


@lru_cache(maxsize=1)
def _get_sync_backend() -> SyncBackend:
    return InMemorySyncBackend()


async def _load_dream(
    session: AsyncSession,
    dream_id: uuid.UUID,
    *,
    tracer,
) -> DreamEntry:
    with tracer.start_as_current_span("db.query.dreams.get"):
        dream = await session.get(DreamEntry, dream_id)

    if dream is None:
        raise HTTPException(status_code=404, detail="Dream not found")
    return dream


async def _count_themes(session: AsyncSession, dream_id: uuid.UUID, *, tracer) -> int:
    with tracer.start_as_current_span("db.query.dreams.theme_count"):
        theme_count = await session.scalar(
            select(func.count())
            .select_from(DreamTheme)
            .where(DreamTheme.dream_id == dream_id, DreamTheme.deprecated.is_(False))
        )
    return theme_count or 0


def is_valid_api_key(api_key: str | None) -> bool:
    if api_key is None:
        return False
    return hmac.compare_digest(api_key, get_settings().SECRET_KEY)
