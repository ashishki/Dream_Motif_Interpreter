from __future__ import annotations

from datetime import datetime, timedelta, timezone
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


@router.get("/health", response_model=HealthResponse)
async def health(response: Response) -> HealthResponse:
    # Public endpoint by design: GET /health is intentionally unauthenticated per
    # IMPLEMENTATION_CONTRACT OBS-3.
    index_last_updated = await _fetch_index_last_updated()
    if index_last_updated is None:
        return HealthResponse(status="ok", index_last_updated=None)

    stale_after = timedelta(hours=get_settings().MAX_INDEX_AGE_HOURS)
    is_stale = datetime.now(timezone.utc) - index_last_updated > stale_after
    if is_stale:
        response.status_code = 503

    return HealthResponse(
        status="ok" if not is_stale else "degraded",
        index_last_updated=index_last_updated.isoformat(),
    )


@lru_cache(maxsize=1)
def _get_engine() -> AsyncEngine:
    return create_async_engine(get_settings().DATABASE_URL)


async def _fetch_index_last_updated() -> datetime | None:
    tracer = get_tracer(__name__)
    statement = text(
        """
        SELECT MAX(created_at) AS index_last_updated
        FROM dream_chunks
        """
    )

    try:
        async with _get_engine().connect() as connection:
            with tracer.start_as_current_span("db.query.health.fetch_index_last_updated"):
                return await connection.scalar(statement)
    except Exception:
        logger.warning("health.fetch_index_last_updated failed", exc_info=True)
        return None
