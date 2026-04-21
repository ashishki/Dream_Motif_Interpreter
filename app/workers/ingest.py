from __future__ import annotations

import uuid
from dataclasses import dataclass
import asyncio
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.dreams import SyncJobState, write_sync_job_state
from app.models.dream import DreamChunk, DreamEntry
from app.models.theme import DreamTheme
from app.retrieval.ingestion import fetch_source_documents, process_source_document
from app.retrieval.types import FetchedSourceDocument, SourceConnector
from app.services.analysis import AnalysisService
from app.services.gdocs_client import GDocsAuthError, GDocsClient
from app.services.motif_service import MotifService
from app.shared.config import get_settings
from app.shared.tracing import get_logger, get_tracer
from app.workers.index import index_dream

logger = get_logger(__name__)


class SupportsFetchDocument(Protocol):
    def fetch_document(self) -> list[str]: ...


@dataclass(frozen=True)
class StoredDreamEntries:
    new_entries: int
    dream_ids: list[uuid.UUID]


@dataclass(frozen=True)
class PipelineTarget:
    dream_id: uuid.UUID
    needs_analysis: bool
    needs_indexing: bool


async def ingest_document(ctx: dict[str, Any], *, job_id: uuid.UUID, doc_id: str) -> int:
    tracer = get_tracer(__name__)
    redis_client = ctx["redis"]
    session_factory: async_sessionmaker[AsyncSession] = ctx["session_factory"]
    gdocs_client: SupportsFetchDocument = ctx.get("gdocs_client", GDocsClient())
    analysis_service: AnalysisService = ctx.get("analysis_service") or AnalysisService()
    motif_service: MotifService = ctx.get("motif_service") or MotifService()

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
            with tracer.start_as_current_span("worker.ingest_document.fetch_source") as fetch_span:
                fetch_span.set_attribute("doc_id", doc_id)
                paragraphs = await asyncio.to_thread(gdocs_client.fetch_document)
            fetched_document = FetchedSourceDocument(
                source_type="google_doc",
                external_id=doc_id,
                title=doc_id,
                source_path=f"documents/{doc_id}",
                updated_at=None,
                raw_contents=paragraphs,
            )
            stored_entries = await _store_entries(
                session_factory=session_factory,
                fetched_document=fetched_document,
            )
            pipeline_targets = await _collect_pipeline_targets(
                session_factory=session_factory,
                dream_ids=stored_entries.dream_ids,
            )
            await _run_post_store_pipeline(
                ctx=ctx,
                session_factory=session_factory,
                analysis_service=analysis_service,
                motif_service=motif_service,
                pipeline_targets=pipeline_targets,
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
        SyncJobState(status="done", new_entries=stored_entries.new_entries),
    )
    return stored_entries.new_entries


async def ingest_source_container(
    ctx: dict[str, Any],
    *,
    job_id: uuid.UUID,
    connector: SourceConnector,
    client_id: str,
) -> int:
    tracer = get_tracer(__name__)
    redis_client = ctx["redis"]
    session_factory: async_sessionmaker[AsyncSession] = ctx["session_factory"]
    analysis_service: AnalysisService = ctx.get("analysis_service") or AnalysisService()
    motif_service: MotifService = ctx.get("motif_service") or MotifService()

    try:
        await write_sync_job_state(redis_client, job_id, SyncJobState(status="running"))
    except Exception:
        logger.warning(
            "ingest.redis_status_write_failed",
            job_id=str(job_id),
            exc_info=True,
        )

    with tracer.start_as_current_span("worker.ingest_source_container") as span:
        span.set_attribute("job_id", str(job_id))
        span.set_attribute("client_id", client_id)

        with tracer.start_as_current_span("worker.ingest_source_container.enumerate_documents"):
            fetched_documents = await asyncio.to_thread(fetch_source_documents, connector)

        total_new_entries = 0
        dream_ids: list[uuid.UUID] = []
        for fetched_document in fetched_documents:
            stored_entries = await _store_entries(
                session_factory=session_factory,
                fetched_document=fetched_document,
                client_id=client_id,
            )
            total_new_entries += stored_entries.new_entries
            dream_ids.extend(stored_entries.dream_ids)

        pipeline_targets = await _collect_pipeline_targets(
            session_factory=session_factory,
            dream_ids=dream_ids,
        )
        await _run_post_store_pipeline(
            ctx=ctx,
            session_factory=session_factory,
            analysis_service=analysis_service,
            motif_service=motif_service,
            pipeline_targets=pipeline_targets,
        )

    await write_sync_job_state(
        redis_client,
        job_id,
        SyncJobState(status="done", new_entries=total_new_entries),
    )
    return total_new_entries


