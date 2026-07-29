from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache

from fastapi import APIRouter, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.shared.config import get_settings
from app.shared.tracing import get_logger, get_tracer

router = APIRouter()
logger = get_logger(__name__)


class HealthResponse(BaseModel):
    status: str
    index_last_updated: str | None = None
    unindexed_dreams: int | None = None
    unindexed_notes: int | None = None


@dataclass(frozen=True)
class IndexHealthSnapshot:
    index_last_updated: datetime | None
    unindexed_dreams: int
    unindexed_notes: int


@router.get("/health", response_model=HealthResponse)
async def health(response: Response) -> HealthResponse:
    # Public endpoint by design: GET /health is intentionally unauthenticated per
    # IMPLEMENTATION_CONTRACT OBS-3.
    snapshot = await _fetch_index_health_snapshot()
    if snapshot is None:
        response.status_code = 503
        return HealthResponse(status="degraded", index_last_updated=None)

    has_backlog = snapshot.unindexed_dreams > 0 or snapshot.unindexed_notes > 0
    if has_backlog:
        response.status_code = 503

    return HealthResponse(
        status="degraded" if has_backlog else "ok",
        index_last_updated=(
            snapshot.index_last_updated.isoformat() if snapshot.index_last_updated else None
        ),
        unindexed_dreams=snapshot.unindexed_dreams,
        unindexed_notes=snapshot.unindexed_notes,
    )


@lru_cache(maxsize=1)
def _get_engine() -> AsyncEngine:
    return create_async_engine(get_settings().DATABASE_URL)


async def _fetch_index_health_snapshot() -> IndexHealthSnapshot | None:
    tracer = get_tracer(__name__)
    statement = text(
        """
        SELECT
            (
                SELECT MAX(created_at)
                FROM dream_chunks
            ) AS index_last_updated,
            (
                SELECT COUNT(*)
                FROM dream_entries AS dream
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM dream_chunks AS chunk
                    WHERE chunk.dream_id = dream.id
                      AND chunk.source_kind = 'dream_text'
                )
            ) AS unindexed_dreams,
            (
                SELECT COUNT(*)
                FROM dream_notes AS note
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM dream_chunks AS chunk
                    WHERE chunk.note_id = note.id
                      AND chunk.source_kind = 'note'
                )
            ) AS unindexed_notes
        """
    )

    try:
        async with _get_engine().connect() as connection:
            with tracer.start_as_current_span("db.query.health.fetch_index_health_snapshot"):
                result = await connection.execute(statement)
                row = result.mappings().one()
                return IndexHealthSnapshot(
                    index_last_updated=row["index_last_updated"],
                    unindexed_dreams=int(row["unindexed_dreams"] or 0),
                    unindexed_notes=int(row["unindexed_notes"] or 0),
                )
    except Exception:
        logger.warning("health.fetch_index_health_snapshot failed", exc_info=True)
        return None
