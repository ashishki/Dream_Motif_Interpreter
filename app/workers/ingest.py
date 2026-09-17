from __future__ import annotations

import asyncio
import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import httpx
from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.dreams import SyncJobState, get_and_delete_sync_notify, write_sync_job_state
from app.models.dream import DreamChunk, DreamEntry
from app.models.note import DreamNote
from app.models.processing import DreamProcessingJob, NoteProcessingJob
from app.models.theme import DreamTheme
from app.models.write_status import DreamWriteStatus
from app.retrieval.ingestion import (
    ValidatedDreamEntry,
    fetch_source_documents,
    process_source_document,
)
from app.retrieval.types import FetchedSourceDocument, SourceConnector
from app.services.analysis import AnalysisService
from app.services.gdocs_client import GDocsAuthError, GDocsClient
from app.services.motif_service import MotifService
from app.shared.config import get_doc_name, get_settings
from app.shared.tracing import get_logger, get_tracer
from app.workers.index import index_dream

logger = get_logger(__name__)


class SupportsFetchDocument(Protocol):
    def fetch_document(self, document_id: str | None = None) -> list[str]: ...


@dataclass(frozen=True)
class StoredDreamEntries:
    new_entries: int
    dream_ids: list[uuid.UUID]


@dataclass(frozen=True)
class PipelineTarget:
    dream_id: uuid.UUID
    needs_analysis: bool
    needs_indexing: bool


