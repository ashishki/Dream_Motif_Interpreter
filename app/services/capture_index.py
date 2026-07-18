from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.shared.tracing import get_logger
from app.workers.index import index_dream

logger = get_logger(__name__)


async def index_capture_best_effort(
    dream_id: uuid.UUID,
    *,
    session_factory: async_sessionmaker[AsyncSession],
) -> int:
    """Index a captured dream without turning an embedding outage into data loss.

    AssistantFacade calls its injected indexer with the dream ID as a positional
    argument. Capture runtimes bind only the session factory and keep that call
    contract while converting a temporary provider failure into deferred indexing.
    """
    try:
        return await index_dream(
            {"session_factory": session_factory},
            dream_id=dream_id,
        )
    except Exception:
        logger.warning("capture.semantic_index_deferred", dream_id=str(dream_id))
        return 0
