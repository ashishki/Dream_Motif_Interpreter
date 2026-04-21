from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.retrieval.ingestion import RagIngestionService
from app.shared.tracing import get_tracer


def build_index_service(ctx: dict[str, Any]) -> RagIngestionService:
    session_factory: async_sessionmaker[AsyncSession] = ctx["session_factory"]
    embedding_client = ctx.get("embedding_client")
    return RagIngestionService(
        session_factory=session_factory,
        embedding_client=embedding_client,
    )


async def index_dream(ctx: dict[str, Any], *, dream_id: uuid.UUID) -> int:
    tracer = get_tracer(__name__)
    service = build_index_service(ctx)
    with tracer.start_as_current_span("worker.index_dream") as span:
        span.set_attribute("dream_id", str(dream_id))
        return await service.index_dream(dream_id)


class WorkerSettings:
    functions = [index_dream]
