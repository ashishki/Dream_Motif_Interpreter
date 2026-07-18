from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.shared.tracing import get_logger
from app.workers.index import index_dream

logger = get_logger(__name__)


async def index_capture_best_effort(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    dream_id: uuid.UUID,
) -> int:
    """Index a captured dream without turning an embedding outage into data loss.

    The current AssistantFacade removes a newly committed dream when its injected
    indexing callable raises. Capture runtimes therefore use this boundary: a
    temporary semantic-index failure returns zero indexed chunks, keeps the dream,
    and lets the existing sync/reindex pipeline repair searchability later.
    """
    try:
        return await index_dream(
            {"session_factory": session_factory},
            dream_id=dream_id,
        )
    except Exception:
        logger.warning("capture.semantic_index_deferred", dream_id=str(dream_id))
        return 0
