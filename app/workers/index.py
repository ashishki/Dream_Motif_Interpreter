from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.retrieval.ingestion import RagIngestionService


async def index_dream(ctx: dict[str, Any], *, dream_id: uuid.UUID) -> int:
    session_factory: async_sessionmaker[AsyncSession] = ctx["session_factory"]
    embedding_client = ctx.get("embedding_client")
    service = RagIngestionService(
        session_factory=session_factory,
        embedding_client=embedding_client,
    )
    return await service.index_dream(dream_id)


class WorkerSettings:
    functions = [index_dream]