async def _store_entries(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    fetched_document: FetchedSourceDocument | None = None,
    paragraphs: list[str] | None = None,
    doc_id: str | None = None,
    client_id: str = "default",
) -> StoredDreamEntries:
    tracer = get_tracer(__name__)
    if fetched_document is None:
        if paragraphs is None or doc_id is None:
            raise ValueError("Either fetched_document or paragraphs plus doc_id are required")
        fetched_document = FetchedSourceDocument(
            source_type="google_doc",
            external_id=doc_id,
            title=doc_id,
            source_path=f"documents/{doc_id}",
            updated_at=None,
            raw_contents=paragraphs,
        )

    with tracer.start_as_current_span(
        "worker.ingest_document.normalize_document"
    ) as normalize_span:
        normalize_span.set_attribute("external_id", fetched_document.external_id)
        pipeline = process_source_document(fetched_document, client_id=client_id)

    inserted_rows = 0
    dream_ids: list[uuid.UUID] = []

    async with session_factory() as session:
        for entry in pipeline.validated_entries:
            dream_id = await _load_existing_dream_id(
                session=session,
                source_doc_id=fetched_document.external_id,
                content_hash=entry.content_hash,
            )
            if dream_id is not None:
                dream_ids.append(dream_id)
                continue

            statement = (
                insert(DreamEntry)
                .values(
                    source_doc_id=entry.source_doc_id,
                    date=entry.date,
                    title=entry.title,
                    raw_text=entry.raw_text,
                    word_count=entry.word_count,
                    content_hash=entry.content_hash,
                    segmentation_confidence=entry.segmentation_confidence,
                    parser_profile=entry.applied_profile,
                    parse_warnings=entry.parse_warnings,
                )
                .on_conflict_do_nothing(index_elements=[DreamEntry.content_hash])
                .returning(DreamEntry.id)
            )
            with tracer.start_as_current_span("db.query.worker_ingest.upsert_dream_entry"):
                result = await session.execute(statement)
            dream_id = result.scalar_one_or_none()
            inserted = dream_id is not None
            if dream_id is None:
                dream_id = await _load_existing_dream_id(
                    session=session,
                    source_doc_id=fetched_document.external_id,
                    content_hash=entry.content_hash,
                    allow_cross_document_lookup=True,
                )
            if dream_id is None:
                raise ValueError("Stored dream entry could not be resolved after upsert")

            dream_ids.append(dream_id)
            if inserted:
                inserted_rows += 1

        with tracer.start_as_current_span("db.query.worker_ingest.commit"):
            await session.commit()

    return StoredDreamEntries(new_entries=inserted_rows, dream_ids=dream_ids)


async def _load_existing_dream_id(
    *,
    session: AsyncSession,
    source_doc_id: str,
    content_hash: str,
    allow_cross_document_lookup: bool = False,
) -> uuid.UUID | None:
    tracer = get_tracer(__name__)

    with tracer.start_as_current_span("db.query.worker_ingest.load_existing_dream_id") as span:
        span.set_attribute("source_doc_id", source_doc_id)
        existing_dream_id = await session.scalar(
            select(DreamEntry.id).where(
                DreamEntry.source_doc_id == source_doc_id,
                DreamEntry.content_hash == content_hash,
            )
        )

    if existing_dream_id is not None or not allow_cross_document_lookup:
        return existing_dream_id

    with tracer.start_as_current_span("db.query.worker_ingest.load_existing_dream_id_by_hash"):
        return await session.scalar(
            select(DreamEntry.id).where(DreamEntry.content_hash == content_hash)
        )


async def _collect_pipeline_targets(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    dream_ids: list[uuid.UUID],
) -> list[PipelineTarget]:
    if not dream_ids:
        return []

    tracer = get_tracer(__name__)
    async with session_factory() as session:
        with tracer.start_as_current_span("db.query.worker_ingest.load_theme_targets"):
            theme_result = await session.execute(
                select(DreamTheme.dream_id).where(DreamTheme.dream_id.in_(dream_ids))
            )
        with tracer.start_as_current_span("db.query.worker_ingest.load_chunk_targets"):
            chunk_result = await session.execute(
                select(DreamChunk.dream_id).where(DreamChunk.dream_id.in_(dream_ids))
            )

    dream_ids_with_themes = set(theme_result.scalars().all())
    dream_ids_with_chunks = set(chunk_result.scalars().all())
    return [
        PipelineTarget(
            dream_id=dream_id,
            needs_analysis=dream_id not in dream_ids_with_themes,
            needs_indexing=dream_id not in dream_ids_with_chunks,
        )
        for dream_id in dream_ids
        if dream_id not in dream_ids_with_themes or dream_id not in dream_ids_with_chunks
    ]


async def _run_post_store_pipeline(
    *,
    ctx: dict[str, Any],
    session_factory: async_sessionmaker[AsyncSession],
    analysis_service: AnalysisService,
    motif_service: MotifService,
    pipeline_targets: list[PipelineTarget],
) -> None:
    tracer = get_tracer(__name__)
    index_worker_ctx = {
        "session_factory": session_factory,
        "embedding_client": ctx.get("embedding_client"),
    }

    with tracer.start_as_current_span("worker.ingest_document.post_store_pipeline") as span:
        span.set_attribute("pipeline_target_count", len(pipeline_targets))
        for target in pipeline_targets:
            span.set_attribute("dream_id", str(target.dream_id))
            if target.needs_analysis:
                await analysis_service.analyse_dream_with_session_factory(
                    target.dream_id,
                    session_factory,
                )
            if target.needs_indexing:
                await index_dream(index_worker_ctx, dream_id=target.dream_id)
            if get_settings().MOTIF_INDUCTION_ENABLED:
                async with session_factory() as session:
                    dream_entry = await session.get(DreamEntry, target.dream_id)
                    if dream_entry is not None:
                        await motif_service.run(dream_entry, session)
                        with tracer.start_as_current_span(
                            "db.query.worker_ingest.commit_motif_inductions"
                        ):
                            await session.commit()


class WorkerSettings:
    functions = [ingest_document]