class SourceDreamConflictError(RuntimeError):
    """An external entry changed identity/content and needs operator review."""


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
                paragraphs = await asyncio.to_thread(gdocs_client.fetch_document, doc_id)
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
            await _notify_sync_complete(
                redis_client,
                job_id,
                count=0,
                doc_id=doc_id,
                error="Ошибка аутентификации Google Docs",
            )
            return 0
        except SourceDreamConflictError:
            logger.warning(
                "worker.ingest_document_source_conflict",
                job_id=str(job_id),
                doc_id=doc_id,
                exc_info=True,
            )
            await write_sync_job_state(redis_client, job_id, SyncJobState(status="failed"))
            await _notify_sync_complete(
                redis_client,
                job_id,
                count=0,
                doc_id=doc_id,
                error=(
                    "обнаружена неоднозначная правка текста сна; "
                    "архив не изменён, нужна ручная проверка"
                ),
            )
            return 0
        except Exception:
            await write_sync_job_state(redis_client, job_id, SyncJobState(status="failed"))
            await _notify_sync_complete(
                redis_client,
                job_id,
                count=0,
                doc_id=doc_id,
                error="Внутренняя ошибка",
            )
            raise

    await write_sync_job_state(
        redis_client,
        job_id,
        SyncJobState(status="done", new_entries=stored_entries.new_entries),
    )
    await _notify_sync_complete(
        redis_client,
        job_id,
        count=stored_entries.new_entries,
        doc_id=doc_id,
        error=None,
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

    try:
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
    except GDocsAuthError:
        await write_sync_job_state(redis_client, job_id, SyncJobState(status="failed"))
        await _notify_sync_complete(
            redis_client,
            job_id,
            count=0,
            doc_id=client_id,
            error="Ошибка аутентификации Google Docs",
        )
        return 0
    except SourceDreamConflictError:
        logger.warning(
            "worker.ingest_source_container_conflict",
            job_id=str(job_id),
            client_id=client_id,
            exc_info=True,
        )
        await write_sync_job_state(redis_client, job_id, SyncJobState(status="failed"))
        await _notify_sync_complete(
            redis_client,
            job_id,
            count=0,
            doc_id=client_id,
            error=(
                "обнаружена неоднозначная правка текста сна; "
                "архив не изменён, нужна ручная проверка"
            ),
        )
        return 0
    except Exception:
        await write_sync_job_state(redis_client, job_id, SyncJobState(status="failed"))
        await _notify_sync_complete(
            redis_client,
            job_id,
            count=0,
            doc_id=client_id,
            error="Внутренняя ошибка",
        )
        raise

    await write_sync_job_state(
        redis_client,
        job_id,
        SyncJobState(status="done", new_entries=total_new_entries),
    )
    await _notify_sync_complete(
        redis_client,
        job_id,
        count=total_new_entries,
        doc_id=client_id,
        error=None,
    )
    return total_new_entries


async def _notify_sync_complete(
    redis_client: Any,
    job_id: uuid.UUID,
    *,
    count: int,
    doc_id: str,
    error: str | None,
) -> None:
    tracer = get_tracer(__name__)
    try:
        chat_id = await get_and_delete_sync_notify(redis_client, job_id)
        if chat_id is None:
            return

        settings = get_settings()
        if not settings.TELEGRAM_BOT_TOKEN:
            return

        doc_label = get_doc_name(doc_id)
        if error is None:
            if count == 0:
                text = (
                    f"Синхронизация «{doc_label}» завершена. Новых снов не найдено. "
                    "Если вы точно добавляли новые сны, возможно, бот не распознал их формат."
                )
            else:
                text = (
                    f"Готово: добавлено {count} новых снов из «{doc_label}». Можно с ними работать."
                )
        else:
            text = (
                f"Синхронизация «{doc_label}» не удалась: {error}. "
                "Новые сны из этого документа пока могут не находиться."
            )

        with tracer.start_as_current_span("http.telegram.send_sync_notification") as span:
            span.set_attribute("job_id", str(job_id))
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={"chat_id": chat_id, "text": text},
                )
                response.raise_for_status()
    except Exception:
        logger.warning("ingest.sync_notify_failed", job_id=str(job_id), exc_info=True)


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
    keyed_entries: list[tuple[ValidatedDreamEntry, str]] = []
    heading_occurrences: dict[str, int] = {}
    for entry in pipeline.validated_entries:
        heading_signature = _source_heading_signature(entry)
        heading_occurrence = heading_occurrences.get(heading_signature, 0)
        heading_occurrences[heading_signature] = heading_occurrence + 1
        keyed_entries.append(
            (
                entry,
                _build_source_entry_key(
                    fetched_document.external_id,
                    heading_signature,
                    heading_occurrence,
                ),
            )
        )
    incoming_source_keys = {source_key for _entry, source_key in keyed_entries}

    async with session_factory() as session:
        for entry, source_entry_key in keyed_entries:
            source_identity_dream = await _load_dream_by_source_entry_key(
                session=session,
                source_entry_key=source_entry_key,
            )
            if source_identity_dream is not None:
                if source_identity_dream.content_hash != entry.content_hash:
                    raise SourceDreamConflictError(
                        "Google Docs entry changed at a previously ingested source position"
                    )
                _apply_google_doc_metadata(
                    source_identity_dream,
                    entry,
                    source_entry_key=source_entry_key,
                )
                if fetched_document.source_type == "google_doc":
                    await _mark_google_doc_presence(
                        session=session,
                        dream_id=source_identity_dream.id,
                        target_doc_id=fetched_document.external_id,
                    )
                dream_ids.append(source_identity_dream.id)
                for note_text in entry.notes:
                    await _upsert_dream_note(
                        session=session,
                        dream_id=source_identity_dream.id,
                        note_text=note_text,
                        source="google_doc",
                    )
                continue

            existing_dream = await _load_renamed_source_dream(
                session=session,
                source_doc_id=fetched_document.external_id,
                content_hash=entry.content_hash,
                incoming_source_keys=incoming_source_keys,
            )
            if existing_dream is None and await _has_disappeared_source_slot(
                session=session,
                source_doc_id=fetched_document.external_id,
                incoming_source_keys=incoming_source_keys,
            ):
                # An unknown heading and unknown body while a previously-known
                # slot disappeared is indistinguishable from a combined
                # heading+body edit.  Never turn it into a second dream.
                raise SourceDreamConflictError(
                    "Google Docs entry changed both heading identity and body"
                )
            if existing_dream is None:
                existing_dream = await _load_adoptable_telegram_dream(
                    session=session,
                    content_hash=entry.content_hash,
                )
            if existing_dream is not None:
                _apply_google_doc_metadata(
                    existing_dream,
                    entry,
                    source_entry_key=source_entry_key,
                )
                if fetched_document.source_type == "google_doc":
                    await _mark_google_doc_presence(
                        session=session,
                        dream_id=existing_dream.id,
                        target_doc_id=fetched_document.external_id,
                    )
                dream_ids.append(existing_dream.id)
                for note_text in entry.notes:
                    await _upsert_dream_note(
                        session=session,
                        dream_id=existing_dream.id,
                        note_text=note_text,
                        source="google_doc",
                    )
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
                    source_entry_key=source_entry_key,
                    segmentation_confidence=entry.segmentation_confidence,
                    parser_profile=entry.applied_profile,
                    parse_warnings=entry.parse_warnings,
                )
                .on_conflict_do_nothing(index_elements=[DreamEntry.source_entry_key])
                .returning(DreamEntry.id)
            )
            with tracer.start_as_current_span("db.query.worker_ingest.upsert_dream_entry"):
                result = await session.execute(statement)
            dream_id = result.scalar_one_or_none()
            inserted = dream_id is not None
            if dream_id is None:
                existing_dream = await _load_dream_by_source_entry_key(
                    session=session,
                    source_entry_key=source_entry_key,
                )
                if existing_dream is not None:
                    if existing_dream.content_hash != entry.content_hash:
                        raise SourceDreamConflictError(
                            "Concurrent source slot contains different dream text"
                        )
                    _apply_google_doc_metadata(
                        existing_dream,
                        entry,
                        source_entry_key=source_entry_key,
                    )
                    dream_id = existing_dream.id
            if dream_id is None:
                raise ValueError("Stored dream entry could not be resolved after upsert")

            dream_ids.append(dream_id)
            if inserted:
                inserted_rows += 1
            if fetched_document.source_type == "google_doc":
                await _mark_google_doc_presence(
                    session=session,
                    dream_id=dream_id,
                    target_doc_id=fetched_document.external_id,
                )
            for note_text in entry.notes:
                await _upsert_dream_note(
                    session=session,
                    dream_id=dream_id,
                    note_text=note_text,
                    source="google_doc",
                )

        with tracer.start_as_current_span("db.query.worker_ingest.commit"):
            await session.commit()

    return StoredDreamEntries(new_entries=inserted_rows, dream_ids=dream_ids)


