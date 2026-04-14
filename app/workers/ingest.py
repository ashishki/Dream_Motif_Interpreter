from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.dreams import SyncJobState, write_sync_job_state
from app.models.dream import DreamEntry
from app.services.gdocs_client import GDocsAuthError, GDocsClient
from app.services.segmentation import segment_paragraphs
from app.shared.tracing import get_logger, get_tracer

logger = get_logger(__name__)


class SupportsFetchDocument(Protocol):
    def fetch_document(self) -> list[str]: ...


@dataclass(frozen=True)
class _FallbackSegmentDraft:
    date: date | None
    paragraphs: list[str]
    segmentation_confidence: str


async def ingest_document(ctx: dict[str, Any], *, job_id: uuid.UUID, doc_id: str) -> int:
    tracer = get_tracer(__name__)
    redis_client = ctx["redis"]
    session_factory: async_sessionmaker[AsyncSession] = ctx["session_factory"]
    gdocs_client: SupportsFetchDocument = ctx.get("gdocs_client", GDocsClient())

    try:
        await write_sync_job_state(redis_client, job_id, SyncJobState(status="running"))
    except Exception:
        logger.warning(
            "ingest.redis_status_write_failed",
            job_id=str(job_id),
            exc_info=True,
        )

    with tracer.start_as_current_span("worker.ingest_document") as span:
        span.set_attribute("job_id", str(job_id))
        span.set_attribute("doc_id", doc_id)
        try:
            paragraphs = gdocs_client.fetch_document()
            new_entries = await _store_entries(
                session_factory=session_factory,
                paragraphs=paragraphs,
                doc_id=doc_id,
            )
        except GDocsAuthError:
            logger.warning("worker.ingest_document_auth_failed", job_id=str(job_id))
            await write_sync_job_state(redis_client, job_id, SyncJobState(status="failed"))
            return 0
        except Exception:
            await write_sync_job_state(redis_client, job_id, SyncJobState(status="failed"))
            raise

    await write_sync_job_state(
        redis_client,
        job_id,
        SyncJobState(status="done", new_entries=new_entries),
    )
    return new_entries


async def _store_entries(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    paragraphs: list[str],
    doc_id: str,
) -> int:
    tracer = get_tracer(__name__)
    entries = segment_paragraphs(paragraphs, llm_boundary_detector=_no_llm_boundary_detector)
    inserted_rows = 0

    async with session_factory() as session:
        for entry in entries:
            statement = (
                insert(DreamEntry)
                .values(
                    source_doc_id=doc_id,
                    date=entry.date,
                    title=entry.title,
                    raw_text=entry.raw_text,
                    word_count=entry.word_count,
                    content_hash=entry.content_hash,
                    segmentation_confidence=entry.segmentation_confidence,
                )
                .on_conflict_do_nothing(index_elements=[DreamEntry.content_hash])
                .returning(DreamEntry.id)
            )
            with tracer.start_as_current_span("db.query.worker_ingest.upsert_dream_entry"):
                result = await session.execute(statement)
            if result.scalar_one_or_none() is not None:
                inserted_rows += 1

        with tracer.start_as_current_span("db.query.worker_ingest.commit"):
            await session.commit()

    return inserted_rows


def _no_llm_boundary_detector(paragraphs: list[str]) -> list[_FallbackSegmentDraft]:
    return [
        _FallbackSegmentDraft(
            date=None,
            paragraphs=paragraphs,
            segmentation_confidence="low",
        )
    ]


class WorkerSettings:
    functions = [ingest_document]
