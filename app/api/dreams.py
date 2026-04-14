from __future__ import annotations

import asyncio
import hmac
import json
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.dream import DreamEntry
from app.models.theme import DreamTheme
from app.services.gdocs_client import GDocsClient
from app.shared.config import get_settings
from app.shared.database import get_session_factory
from app.shared.tracing import get_logger, get_tracer

router = APIRouter()
logger = get_logger(__name__)


class _InMemoryRedisClient:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        del ex
        self._values[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self._values.get(key)

    async def aclose(self) -> None:
        return None


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


class JobEnqueuer(Protocol):
    async def enqueue_ingest(self, *, job_id: uuid.UUID, doc_id: str) -> None: ...


class RedisSyncBackend:
    def __init__(self, *, redis_client: Any, job_enqueuer: JobEnqueuer, doc_id: str) -> None:
        self._redis_client = redis_client
        self._job_enqueuer = job_enqueuer
        self._doc_id = doc_id

    async def enqueue_sync(self) -> uuid.UUID:
        job_id = uuid.uuid4()
        await write_sync_job_state(self._redis_client, job_id, SyncJobState(status="queued"))
        await self._job_enqueuer.enqueue_ingest(job_id=job_id, doc_id=self._doc_id)
        return job_id

    async def get_status(self, job_id: uuid.UUID) -> SyncJobState | None:
        return await read_sync_job_state(self._redis_client, job_id)


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

    async with get_session_factory()() as session:
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

    async with get_session_factory()() as session:
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
def _get_sync_backend() -> SyncBackend:
    return RedisSyncBackend(
        redis_client=_get_redis_client(),
        job_enqueuer=_get_job_enqueuer(),
        doc_id=get_settings().GOOGLE_DOC_ID,
    )


async def write_sync_job_state(redis_client: Any, job_id: uuid.UUID, state: SyncJobState) -> None:
    tracer = get_tracer(__name__)
    payload = {"status": state.status, "new_entries": state.new_entries}
    with tracer.start_as_current_span("redis.sync_job.set") as span:
        span.set_attribute("job_id", str(job_id))
        span.set_attribute("status", state.status)
        await redis_client.set(_sync_job_key(job_id), json.dumps(payload))


async def read_sync_job_state(redis_client: Any, job_id: uuid.UUID) -> SyncJobState | None:
    tracer = get_tracer(__name__)
    with tracer.start_as_current_span("redis.sync_job.get") as span:
        span.set_attribute("job_id", str(job_id))
        payload = await redis_client.get(_sync_job_key(job_id))

    if payload is None:
        return None

    data = json.loads(payload)
    return SyncJobState(
        status=str(data["status"]),
        new_entries=data.get("new_entries"),
    )


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


class LocalAsyncJobEnqueuer:
    def __init__(
        self,
        *,
        redis_client: Any,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._redis_client = redis_client
        self._session_factory = session_factory
        self._tasks: set[asyncio.Task[None]] = set()

    async def enqueue_ingest(self, *, job_id: uuid.UUID, doc_id: str) -> None:
        from app.workers.ingest import ingest_document

        task = asyncio.create_task(
            self._run_ingest_job(job_id=job_id, doc_id=doc_id, ingest_document=ingest_document)
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_ingest_job(self, *, job_id: uuid.UUID, doc_id: str, ingest_document) -> None:
        try:
            await ingest_document(
                {
                    "redis": self._redis_client,
                    "session_factory": self._session_factory,
                    "gdocs_client": GDocsClient(),
                },
                job_id=job_id,
                doc_id=doc_id,
            )
        except Exception:
            logger.exception("sync.ingest_job_failed", job_id=str(job_id))


@lru_cache(maxsize=1)
def _get_job_enqueuer() -> JobEnqueuer:
    return LocalAsyncJobEnqueuer(
        redis_client=_get_redis_client(),
        session_factory=get_session_factory(),
    )


_REDIS_CLIENT: Any | None = None


def _build_redis_client():
    try:
        from redis import asyncio as redis_asyncio
    except ModuleNotFoundError:
        logger.warning("sync.redis_client_unavailable_falling_back_to_memory")
        return _InMemoryRedisClient()

    return redis_asyncio.from_url(get_settings().REDIS_URL, decode_responses=True)


def _get_redis_client():
    global _REDIS_CLIENT
    if _REDIS_CLIENT is None:
        _REDIS_CLIENT = _build_redis_client()
    return _REDIS_CLIENT


def _sync_job_key(job_id: uuid.UUID) -> str:
    return f"sync_job:{job_id}"