async def _load_renamed_source_dream(
    *,
    session: AsyncSession,
    source_doc_id: str,
    content_hash: str,
    incoming_source_keys: set[str],
) -> DreamEntry | None:
    with get_tracer(__name__).start_as_current_span(
        "db.query.worker_ingest.load_renamed_source_dream"
    ) as span:
        span.set_attribute("source_doc_id", source_doc_id)
        stmt = select(DreamEntry).where(
            DreamEntry.source_doc_id == source_doc_id,
            DreamEntry.content_hash == content_hash,
        )
        if incoming_source_keys:
            stmt = stmt.where(
                or_(
                    DreamEntry.source_entry_key.is_(None),
                    DreamEntry.source_entry_key.not_in(incoming_source_keys),
                )
            )
        rows = list((await session.execute(stmt.limit(2).with_for_update())).scalars().all())
    if len(rows) > 1:
        raise SourceDreamConflictError("Multiple prior source slots match a renamed dream body")
    return rows[0] if rows else None


async def _load_adoptable_telegram_dream(
    *,
    session: AsyncSession,
    content_hash: str,
) -> DreamEntry | None:
    with get_tracer(__name__).start_as_current_span(
        "db.query.worker_ingest.load_adoptable_telegram_dream"
    ):
        result = await session.execute(
            select(DreamEntry)
            .where(
                DreamEntry.content_hash == content_hash,
                DreamEntry.source_entry_key.is_(None),
                DreamEntry.source_doc_id.like("telegram:%"),
            )
            .limit(2)
            .with_for_update()
        )
        rows = list(result.scalars().all())
    if len(rows) > 1:
        logger.warning(
            "worker.ingest_document_ambiguous_telegram_adoption",
            matching_rows=len(rows),
        )
        return None
    return rows[0] if rows else None


async def _has_disappeared_source_slot(
    *,
    session: AsyncSession,
    source_doc_id: str,
    incoming_source_keys: set[str],
) -> bool:
    stmt = (
        select(DreamEntry.id)
        .where(
            DreamEntry.source_doc_id == source_doc_id,
            DreamEntry.source_entry_key.is_not(None),
        )
        .limit(1)
    )
    if incoming_source_keys:
        stmt = stmt.where(DreamEntry.source_entry_key.not_in(incoming_source_keys))
    return await session.scalar(stmt) is not None


async def _load_dream_by_source_entry_key(
    *,
    session: AsyncSession,
    source_entry_key: str,
) -> DreamEntry | None:
    with get_tracer(__name__).start_as_current_span(
        "db.query.worker_ingest.load_dream_by_source_entry_key"
    ):
        return await session.scalar(
            select(DreamEntry)
            .where(DreamEntry.source_entry_key == source_entry_key)
            .with_for_update()
        )


def _source_heading_signature(entry: ValidatedDreamEntry) -> str:
    normalized_title = " ".join(re.sub(r"[^0-9a-zа-яё]+", " ", entry.title.casefold()).split())
    date_value = entry.date.isoformat() if entry.date is not None else "unknown-date"
    return f"{date_value}:{normalized_title or 'untitled'}"


def _build_source_entry_key(
    source_doc_id: str,
    heading_signature: str,
    heading_occurrence: int,
) -> str:
    """Build a privacy-safe identity from heading plus same-heading occurrence.

    Unlike a global document ordinal, this survives unrelated inserts and
    reordering.  Repeated identical headings are deliberately numbered within
    that heading only; an ambiguous insert among them fails closed rather than
    silently duplicating a changed dream.
    """
    value = (
        f"google_doc:{source_doc_id}:heading:{heading_signature}:occurrence:{heading_occurrence}"
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _apply_google_doc_metadata(
    dream: DreamEntry,
    entry: ValidatedDreamEntry,
    *,
    source_entry_key: str,
) -> None:
    """Use Google Doc metadata as the latest heading/date for already-known text."""
    dream.source_doc_id = entry.source_doc_id
    dream.source_entry_key = source_entry_key
    dream.date = entry.date
    dream.title = entry.title
    dream.segmentation_confidence = entry.segmentation_confidence
    dream.parser_profile = entry.applied_profile
    dream.parse_warnings = list(entry.parse_warnings)


async def _mark_google_doc_presence(
    *,
    session: AsyncSession,
    dream_id: uuid.UUID,
    target_doc_id: str,
) -> None:
    """Record that this dream already exists in the authoritative document.

    This closes the race where a Telegram capture is discovered by ingest
    while its durable GDocs stage is still pending or running.  Clearing the
    worker token makes a stale owner fail its final compare-and-swap.
    """
    now = datetime.now(timezone.utc)
    receipt_result = await session.execute(
        insert(DreamWriteStatus)
        .values(
            id=uuid.uuid4(),
            dream_id=dream_id,
            target_doc_id=target_doc_id,
            status="succeeded",
            attempt_count=0,
            last_error=None,
            claim_token=None,
            updated_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_dream_write_statuses_dream_target",
            set_={
                "status": "succeeded",
                "last_error": None,
                "claim_token": None,
                "updated_at": now,
            },
            where=or_(
                DreamWriteStatus.status != "pending",
                DreamWriteStatus.updated_at < now - timedelta(minutes=10),
            ),
        )
        .returning(DreamWriteStatus.id)
    )
    if receipt_result.scalar_one_or_none() is None:
        # A fresh durable writer has already claimed this dream/document.
        # Roll the ingest transaction back via the caller's conflict path and
        # retry after that owner has finalized its external write.
        raise SourceDreamConflictError("Google Docs delivery is already in progress for this dream")
    await session.execute(
        update(DreamProcessingJob)
        .where(
            DreamProcessingJob.dream_id == dream_id,
            DreamProcessingJob.stage == "gdocs",
        )
        .values(
            status="succeeded",
            last_error=None,
            locked_at=None,
            lock_token=None,
            updated_at=now,
        )
    )


async def _upsert_dream_note(
    *,
    session: AsyncSession,
    dream_id: uuid.UUID,
    note_text: str,
    source: str,
) -> uuid.UUID | None:
    normalized_text = note_text.strip()
    if not normalized_text:
        return None
    content_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()

    existing_result = await session.execute(
        select(DreamNote.id, DreamChunk.id, DreamChunk.embedding)
        .outerjoin(DreamChunk, DreamChunk.note_id == DreamNote.id)
        .where(
            DreamNote.dream_id == dream_id,
            DreamNote.content_hash == content_hash,
        )
    )
    existing_row = existing_result.first()
    if existing_row is not None:
        existing_id, chunk_id, embedding = existing_row
        if chunk_id is not None and embedding is not None:
            return None

        # A Google-authored note must never be echoed back to Google Docs.  Its
        # semantic indexing is safe to retry, so persist only the index stage in
        # the same transaction as the note.  A previously succeeded job is
        # re-armed when its chunk is missing or contains a legacy NULL vector.
        await _ensure_imported_note_index_job(
            session=session,
            note_id=existing_id,
            repair_succeeded=True,
        )
        return existing_id

    note_id = uuid.uuid4()
    statement = (
        insert(DreamNote)
        .values(
            id=note_id,
            dream_id=dream_id,
            text=normalized_text,
            content_hash=content_hash,
            source=source,
        )
        .on_conflict_do_nothing(constraint="uq_dream_notes_dream_id_content_hash")
        .returning(DreamNote.id)
    )
    inserted_result = await session.execute(statement)
    inserted_id = inserted_result.scalar_one_or_none()
    if inserted_id is not None:
        await _ensure_imported_note_index_job(
            session=session,
            note_id=inserted_id,
            repair_succeeded=False,
        )
        return inserted_id

    # A concurrent ingest won the unique constraint.  It cannot have been
    # indexed before this transaction committed, so include it for repair.
    raced_id = await session.scalar(
        select(DreamNote.id).where(
            DreamNote.dream_id == dream_id,
            DreamNote.content_hash == content_hash,
        )
    )
    if raced_id is None:
        raise ValueError("Stored Google Docs note could not be resolved after upsert")
    await _ensure_imported_note_index_job(
        session=session,
        note_id=raced_id,
        repair_succeeded=False,
    )
    return raced_id


async def _ensure_imported_note_index_job(
    *,
    session: AsyncSession,
    note_id: uuid.UUID,
    repair_succeeded: bool,
) -> None:
    """Atomically enqueue the only safe stage for a Google-authored note.

    The source document is authoritative, so enqueueing a ``gdocs`` stage here
    would append the same note back into its source.  Index work is idempotent.
    Failed jobs retain their explicit-retry boundary; only a job that claimed
    success while its chunk is now absent/NULL is automatically repaired.
    """
    now = datetime.now(timezone.utc)
    statement = (
        insert(NoteProcessingJob)
        .values(
            id=uuid.uuid4(),
            note_id=note_id,
            stage="index",
            status="pending",
            attempt_count=0,
            last_error=None,
            available_at=now,
            locked_at=None,
            lock_token=None,
            target_doc_id=None,
            updated_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_note_processing_jobs_note_stage")
    )
    await session.execute(statement)
    if not repair_succeeded:
        return

    await session.execute(
        update(NoteProcessingJob)
        .where(
            NoteProcessingJob.note_id == note_id,
            NoteProcessingJob.stage == "index",
            NoteProcessingJob.status == "succeeded",
        )
        .values(
            status="retryable",
            attempt_count=0,
            last_error=None,
            available_at=now,
            locked_at=None,
            lock_token=None,
            updated_at=now,
        )
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
                select(DreamChunk.dream_id).where(
                    DreamChunk.dream_id.in_(dream_ids),
                    DreamChunk.source_kind == "dream_text",
                    DreamChunk.embedding.is_not(None),
                )
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
