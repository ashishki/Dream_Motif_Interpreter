from __future__ import annotations

import asyncio
import contextlib
import hashlib
import inspect
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.assistant.session import load_recent_dream_set
from app.llm.client import AnthropicLLMClient, LLMClientError
from app.models.dream import DreamEntry
from app.models.motif import MotifInduction
from app.models.note import DreamNote
from app.models.processing import DreamProcessingJob, NoteProcessingJob
from app.models.theme import DreamTheme, ThemeCategory
from app.models.write_status import DreamWriteStatus
from app.retrieval.query import EvidenceBlock, InsufficientEvidence, RagQueryService
from app.services.analysis import AnalysisService
from app.services.gdocs_client import GDocsClient, GDocsWriteError
from app.services.motif_service import MotifService
from app.services.patterns import CoOccurrencePattern, PatternService, RecurringPattern
from app.services.research_service import ResearchService
from app.services.versioning import VersioningService
from app.shared.config import get_settings
from app.shared.tracing import get_logger, get_tracer

logger = get_logger(__name__)
WEAK_SEARCH_RELEVANCE_THRESHOLD = 0.4
DREAM_PROCESSING_STAGES = ("index", "analysis", "motif", "gdocs")
NOTE_PROCESSING_STAGES = ("index", "gdocs")
WRITE_RECEIPT_STALE_AFTER = timedelta(minutes=10)


class DreamRecordingUnavailable(RuntimeError):
    """Legacy adapter error for an unrecoverable archive persistence failure."""


class DreamProcessingRetryable(RuntimeError):
    """Raised when a durable post-capture stage should be retried."""


class DreamProcessingLeaseLost(RuntimeError):
    """Raised when a stale worker no longer owns a processing job lease."""


class DreamIngressConflictError(RuntimeError):
    """Raised when one stable ingress event is replayed with different text."""


class NoteProcessingRetryable(RuntimeError):
    """Raised when a durable note stage should be retried."""


class NoteProcessingLeaseLost(RuntimeError):
    """Raised when a stale worker no longer owns a note processing lease."""


@dataclass(frozen=True)
class SearchResultItem:
    dream_id: uuid.UUID
    date: date | None
    title: str | None
    chunk_text: str
    relevance_score: float
    matched_fragments: list[dict[str, Any]]
    quote: str | None = None


@dataclass(frozen=True)
class SearchResult:
    items: list[SearchResultItem]
    insufficient_reason: str | None = None


@dataclass(frozen=True)
class DreamThemeItem:
    id: uuid.UUID
    category_id: uuid.UUID
    category_name: str
    salience: float
    status: str
    match_type: str
    fragments: list[dict[str, Any]]
    deprecated: bool
    created_at: str


@dataclass(frozen=True)
class DreamDetail:
    id: uuid.UUID
    date: str | None
    title: str
    raw_text: str
    word_count: int
    source_doc_id: str
    created_at: str
    segmentation_confidence: str
    themes: list[DreamThemeItem]
    notes: list[str]


@dataclass(frozen=True)
class DreamSummary:
    id: uuid.UUID
    date: str | None
    title: str
    raw_text_preview: str
    theme_names: list[str]


@dataclass(frozen=True)
class DreamTitleSearchResult:
    dream_id: uuid.UUID
    date: str | None
    title: str
    raw_text_preview: str


@dataclass(frozen=True)
class CreatedDreamItem:
    id: uuid.UUID
    date: str | None
    title: str
    word_count: int
    source_doc_id: str
    created_at: str
    created: bool
    written_to_google_doc: bool = False
    written_to_doc_name: str = ""
    semantic_index_status: str = "succeeded"
    processing_status: str = "succeeded"
    google_doc_write_status: str = "succeeded"
    processing_job_id: uuid.UUID | None = None
    processing_job_ids: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True)
class RecurringPatternItem:
    category_id: uuid.UUID
    name: str
    count: int
    percentage_of_dreams: float


@dataclass(frozen=True)
class CoOccurrencePatternItem:
    category_ids: tuple[uuid.UUID, uuid.UUID]
    count: int


@dataclass(frozen=True)
class PatternSummary:
    recurring: list[RecurringPatternItem]
    co_occurrence: list[CoOccurrencePatternItem]


@dataclass(frozen=True)
class ThemeHistoryEntry:
    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    snapshot: dict[str, Any]
    created_at: str


@dataclass(frozen=True)
class MotifInductionItem:
    id: uuid.UUID
    label: str
    rationale: str | None
    confidence: str | None
    status: str
    fragments: list[dict[str, Any]]
    model_version: str | None
    created_at: str


@dataclass(frozen=True)
class SyncJobRef:
    job_id: uuid.UUID
    status: str
    doc_id: str


@dataclass(frozen=True)
class ArchiveSyncStatus:
    doc_id: str
    status: str
    last_checked_at: str | None
    last_sync_started_at: str | None
    last_synced_at: str | None
    last_sync_job_id: str | None
    is_stale_running: bool = False
    last_sync_error: str | None = None
    last_added_count: int | None = None
    last_sync_stage: str | None = None


@dataclass(frozen=True)
class DreamInterpretationRequest:
    dream_id: uuid.UUID
    title: str
    prompt: str


@dataclass(frozen=True)
class DreamInterpretationResult:
    dream_id: uuid.UUID
    title: str
    text: str


@dataclass(frozen=True)
class DreamRecordingInput:
    raw_text: str
    title: str | None
    dream_date_hint: date | None = None


class SyncJobEnqueuer(Protocol):
    async def enqueue_ingest(
        self,
        *,
        job_id: uuid.UUID,
        doc_id: str,
        chat_id: int | None = None,
    ) -> None: ...


class AssistantFacade:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        rag_query_service: RagQueryService,
        pattern_service: type[PatternService] = PatternService,
        versioning_service: type[VersioningService] = VersioningService,
        sync_job_enqueuer: SyncJobEnqueuer | None = None,
        analysis_service: AnalysisService | None = None,
        research_service: ResearchService | None = None,
        index_dream_callable: Callable[[uuid.UUID], Awaitable[int]] | None = None,
        index_note_callable: Callable[[uuid.UUID], Awaitable[int]] | None = None,
        motif_service: MotifService | None = None,
        interpretation_llm_client: Any | None = None,
        title_llm_client: Any | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._rag_query_service = rag_query_service
        self._pattern_service = pattern_service
        self._versioning_service = versioning_service
        self._sync_job_enqueuer = sync_job_enqueuer
        self._analysis_service = analysis_service or AnalysisService()
        self._research_service = research_service or ResearchService()
        self._index_dream_callable = index_dream_callable or self._build_index_dream_callable()
        self._index_note_callable = index_note_callable or self._build_index_note_callable()
        self._motif_service = motif_service or MotifService()
        self._interpretation_llm_client = interpretation_llm_client or AnthropicLLMClient()
        self._title_llm_client = title_llm_client or self._interpretation_llm_client

    async def shutdown(self) -> None:
        """Release facade-owned runtime helpers without closing shared DB state."""
        shutdown = getattr(self._sync_job_enqueuer, "shutdown", None)
        if not callable(shutdown):
            return
        result = shutdown()
        if inspect.isawaitable(result):
            await result

    async def start_background_workers(self) -> None:
        """Start facade-owned durable recovery helpers after runtime validation."""
        start = getattr(self._sync_job_enqueuer, "start", None)
        if not callable(start):
            return
        result = start()
        if inspect.isawaitable(result) and not isinstance(result, asyncio.Task):
            await result

    async def search_dreams(self, query: str) -> SearchResult:
        result = await self._rag_query_service.retrieve(query)
        if isinstance(result, InsufficientEvidence):
            return SearchResult(items=[], insufficient_reason=result.reason)

        # Group multiple chunks per dream — one SearchResultItem per dream_id,
        # fragments joined with '\n---\n', highest relevance_score kept.
        grouped: dict[uuid.UUID, SearchResultItem] = {}
        for block in result:
            did = block.dream_id
            item = _search_result_item(block, query)
            if not _is_verified_search_item(item):
                continue
            if did not in grouped:
                grouped[did] = item
            else:
                existing = grouped[did]
                new_score = max(existing.relevance_score, item.relevance_score)
                new_text = existing.chunk_text + "\n---\n" + item.chunk_text
                new_fragments = existing.matched_fragments + item.matched_fragments
                grouped[did] = SearchResultItem(
                    dream_id=existing.dream_id,
                    date=existing.date,
                    title=existing.title,
                    chunk_text=new_text,
                    relevance_score=new_score,
                    matched_fragments=new_fragments,
                    quote=_extract_quote(new_text, query),
                )
        if not grouped:
            return SearchResult(
                items=[], insufficient_reason="No verified archive-backed matches found"
            )
        return SearchResult(items=list(grouped.values()))

    async def search_dreams_exact(self, query: str) -> list[SearchResultItem]:
        tracer = get_tracer(__name__)
        with tracer.start_as_current_span("assistant.search_dreams_exact"):
            rows = await self._rag_query_service.exact_search(query)
        return [_exact_result_item(row, query) for row in rows]

    async def get_dream(self, dream_id: uuid.UUID) -> DreamDetail | None:
        tracer = get_tracer(__name__)

        async with self._session_factory() as session:
            with tracer.start_as_current_span("assistant.get_dream.load_dream"):
                dream = await session.get(DreamEntry, dream_id)
            if dream is None:
                return None

            with tracer.start_as_current_span("assistant.get_dream.load_themes"):
                theme_result = await session.execute(
                    select(DreamTheme, ThemeCategory.name)
                    .join(ThemeCategory, ThemeCategory.id == DreamTheme.category_id)
                    .where(DreamTheme.dream_id == dream_id)
                    .order_by(DreamTheme.created_at.asc(), DreamTheme.id.asc())
                )
            with tracer.start_as_current_span("assistant.get_dream.load_notes"):
                notes_result = await session.execute(
                    select(DreamNote.text)
                    .where(DreamNote.dream_id == dream.id)
                    .order_by(DreamNote.created_at.asc(), DreamNote.id.asc())
                )
                notes = list(notes_result.scalars().all())

        return DreamDetail(
            id=dream.id,
            date=dream.date.isoformat() if dream.date is not None else None,
            title=dream.title,
            raw_text=dream.raw_text,
            word_count=dream.word_count,
            source_doc_id=dream.source_doc_id,
            created_at=dream.created_at.isoformat(),
            segmentation_confidence=dream.segmentation_confidence,
            themes=[
                _theme_item(theme=theme, category_name=category_name)
                for theme, category_name in theme_result.all()
            ],
            notes=notes,
        )

    async def list_recent_dreams(self, limit: int = 10) -> list[DreamSummary]:
        tracer = get_tracer(__name__)
        bounded_limit = max(1, limit)

        async with self._session_factory() as session:
            with tracer.start_as_current_span("assistant.list_recent_dreams"):
                result = await session.execute(
                    select(DreamEntry)
                    .order_by(
                        DreamEntry.date.desc(),
                        DreamEntry.created_at.desc(),
                    )
                    .limit(bounded_limit)
                )
                dreams = result.scalars().all()

                dream_ids = [dream.id for dream in dreams]
                theme_result = await session.execute(
                    select(DreamTheme.dream_id, ThemeCategory.name)
                    .join(ThemeCategory, ThemeCategory.id == DreamTheme.category_id)
                    .where(DreamTheme.dream_id.in_(dream_ids))
                )
                themes_by_dream: dict[uuid.UUID, list[str]] = {}
                for dream_id, theme_name in theme_result.all():
                    themes_by_dream.setdefault(dream_id, []).append(theme_name)

        return [
            _dream_summary_item(dream, theme_names=themes_by_dream.get(dream.id, []))
            for dream in dreams
        ]

    async def search_dreams_by_title(
        self, query: str, limit: int = 10, dream_date: date | None = None
    ) -> list[DreamTitleSearchResult]:
        normalized_query = _normalize_title_search(query)
        if not normalized_query:
            return []

        bounded_limit = max(1, min(limit, 50))
        title_pattern = f"%{_escape_like(query.strip())}%"
        normalized_title = func.lower(
            func.regexp_replace(DreamEntry.title, r"[^0-9A-Za-zА-Яа-яЁё]+", " ", "g")
        )
        tracer = get_tracer(__name__)

        async with self._session_factory() as session:
            with tracer.start_as_current_span("assistant.search_dreams_by_title"):
                stmt = select(DreamEntry).where(
                    or_(
                        DreamEntry.title.ilike(title_pattern, escape="\\"),
                        normalized_title.contains(normalized_query),
                    )
                )
                if dream_date is not None:
                    stmt = stmt.where(DreamEntry.date == dream_date)
                stmt = stmt.order_by(DreamEntry.date.desc(), DreamEntry.created_at.desc()).limit(
                    bounded_limit
                )
                result = await session.execute(stmt)
                dreams = result.scalars().all()

        return [
            DreamTitleSearchResult(
                dream_id=dream.id,
                date=dream.date.isoformat() if dream.date is not None else None,
                title=dream.title,
                raw_text_preview=(dream.raw_text or "")[:400],
            )
            for dream in sorted(
                dreams,
                key=lambda dream: _title_match_rank(dream.title, query),
            )
        ]

    async def get_patterns(self) -> PatternSummary:
        async with self._session_factory() as session:
            recurring = await self._pattern_service.list_recurring_patterns(session)
            co_occurrence = await self._pattern_service.list_co_occurrence_patterns(session)

        return PatternSummary(
            recurring=[_recurring_pattern_item(pattern) for pattern in recurring],
            co_occurrence=[_co_occurrence_pattern_item(pattern) for pattern in co_occurrence],
        )

    async def create_dream(
        self,
        raw_text: str,
        *,
        title: str | None = None,
        dream_date: date | None = None,
        chat_id: int | None = None,
        source_event_key: str | None = None,
    ) -> CreatedDreamItem:
        prepared_input = _prepare_dream_recording_input(raw_text, title=title)
        normalized_text = prepared_input.raw_text
        if not normalized_text:
            raise ValueError("Dream text must not be empty")

        resolved_dream_date = dream_date or prepared_input.dream_date_hint or _application_today()
        source_doc_id = f"telegram:{chat_id}" if chat_id is not None else "telegram:manual"
        content_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
        normalized_source_event_key = _normalize_source_event_key(source_event_key)
        tracer = get_tracer(__name__)
        if normalized_source_event_key is not None:
            async with self._session_factory() as session:
                with tracer.start_as_current_span("assistant.create_dream.lookup_existing"):
                    result = await session.execute(
                        select(DreamEntry).where(
                            DreamEntry.source_event_key == normalized_source_event_key
                        )
                    )
                existing = result.scalar_one_or_none()
                if existing is not None:
                    if existing.content_hash != content_hash:
                        raise DreamIngressConflictError(
                            "The same source event contains different dream text"
                        )
                    return await self._existing_dream_capture_result(session, existing)

        # Capture must not depend on an LLM.  A deterministic title is enough
        # to acknowledge the durable record; enrichment happens from the DB
        # outbox after the transaction commits.
        resolved_title = _resolve_dream_title(
            normalized_text,
            title=prepared_input.title,
            dream_date=resolved_dream_date,
        )

        async with self._session_factory() as session:
            dream = DreamEntry(
                id=uuid.uuid4(),
                source_doc_id=source_doc_id,
                date=resolved_dream_date,
                title=resolved_title,
                raw_text=normalized_text,
                word_count=len(normalized_text.split()),
                content_hash=content_hash,
                source_event_key=normalized_source_event_key,
                segmentation_confidence="low",
                parser_profile="telegram",
                parse_warnings=[],
                created_at=datetime.now(timezone.utc),
            )
            processing_jobs = [
                DreamProcessingJob(
                    id=uuid.uuid4(),
                    dream_id=dream.id,
                    status="pending",
                    stage=stage,
                    attempt_count=0,
                    available_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                for stage in DREAM_PROCESSING_STAGES
            ]
            session.add_all([dream, *processing_jobs])
            try:
                with tracer.start_as_current_span("assistant.create_dream.commit"):
                    await session.commit()
            except IntegrityError:
                # Two deliveries of the same Telegram update can pass the
                # lookup concurrently.  Only the ingress event key arbitrates
                # that race; identical text from distinct events is legitimate.
                await session.rollback()
                if normalized_source_event_key is None:
                    raise
                race_result = await session.execute(
                    select(DreamEntry).where(
                        DreamEntry.source_event_key == normalized_source_event_key
                    )
                )
                race_winner = race_result.scalar_one_or_none()
                if race_winner is None:
                    raise
                if race_winner.content_hash != content_hash:
                    raise DreamIngressConflictError(
                        "The same source event contains different dream text"
                    )
                return await self._existing_dream_capture_result(session, race_winner)

        return CreatedDreamItem(
            id=dream.id,
            date=dream.date.isoformat() if dream.date is not None else None,
            title=dream.title,
            word_count=dream.word_count,
            source_doc_id=dream.source_doc_id,
            created_at=dream.created_at.isoformat(),
            created=True,
            written_to_google_doc=False,
            semantic_index_status="pending",
            processing_status="pending",
            google_doc_write_status="pending",
            processing_job_id=processing_jobs[0].id,
            processing_job_ids=tuple(job.id for job in processing_jobs),
        )

    async def _existing_dream_capture_result(
        self,
        session: AsyncSession,
        dream: DreamEntry,
    ) -> CreatedDreamItem:
        jobs = await self._ensure_dream_processing_jobs(session, dream_id=dream.id)
        jobs_by_stage = {job.stage: job for job in jobs}
        index_job = jobs_by_stage["index"]
        google_job = jobs_by_stage["gdocs"]
        processing_status = _aggregate_processing_status(jobs)
        return CreatedDreamItem(
            id=dream.id,
            date=dream.date.isoformat() if dream.date is not None else None,
            title=dream.title,
            word_count=dream.word_count,
            source_doc_id=dream.source_doc_id,
            created_at=dream.created_at.isoformat(),
            created=False,
            written_to_google_doc=google_job.status == "succeeded",
            semantic_index_status=_public_stage_status(index_job.status),
            processing_status=processing_status,
            google_doc_write_status=_public_stage_status(google_job.status),
            processing_job_id=index_job.id,
            processing_job_ids=tuple(job.id for job in jobs),
        )

    async def _ensure_dream_processing_jobs(
        self,
        session: AsyncSession,
        *,
        dream_id: uuid.UUID,
    ) -> list[DreamProcessingJob]:
        jobs_result = await session.execute(
            select(DreamProcessingJob).where(DreamProcessingJob.dream_id == dream_id)
        )
        jobs = list(jobs_result.scalars().all())
        jobs_by_stage = {job.stage: job for job in jobs}
        missing_stages = [stage for stage in DREAM_PROCESSING_STAGES if stage not in jobs_by_stage]
        if missing_stages:
            now = datetime.now(timezone.utc)
            dream = await session.get(DreamEntry, dream_id)
            native_google_source = bool(
                dream is not None and not dream.source_doc_id.startswith("telegram:")
            )
            new_jobs = [
                DreamProcessingJob(
                    id=uuid.uuid4(),
                    dream_id=dream_id,
                    status=(
                        "succeeded" if stage == "gdocs" and native_google_source else "pending"
                    ),
                    stage=stage,
                    attempt_count=0,
                    available_at=now,
                    updated_at=now,
                )
                for stage in missing_stages
            ]
            session.add_all(new_jobs)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                winning_jobs_result = await session.execute(
                    select(DreamProcessingJob).where(DreamProcessingJob.dream_id == dream_id)
                )
                jobs = list(winning_jobs_result.scalars().all())
                if len({job.stage for job in jobs}) != len(DREAM_PROCESSING_STAGES):
                    raise
            else:
                jobs.extend(new_jobs)
        return sorted(jobs, key=lambda job: DREAM_PROCESSING_STAGES.index(job.stage))

    async def retry_dream_processing(
        self,
        dream_id: uuid.UUID,
        *,
        stages: tuple[str, ...] | None = None,
    ) -> tuple[uuid.UUID, ...]:
        """Explicitly restore failed stage attempt budgets for operator/user retry."""
        requested = set(stages or DREAM_PROCESSING_STAGES)
        unknown = requested.difference(DREAM_PROCESSING_STAGES)
        if unknown:
            raise ValueError(f"Unknown dream processing stages: {sorted(unknown)}")

        async with self._session_factory() as session:
            result = await session.execute(
                select(DreamProcessingJob).where(
                    DreamProcessingJob.dream_id == dream_id,
                    DreamProcessingJob.stage.in_(requested),
                    DreamProcessingJob.status == "failed",
                )
            )
            jobs = list(result.scalars().all())
            now = datetime.now(timezone.utc)
            for job in jobs:
                job.status = "retryable"
                job.attempt_count = 0
                job.last_error = None
                job.available_at = now
                job.locked_at = None
                job.lock_token = None
                job.updated_at = now
                session.add(job)
            if jobs:
                await session.commit()
        return tuple(job.id for job in jobs)

    async def process_dream_processing_job(
        self,
        job_id: uuid.UUID,
        *,
        lock_token: uuid.UUID | None = None,
    ) -> None:
        """Run exactly one independently retryable post-capture stage.

        Workers pass their lease token so a stale owner cannot start another
        stage after the row has been reclaimed.  Completion is persisted by
        the worker with the same token (CAS); stage work itself is idempotent.
        """
        async with self._session_factory() as session:
            job = await session.get(DreamProcessingJob, job_id)
            if job is None:
                raise ValueError(f"Dream processing job {job_id} does not exist")
            if lock_token is not None and (job.status != "running" or job.lock_token != lock_token):
                raise DreamProcessingLeaseLost(
                    f"Dream processing job {job_id} lease is no longer owned"
                )
            dream_id = job.dream_id
            stage = job.stage

        if stage == "index":
            await self._index_dream_callable(dream_id)
            return

        if stage == "analysis":
            await self._analysis_service.analyse_dream_with_session_factory(
                dream_id,
                self._session_factory,
            )
            return

        if stage == "motif":
            if get_settings().MOTIF_INDUCTION_ENABLED:
                async with self._session_factory() as session:
                    dream = await session.get(DreamEntry, dream_id)
                    if dream is None:
                        raise ValueError(f"Dream entry {dream_id} does not exist")
                    await self._motif_service.run(dream, session, strict=True)
                    await session.commit()
            return

        if stage == "gdocs":
            written, _doc_name = await self.write_dream_to_google_doc(dream_id=dream_id)
            if not written:
                raise DreamProcessingRetryable(
                    "Google Docs write is pending after a retryable failure"
                )
            return

        raise ValueError(f"Unknown dream processing stage: {stage}")

    async def write_dream_to_google_doc(
        self,
        dream_id: uuid.UUID,
        doc_id: str | None = None,
        *,
        write_status_id: uuid.UUID | None = None,
    ) -> tuple[bool, str]:
        """Write a dream entry to Google Doc.

        Returns ``(desired_state_reached, doc_name)``.  A successful existing
        receipt counts as reached, while a fresh pending receipt is left to its
        current owner and returns ``False``.  The receipt claim is atomic and
        finalized with a token compare-and-swap.
        """
        from app.shared.config import get_doc_name, get_effective_google_doc_id

        del write_status_id  # Legacy hint; the unique dream/document key is authoritative.
        resolved_doc_id = doc_id or get_effective_google_doc_id()
        doc_name = get_doc_name(resolved_doc_id)
        tracer = get_tracer(__name__)
        receipt_id: uuid.UUID | None = None
        claim_token: uuid.UUID | None = None
        with tracer.start_as_current_span("assistant.write_dream_to_google_doc"):
            try:
                async with self._session_factory() as session:
                    with tracer.start_as_current_span("db.dream_write_status.prepare"):
                        # Serialize with source-ingest reconciliation on the
                        # dream row before either side performs a cross-system
                        # write/receipt transition.
                        dream = await session.get(
                            DreamEntry,
                            dream_id,
                            with_for_update=True,
                        )
                        if dream is None:
                            logger.warning(
                                "write_dream_to_google_doc: dream not found",
                                dream_id=str(dream_id),
                            )
                            return False, doc_name

                        now = datetime.now(timezone.utc)
                        claim_token = uuid.uuid4()
                        proposed_receipt_id = uuid.uuid4()
                        claim_stmt = (
                            pg_insert(DreamWriteStatus)
                            .values(
                                id=proposed_receipt_id,
                                dream_id=dream_id,
                                target_doc_id=resolved_doc_id,
                                status="pending",
                                attempt_count=1,
                                last_error=None,
                                claim_token=claim_token,
                                created_at=now,
                                updated_at=now,
                            )
                            .on_conflict_do_update(
                                constraint="uq_dream_write_statuses_dream_target",
                                set_={
                                    "status": "pending",
                                    "attempt_count": DreamWriteStatus.attempt_count + 1,
                                    "last_error": None,
                                    "claim_token": claim_token,
                                    "updated_at": now,
                                },
                                where=or_(
                                    DreamWriteStatus.status == "failed",
                                    and_(
                                        DreamWriteStatus.status == "pending",
                                        DreamWriteStatus.updated_at
                                        < now - WRITE_RECEIPT_STALE_AFTER,
                                    ),
                                ),
                            )
                            .returning(DreamWriteStatus.id)
                        )
                        claim_result = await session.execute(claim_stmt)
                        receipt_id = claim_result.scalar_one_or_none()
                        if receipt_id is None:
                            existing_result = await session.execute(
                                select(DreamWriteStatus).where(
                                    DreamWriteStatus.dream_id == dream_id,
                                    DreamWriteStatus.target_doc_id == resolved_doc_id,
                                )
                            )
                            existing_receipt = existing_result.scalar_one_or_none()
                            await session.commit()
                            if (
                                existing_receipt is not None
                                and existing_receipt.status == "succeeded"
                            ):
                                logger.info(
                                    "Google Docs write already has a successful receipt",
                                    dream_id=str(dream_id),
                                    doc_id=resolved_doc_id,
                                )
                                return True, doc_name
                            # Another writer owns a fresh claim.  Do not race it.
                            return False, doc_name
                        await session.commit()

                date_str = dream.date.strftime("%d.%m.%y") if dream.date else "??.??.??"
                title_str = (
                    dream.title.strip() if dream.title and dream.title.strip() else "без названия"
                )
                raw_text = dream.raw_text or ""

                client = GDocsClient()
                inserted = await asyncio.to_thread(
                    client.append_dream_entry,
                    resolved_doc_id,
                    date_str,
                    title_str,
                    raw_text,
                    idempotency_key=f"dream:{dream.id}",
                )
                logger.info(
                    "Dream Google Docs state ensured",
                    dream_id=str(dream_id),
                    doc_id=resolved_doc_id,
                    inserted=inserted,
                )
                await self._mark_dream_write_status(
                    receipt_id,
                    claim_token=claim_token,
                    status="succeeded",
                    last_error=None,
                )
                return True, doc_name
            except GDocsWriteError as exc:
                await self._mark_dream_write_status(
                    receipt_id,
                    claim_token=claim_token,
                    status="failed",
                    last_error=_sanitize_write_error(str(exc)),
                )
                logger.warning(
                    "Failed to write dream to Google Doc",
                    dream_id=str(dream_id),
                    doc_id=resolved_doc_id,
                    error=str(exc),
                )
                return False, doc_name
            except Exception as exc:
                await self._mark_dream_write_status(
                    receipt_id,
                    claim_token=claim_token,
                    status="failed",
                    last_error=_sanitize_write_error(str(exc)),
                )
                logger.error(
                    "Unexpected error writing dream to Google Doc",
                    dream_id=str(dream_id),
                    error=str(exc),
                )
                return False, doc_name

    async def _mark_dream_write_status(
        self,
        write_status_id: uuid.UUID | None,
        *,
        claim_token: uuid.UUID | None,
        status: str,
        last_error: str | None,
    ) -> bool:
        if write_status_id is None or claim_token is None:
            return False
        async with self._session_factory() as session:
            with get_tracer(__name__).start_as_current_span("db.dream_write_status.update"):
                result = await session.execute(
                    update(DreamWriteStatus)
                    .where(
                        DreamWriteStatus.id == write_status_id,
                        DreamWriteStatus.status == "pending",
                        DreamWriteStatus.claim_token == claim_token,
                    )
                    .values(
                        status=status,
                        last_error=last_error,
                        claim_token=None,
                        updated_at=datetime.now(timezone.utc),
                    )
                    .returning(DreamWriteStatus.id)
                )
                await session.commit()
                return result.scalar_one_or_none() is not None

    async def retry_write_to_google_doc(
        self, dream_id: uuid.UUID | None = None, *, chat_id: int | None = None
    ) -> tuple[bool, str, str]:
        """Retry or repeat a Google Doc write.

        If dream_id is omitted, retry the latest failed write scoped to the current
        Telegram chat source when chat_id is available.  A successful receipt is
        reported as ``already_present`` and is never presented as a fresh append;
        forced repair requires explicit receipt/marker reconciliation.
        """
        from app.shared.config import get_doc_name, get_effective_google_doc_id

        target_doc_id = get_effective_google_doc_id()
        if dream_id is not None:
            write_status_id: uuid.UUID | None = None
            async with self._session_factory() as session:
                with get_tracer(__name__).start_as_current_span(
                    "db.dream_write_status.retry_lookup"
                ):
                    result = await session.execute(
                        select(DreamWriteStatus)
                        .where(DreamWriteStatus.dream_id == dream_id)
                        .where(DreamWriteStatus.target_doc_id == target_doc_id)
                        .where(DreamWriteStatus.status == "failed")
                        .order_by(DreamWriteStatus.updated_at.desc())
                        .limit(1)
                    )
                    write_status = result.scalar_one_or_none()
                    if write_status is not None:
                        write_status_id = write_status.id
                    else:
                        succeeded_result = await session.execute(
                            select(DreamWriteStatus).where(
                                DreamWriteStatus.dream_id == dream_id,
                                DreamWriteStatus.target_doc_id == target_doc_id,
                                DreamWriteStatus.status == "succeeded",
                            )
                        )
                        if succeeded_result.scalar_one_or_none() is not None:
                            return True, get_doc_name(target_doc_id), "already_present"
            success, doc_name = await self.write_dream_to_google_doc(
                dream_id=dream_id,
                write_status_id=write_status_id,
            )
            return success, doc_name, "retried"

        async with self._session_factory() as session:
            with get_tracer(__name__).start_as_current_span("db.dream_write_status.retry_lookup"):
                stmt = (
                    select(DreamWriteStatus)
                    .join(DreamEntry, DreamEntry.id == DreamWriteStatus.dream_id)
                    .where(DreamWriteStatus.status == "failed")
                    .where(DreamWriteStatus.target_doc_id == target_doc_id)
                    .order_by(DreamWriteStatus.updated_at.desc())
                    .limit(1)
                )
                if chat_id is not None:
                    stmt = stmt.where(DreamEntry.source_doc_id == f"telegram:{chat_id}")
                result = await session.execute(stmt)
                write_status = result.scalar_one_or_none()
                if write_status is None:
                    if chat_id is None:
                        return False, "", "nothing_to_retry"
                    latest_result = await session.execute(
                        select(DreamEntry)
                        .where(DreamEntry.source_doc_id == f"telegram:{chat_id}")
                        .order_by(DreamEntry.created_at.desc())
                        .limit(1)
                    )
                    latest_dream = latest_result.scalar_one_or_none()
                    if latest_dream is None:
                        return False, "", "nothing_to_retry"
                    dream_id = latest_dream.id
                    write_status_id = None
                    succeeded_result = await session.execute(
                        select(DreamWriteStatus).where(
                            DreamWriteStatus.dream_id == dream_id,
                            DreamWriteStatus.target_doc_id == target_doc_id,
                            DreamWriteStatus.status == "succeeded",
                        )
                    )
                    if succeeded_result.scalar_one_or_none() is not None:
                        return True, get_doc_name(target_doc_id), "already_present"
                else:
                    dream_id = write_status.dream_id
                    write_status_id = write_status.id

        success, doc_name = await self.write_dream_to_google_doc(
            dream_id=dream_id,
            write_status_id=write_status_id,
        )
        return success, doc_name, "retried"

    async def add_dream_note(
        self,
        note_text: str,
        dream_id: uuid.UUID | None = None,
        chat_id: int | None = None,
    ) -> tuple[bool, str]:
        """Durably save a note and queue its independent post-capture stages."""
        normalized_text = note_text.strip()
        if not normalized_text:
            return False, "Текст заметки пуст."

        tracer = get_tracer(__name__)
        target_dream_id = dream_id
        if target_dream_id is None and chat_id is not None:
            recent = load_recent_dream_set(chat_id)
            if recent is not None and len(recent.dream_ids) == 1:
                with contextlib.suppress(ValueError):
                    target_dream_id = uuid.UUID(recent.dream_ids[0])

        note_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
        async with self._session_factory() as session:
            with tracer.start_as_current_span("assistant.add_dream_note.resolve_dream"):
                dream = await self._resolve_note_target_dream(
                    session,
                    dream_id=target_dream_id,
                    chat_id=chat_id,
                )
            if dream is None:
                return False, "Не найден сон для добавления заметки."

            existing_note_result = await session.execute(
                select(DreamNote).where(
                    DreamNote.dream_id == dream.id,
                    DreamNote.content_hash == note_hash,
                )
            )
            note = existing_note_result.scalar_one_or_none()
            if note is not None:
                # A legacy duplicate has no trustworthy Google Docs delivery
                # receipt.  Repairing its semantic index is safe; blindly
                # creating a Google Docs job could duplicate historical text.
                index_job = await self._ensure_safe_note_index_job(session, note_id=note.id)
                return True, await self._existing_note_processing_message(
                    session,
                    note_id=note.id,
                    index_job=index_job,
                )

            now = datetime.now(timezone.utc)
            note = DreamNote(
                id=uuid.uuid4(),
                dream_id=dream.id,
                text=normalized_text,
                content_hash=note_hash,
                source="telegram",
                created_at=now,
            )
            processing_jobs = [
                NoteProcessingJob(
                    id=uuid.uuid4(),
                    note_id=note.id,
                    stage="index",
                    status="pending",
                    attempt_count=0,
                    available_at=now,
                    updated_at=now,
                ),
                NoteProcessingJob(
                    id=uuid.uuid4(),
                    note_id=note.id,
                    stage="gdocs",
                    status="pending",
                    attempt_count=0,
                    available_at=now,
                    target_doc_id=self._resolve_note_doc_id(dream),
                    updated_at=now,
                ),
            ]
            session.add_all([note, *processing_jobs])
            try:
                with tracer.start_as_current_span("assistant.add_dream_note.commit"):
                    await session.commit()
            except IntegrityError:
                # A concurrent replay won the note uniqueness race.  Its note
                # and jobs committed atomically; for a legacy winner, only the
                # safe index stage may be repaired here.
                await session.rollback()
                raced_note_result = await session.execute(
                    select(DreamNote).where(
                        DreamNote.dream_id == dream.id,
                        DreamNote.content_hash == note_hash,
                    )
                )
                raced_note = raced_note_result.scalar_one_or_none()
                if raced_note is None:
                    raise
                index_job = await self._ensure_safe_note_index_job(session, note_id=raced_note.id)
                return True, await self._existing_note_processing_message(
                    session,
                    note_id=raced_note.id,
                    index_job=index_job,
                )

        return (
            True,
            "Заметка сохранена. Семантический индекс и Google Doc обновятся в фоне.",
        )

    async def _ensure_safe_note_index_job(
        self,
        session: AsyncSession,
        *,
        note_id: uuid.UUID,
    ) -> NoteProcessingJob:
        result = await session.execute(
            select(NoteProcessingJob).where(
                NoteProcessingJob.note_id == note_id,
                NoteProcessingJob.stage == "index",
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            return existing

        now = datetime.now(timezone.utc)
        job = NoteProcessingJob(
            id=uuid.uuid4(),
            note_id=note_id,
            stage="index",
            status="pending",
            attempt_count=0,
            available_at=now,
            updated_at=now,
        )
        session.add(job)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            winner_result = await session.execute(
                select(NoteProcessingJob).where(
                    NoteProcessingJob.note_id == note_id,
                    NoteProcessingJob.stage == "index",
                )
            )
            winner = winner_result.scalar_one_or_none()
            if winner is None:
                raise
            return winner
        return job

    async def _existing_note_processing_message(
        self,
        session: AsyncSession,
        *,
        note_id: uuid.UUID,
        index_job: NoteProcessingJob,
    ) -> str:
        result = await session.execute(
            select(NoteProcessingJob).where(
                NoteProcessingJob.note_id == note_id,
                NoteProcessingJob.stage == "gdocs",
            )
        )
        gdocs_job = result.scalar_one_or_none()
        return _existing_note_status_message(
            index_status=index_job.status,
            gdocs_status=gdocs_job.status if gdocs_job is not None else None,
        )

    async def retry_note_processing(
        self,
        note_id: uuid.UUID,
        *,
        stages: tuple[str, ...] | None = None,
    ) -> tuple[uuid.UUID, ...]:
        """Explicitly restore attempt budgets for failed note stages only."""
        requested = set(stages or NOTE_PROCESSING_STAGES)
        unknown = requested.difference(NOTE_PROCESSING_STAGES)
        if unknown:
            raise ValueError(f"Unknown note processing stages: {sorted(unknown)}")

        async with self._session_factory() as session:
            result = await session.execute(
                select(NoteProcessingJob).where(
                    NoteProcessingJob.note_id == note_id,
                    NoteProcessingJob.stage.in_(requested),
                    NoteProcessingJob.status == "failed",
                )
            )
            jobs = list(result.scalars().all())
            now = datetime.now(timezone.utc)
            for job in jobs:
                job.status = "retryable"
                job.attempt_count = 0
                job.last_error = None
                job.available_at = now
                job.locked_at = None
                job.lock_token = None
                job.updated_at = now
                session.add(job)
            if jobs:
                await session.commit()
        return tuple(job.id for job in jobs)

    async def process_note_processing_job(
        self,
        job_id: uuid.UUID,
        *,
        lock_token: uuid.UUID | None = None,
    ) -> None:
        """Run exactly one immutable, idempotent note processing stage."""
        async with self._session_factory() as session:
            job = await session.get(NoteProcessingJob, job_id)
            if job is None:
                raise ValueError(f"Note processing job {job_id} does not exist")
            if lock_token is not None and (job.status != "running" or job.lock_token != lock_token):
                raise NoteProcessingLeaseLost(
                    f"Note processing job {job_id} lease is no longer owned"
                )
            note_id = job.note_id
            stage = job.stage
            target_doc_id = job.target_doc_id

            if stage == "gdocs":
                note = await session.get(DreamNote, note_id)
                if note is None:
                    raise ValueError(f"Dream note {note_id} does not exist")
                dream = await session.get(DreamEntry, note.dream_id)
                if dream is None:
                    raise ValueError(f"Dream entry {note.dream_id} does not exist")
                headings = _dream_doc_heading_candidates(dream)
                created_at = note.created_at
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                note_line = f"[Note {created_at.astimezone(timezone.utc):%d.%m.%y}]: {note.text}"

        if stage == "index":
            await self._index_note_callable(note_id)
            return

        if stage == "gdocs":
            if not target_doc_id:
                raise NoteProcessingRetryable("Note Google Docs target is missing")
            client = GDocsClient()
            for heading in headings:
                placed = await asyncio.to_thread(
                    client.insert_text_under_heading,
                    target_doc_id,
                    heading=heading,
                    text=note_line,
                    idempotency_key=f"note:{note_id}",
                )
                if placed:
                    return
            raise NoteProcessingRetryable("Dream heading is not present in Google Docs yet")

        raise ValueError(f"Unknown note processing stage: {stage}")

    async def _resolve_dream_title_for_recording(
        self,
        raw_text: str,
        *,
        title: str | None,
    ) -> str:
        if title is not None and title.strip():
            return _strip_date_prefix(title.strip())
        return await self._generate_dream_title_with_llm(raw_text)

    async def _generate_dream_title_with_llm(self, raw_text: str) -> str:
        fallback = _generate_dream_title(raw_text)
        try:
            generated = await self._title_llm_client.complete(
                _DREAM_TITLE_SYSTEM_PROMPT,
                _build_dream_title_prompt(raw_text),
                max_tokens=80,
            )
        except Exception:
            logger.warning("Dream title LLM generation failed; using fallback", exc_info=True)
            return fallback

        cleaned = _clean_generated_dream_title(generated)
        return cleaned or fallback

    async def prepare_dream_interpretation_request(
        self,
        *,
        dream_id: uuid.UUID | None = None,
        user_request: str = "",
        chat_id: int | None = None,
    ) -> DreamInterpretationRequest | None:
        async with self._session_factory() as session:
            dream = await self._resolve_note_target_dream(
                session,
                dream_id=dream_id,
                chat_id=chat_id,
            )
            if dream is None:
                return None

        prompt = _build_dream_interpretation_prompt(dream, user_request=user_request)
        return DreamInterpretationRequest(
            dream_id=dream.id,
            title=dream.title,
            prompt=prompt,
        )

    async def interpret_dream_with_prompt(
        self,
        *,
        dream_id: uuid.UUID,
        prompt: str,
    ) -> DreamInterpretationResult | None:
        async with self._session_factory() as session:
            dream = await session.get(DreamEntry, dream_id)
            if dream is None:
                return None

        try:
            interpretation = await self._interpretation_llm_client.complete(
                _DREAM_INTERPRETATION_SYSTEM_PROMPT,
                prompt,
                max_tokens=1200,
            )
        except LLMClientError:
            logger.warning("Dream interpretation LLM failed", dream_id=str(dream_id))
            raise

        return DreamInterpretationResult(
            dream_id=dream.id,
            title=dream.title,
            text=interpretation.strip(),
        )

    async def get_theme_history(self, dream_id: uuid.UUID) -> list[ThemeHistoryEntry]:
        async with self._session_factory() as session:
            _, versions = await self._versioning_service.list_theme_history(
                session, dream_id=dream_id
            )

        return [
            ThemeHistoryEntry(
                id=version.id,
                entity_type=version.entity_type,
                entity_id=version.entity_id,
                snapshot=version.snapshot,
                created_at=version.created_at.isoformat(),
            )
            for version in versions
        ]

    async def get_dream_motifs(self, dream_id: uuid.UUID) -> list[MotifInductionItem]:
        tracer = get_tracer(__name__)

        async with self._session_factory() as session:
            with tracer.start_as_current_span("assistant.get_dream_motifs"):
                result = await session.execute(
                    select(MotifInduction)
                    .where(MotifInduction.dream_id == dream_id)
                    .where(MotifInduction.status != "rejected")
                    .order_by(MotifInduction.created_at.asc(), MotifInduction.id.asc())
                )

        return [_motif_induction_item(motif) for motif in result.scalars().all()]

    async def research_motif_parallels(
        self,
        motif_id: uuid.UUID,
        triggered_by: str,
    ) -> list[dict[str, Any]]:
        tracer = get_tracer(__name__)

        async with self._session_factory() as session:
            with tracer.start_as_current_span("assistant.research_motif_parallels"):
                research_result = await self._research_service.run(
                    motif_id,
                    session,
                    triggered_by=triggered_by,
                )
            with tracer.start_as_current_span("assistant.research_motif_parallels.commit"):
                await session.commit()
            with tracer.start_as_current_span("assistant.research_motif_parallels.refresh"):
                await session.refresh(research_result)

        return _research_parallel_items(research_result)

    async def trigger_sync(self, doc_id: str = "", chat_id: int | None = None) -> list[SyncJobRef]:
        from app.shared.config import get_all_doc_ids

        if self._sync_job_enqueuer is None:
            raise RuntimeError("AssistantFacade trigger_sync requires a sync job enqueuer")

        doc_ids = [doc_id] if doc_id.strip() else get_all_doc_ids()
        refs: list[SyncJobRef] = []
        for resolved_doc_id in doc_ids:
            job_id = uuid.uuid4()
            await self._sync_job_enqueuer.enqueue_ingest(
                job_id=job_id,
                doc_id=resolved_doc_id,
                chat_id=chat_id,
            )
            refs.append(SyncJobRef(job_id=job_id, status="queued", doc_id=resolved_doc_id))
        return refs

    async def get_sync_status(self, doc_id: str = "") -> list[ArchiveSyncStatus]:
        from app.shared.config import get_all_doc_ids

        if self._sync_job_enqueuer is None:
            raise RuntimeError("AssistantFacade get_sync_status requires a sync job enqueuer")
        status_getter = getattr(self._sync_job_enqueuer, "get_auto_sync_status", None)
        if status_getter is None:
            raise RuntimeError("Sync status is unavailable in this runtime")

        doc_ids = [doc_id] if doc_id.strip() else get_all_doc_ids()
        statuses: list[ArchiveSyncStatus] = []
        for resolved_doc_id in doc_ids:
            state = await status_getter(resolved_doc_id)
            statuses.append(
                ArchiveSyncStatus(
                    doc_id=resolved_doc_id,
                    status=state.last_sync_status,
                    last_checked_at=state.last_checked_at,
                    last_sync_started_at=state.last_sync_started_at,
                    last_synced_at=state.last_synced_at,
                    last_sync_job_id=state.last_sync_job_id,
                    is_stale_running=_sync_state_looks_stale(state),
                    last_sync_error=getattr(state, "last_sync_error", None),
                    last_added_count=getattr(state, "last_added_count", None),
                    last_sync_stage=getattr(state, "last_sync_stage", None),
                )
            )
        return statuses

    def create_archive_source_document(self, title: str) -> dict[str, str]:
        """Create a new Google Doc, share with owner if configured, return {id, name, url}."""
        from app.shared.config import register_doc_name

        owner_email = get_settings().GOOGLE_OWNER_EMAIL.strip() or None
        client = GDocsClient()
        doc = client.create_document(title, owner_email=owner_email)
        register_doc_name(doc["id"], doc["name"])
        return doc

    def search_archive_source_by_title(self, title: str) -> list[dict[str, str]]:
        """Search Google Drive for Docs matching *title*. Returns [{id, name}, ...]."""
        client = GDocsClient()
        return client.search_docs_by_title(title)

    def get_archive_source(self) -> str:
        from app.shared.config import get_effective_google_doc_id

        return get_effective_google_doc_id()

    def get_archive_source_name(self) -> str:
        """Return the human-readable name of the active write target."""
        from app.shared.config import get_doc_name, get_effective_google_doc_id

        return get_doc_name(get_effective_google_doc_id())

    def set_archive_source(self, doc_id: str) -> str:
        from app.shared.config import set_google_doc_id_override

        set_google_doc_id_override(doc_id)
        return doc_id

    def list_archive_sources(self) -> list[str]:
        from app.shared.config import get_all_doc_ids

        return get_all_doc_ids()

    def add_archive_source(self, doc_id: str, *, name: str | None = None) -> list[str]:
        from app.shared.config import (
            get_all_doc_ids,
            get_settings,
            register_doc_name,
            set_google_doc_ids_override,
        )

        if name:
            register_doc_name(doc_id, name)
        current_all = get_all_doc_ids()
        primary = current_all[0] if current_all else get_settings().GOOGLE_DOC_ID
        extras = [resolved_doc_id for resolved_doc_id in current_all if resolved_doc_id != primary]
        if doc_id not in current_all:
            extras.append(doc_id)
        set_google_doc_ids_override(extras)
        return get_all_doc_ids()

    def remove_archive_source(self, doc_id: str) -> list[str]:
        from app.shared.config import (
            get_all_doc_ids,
            get_effective_google_doc_id,
            set_google_doc_ids_override,
        )

        primary = get_effective_google_doc_id()
        if doc_id == primary:
            raise ValueError("Cannot remove the primary archive source")
        current_all = get_all_doc_ids()
        extras = [
            resolved_doc_id
            for resolved_doc_id in current_all
            if resolved_doc_id != primary and resolved_doc_id != doc_id
        ]
        set_google_doc_ids_override(extras)
        return get_all_doc_ids()

    def _build_index_dream_callable(self) -> Callable[[uuid.UUID], Awaitable[int]]:
        async def _index(dream_id: uuid.UUID) -> int:
            from app.workers.index import index_dream

            return await index_dream({"session_factory": self._session_factory}, dream_id=dream_id)

        return _index

    def _build_index_note_callable(self) -> Callable[[uuid.UUID], Awaitable[int]]:
        async def _index(note_id: uuid.UUID) -> int:
            from app.workers.index import index_note

            return await index_note({"session_factory": self._session_factory}, note_id=note_id)

        return _index

    async def _resolve_note_target_dream(
        self,
        session: AsyncSession,
        *,
        dream_id: uuid.UUID | None,
        chat_id: int | None,
    ) -> DreamEntry | None:
        if dream_id is not None:
            return await session.get(DreamEntry, dream_id)

        stmt = select(DreamEntry)
        stmt = stmt.order_by(
            DreamEntry.date.desc().nullslast(),
            DreamEntry.created_at.desc(),
        ).limit(1)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    def _resolve_note_doc_id(self, dream: DreamEntry) -> str:
        from app.shared.config import get_effective_google_doc_id

        if dream.source_doc_id.startswith("telegram:"):
            return get_effective_google_doc_id()
        return dream.source_doc_id


def _existing_note_status_message(
    *,
    index_status: str,
    gdocs_status: str | None,
) -> str:
    if index_status == "succeeded":
        index_message = "семантический индекс готов"
    elif index_status == "failed":
        index_message = "семантический индекс требует явного повтора"
    else:
        index_message = "обновление семантического индекса стоит в очереди"

    if gdocs_status is None:
        gdocs_message = (
            "состояние доставки в Google Docs неизвестно, поэтому автоматически её не повторяю"
        )
    elif gdocs_status == "succeeded":
        gdocs_message = "запись в Google Docs подтверждена"
    elif gdocs_status == "failed":
        gdocs_message = "доставка в Google Docs требует явного повтора"
    else:
        gdocs_message = "обновление Google Docs стоит в очереди"
    return f"Заметка уже сохранена; {index_message}; {gdocs_message}."


def _search_result_item(block: EvidenceBlock, query: str) -> SearchResultItem:
    return SearchResultItem(
        dream_id=block.dream_id,
        date=block.date,
        title=block.title,
        chunk_text=block.chunk_text,
        relevance_score=block.relevance_score,
        matched_fragments=[
            {
                "text": fragment.text,
                "match_type": fragment.match_type,
                "char_offset": fragment.char_offset,
            }
            for fragment in block.matched_fragments
        ],
        quote=_extract_quote(block.chunk_text, query),
    )


def _is_verified_search_item(item: SearchResultItem) -> bool:
    if item.quote or item.matched_fragments:
        return True
    return item.relevance_score >= WEAK_SEARCH_RELEVANCE_THRESHOLD and bool(item.chunk_text.strip())


def _exact_result_item(row: dict[str, Any], query: str) -> SearchResultItem:
    return SearchResultItem(
        dream_id=row["dream_id"],
        date=row.get("date"),
        title=row.get("title"),
        chunk_text=row.get("chunk_text", ""),
        relevance_score=1.0,
        matched_fragments=[],
        quote=_extract_quote(row.get("chunk_text", ""), query),
    )


def _extract_quote(chunk_text: str, query: str) -> str | None:
    import re

    words = set(re.sub(r"[^\w\s]", "", query.lower()).split())
    if not words:
        return None
    for sentence in re.split(r"[.!?\n]+", chunk_text):
        stripped_sentence = sentence.strip()
        if not stripped_sentence:
            continue
        sentence_lower = stripped_sentence.lower()
        if any(
            re.search(
                r"(?<![а-яёА-ЯЁa-zA-Z\d])" + re.escape(word) + r"(?![а-яёА-ЯЁa-zA-Z\d])",
                sentence_lower,
            )
            for word in words
        ):
            return stripped_sentence
    return None


def _research_parallel_items(research_result: Any) -> list[dict[str, Any]]:
    sources = research_result.sources if isinstance(research_result.sources, list) else []
    source_lookup = {
        source.get("url"): source.get("retrieved_at")
        for source in sources
        if isinstance(source, dict) and source.get("url")
    }
    parallels = research_result.parallels if isinstance(research_result.parallels, list) else []

    return [
        {
            "domain": parallel.get("domain"),
            "label": parallel.get("label"),
            "source_url": parallel.get("source_url"),
            "retrieved_at": source_lookup.get(parallel.get("source_url")),
            "relevance_note": parallel.get("relevance_note"),
            "overlap_degree": parallel.get("overlap_degree"),
        }
        for parallel in parallels
        if isinstance(parallel, dict)
    ]


def _theme_item(*, theme: DreamTheme, category_name: str) -> DreamThemeItem:
    return DreamThemeItem(
        id=theme.id,
        category_id=theme.category_id,
        category_name=category_name,
        salience=theme.salience,
        status=theme.status,
        match_type=theme.match_type,
        fragments=[fragment for fragment in theme.fragments if isinstance(fragment, dict)],
        deprecated=theme.deprecated,
        created_at=theme.created_at.isoformat(),
    )


def _dream_summary_item(dream: DreamEntry, *, theme_names: list[str] | None = None) -> DreamSummary:
    return DreamSummary(
        id=dream.id,
        date=dream.date.isoformat() if dream.date is not None else None,
        title=dream.title,
        raw_text_preview=(dream.raw_text or "")[:400],
        theme_names=theme_names or [],
    )


def _dream_doc_heading(dream: DreamEntry) -> str:
    return _dream_doc_heading_candidates(dream)[0]


def _dream_doc_heading_candidates(dream: DreamEntry) -> list[str]:
    title = (dream.title or "").strip()
    clean_title = _DATE_PREFIX_RE.sub("", title).strip()
    candidates: list[str] = []

    def add(value: str | None) -> None:
        normalized = (value or "").strip()
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    if dream.date is None:
        add(clean_title)
        add(title)
        parsed_title = _split_title_date_prefix(title)
        if parsed_title is not None:
            title_date, title_without_date = parsed_title
            add(f"{title_date} - {title_without_date}")
            add(f"{title_date} {title_without_date}")
        return candidates

    date_str = dream.date.strftime("%d.%m.%y")
    add(f"{date_str} - {clean_title}")
    add(f"{date_str} {clean_title}")
    add(title)
    return candidates


def _split_title_date_prefix(title: str) -> tuple[str, str] | None:
    match = _DATE_TITLE_PREFIX_RE.match(title.strip())
    if match is None:
        return None
    day = int(match.group("day"))
    month = int(match.group("month"))
    year = match.group("year")
    suffix = match.group("title").strip()
    if not suffix:
        return None
    return f"{day:02d}.{month:02d}.{year[-2:]}", suffix


_DATE_PREFIX_RE = re.compile(r"^\d{2}\.\d{2}\.\d{2,4}[\s\-,]+")
_DATE_TITLE_PREFIX_RE = re.compile(
    r"^\s*(?P<day>\d{1,2})[./](?P<month>\d{1,2})[./](?P<year>\d{2,4})"
    r"(?:\s*[-–—,]\s*|\s+)(?P<title>\S.*)$"
)
_WORD_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё]+")
_INLINE_TITLE_PATTERNS = (
    re.compile(
        r"(?is)(?:^|[\n\r.!?:;–—-]\s*)(?:название|title)\s*[:\-–—]\s*"
        r"[\"«“]?(?P<title>[^.\n\r!?\"»”]+)[\"»”]?[.!?]?\s*"
    ),
    re.compile(
        r"(?is)(?:^|[\n\r.!?:;–—-]\s*)(?:назови\s+(?:его|сон)|с\s+названием)\s+"
        r"[\"«“]?(?P<title>.+?)[\"»”]?"
        r"(?=(?:[.!?\n\r]|,\s*(?:мне|я|во\s+сне|потом|там)\b|"
        r"\s+(?:мне\s+приснил|мне\s+снил|во\s+сне|я\s+)|$))"
        r"[\s,.;:!?–—-]*"
    ),
)
_TECHNICAL_RELATIVE_DATE_RE = re.compile(
    r"(?is)^\s*"
    r"(?:"
    r"(?:он|она|оно|они|сон)\s+мне\s+"
    r"(?:приснил(?:ся|ась|ось|ись)|снил(?:ся|ась|ось|ись))"
    r"|"
    r"(?:он|она|оно|они|сон)\s+"
    r"(?:приснил(?:ся|ась|ось|ись)|снил(?:ся|ась|ось|ись))"
    r")\s+"
    r"(?P<marker>сегодня|вчера|позавчера)"
    r"[\s:;,.!?–—-]*"
)
_LEADING_RELATIVE_DATE_DIRECTIVE_RE = re.compile(
    r"(?is)^\s*(?P<marker>сегодня|вчера|позавчера)"
    r"(?:\s*[:;,.!?–—-]+\s*|\s+(?=(?:мне\s+)?(?:приснил|снил)))"
)
_DREAM_RECORD_COMMAND_PREFIX_RE = re.compile(
    r"(?is)^\s*(?:пожалуйста[,\s]+)?"
    r"(?:(?:можешь|можно|давай|хочу|я\s+хочу)\s+)?"
    r"(?:"
    r"(?:запиши|сохрани|добавь|занеси|записать|сохранить|добавить|занести)"
    r"(?:\s+(?:мой|этот|новый|старый|следующий|прошлый))?\s+сон"
    r"(?:\s+текстом)?"
    r"(?:\s+в\s+(?:архив|документ|google\s+doc|гугл\s+документ))?"
    r"|"
    r"(?:запиши|сохрани|добавь|занеси|записать|сохранить|добавить|занести)"
    r"\s+в\s+архив"
    r")"
    r"[\s:;,.!?–—-]*"
)
_LEADING_DATE_DIRECTIVE_RE = re.compile(
    r"(?is)^\s*"
    r"(?:(?:дата(?:\s+сна)?|date)\s*[:\-–—]?\s*)?"
    r"(?:(?:за|от|на)\s+)?"
    r"(?P<date>\d{1,2}[./]\d{1,2}(?:[./](?:\d{2}|\d{4}))?)"
    r"[\s:;,.!?–—-]*"
)
_DEFAULT_APPLICATION_TIMEZONE = "Asia/Tbilisi"
_DREAM_INTERPRETATION_SYSTEM_PROMPT = (
    "You interpret dreams for a private archive. Write in Russian. "
    "Use only the supplied dream text and the user's approved request. "
    "Separate direct observations from hypotheses. Do not diagnose, do not claim certainty, "
    "and avoid instructions that replace professional help."
)
_DREAM_TITLE_SYSTEM_PROMPT = (
    "You create concise titles for private dream journal entries. "
    "Read the full dream text and return exactly one short title. "
    "Use Russian by default. Do not explain. Do not use markdown. "
    "Do not include dates, quotes, the word 'сон', or command words."
)
_TITLE_STOPWORDS = {
    "today",
    "dream",
    "dreamed",
    "dreamt",
    "there",
    "with",
    "that",
    "through",
    "сегодня",
    "вчера",
    "позавчера",
    "сон",
    "сна",
    "сне",
    "приснилось",
    "приснился",
    "приснилась",
    "приснились",
    "снилось",
    "мне",
    "что",
    "как",
    "был",
    "была",
    "были",
    "это",
    "там",
    "через",
    "который",
    "которая",
    "которые",
    "запиши",
    "сохрани",
    "добавь",
    "занеси",
    "название",
    "назови",
}


def _normalize_title_search(value: str) -> str:
    return " ".join(word.casefold() for word in _WORD_RE.findall(value))


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _title_match_rank(title: str, query: str) -> tuple[int, str]:
    title_folded = title.casefold()
    query_folded = query.strip().casefold()
    normalized_title = _normalize_title_search(title)
    normalized_query = _normalize_title_search(query)
    if title_folded == query_folded:
        rank = 0
    elif normalized_title == normalized_query:
        rank = 1
    elif query_folded and query_folded in title_folded:
        rank = 2
    else:
        rank = 3
    return rank, title_folded


_RELATIVE_DATE_OFFSETS = (
    ("позавчера", 2),
    ("сегодня", 0),
    ("вчера", 1),
)
_ABSOLUTE_DREAM_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})[./](\d{1,2})(?:[./](\d{2}|\d{4}))?(?!\d)")


def _strip_date_prefix(s: str) -> str:
    return _DATE_PREFIX_RE.sub("", s).strip()


def _application_today() -> date:
    timezone_name = get_settings().APP_TIMEZONE.strip()
    if not timezone_name:
        timezone_name = _DEFAULT_APPLICATION_TIMEZONE
    try:
        tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        logger.warning("Invalid APP_TIMEZONE, falling back to default", timezone=timezone_name)
        tz = ZoneInfo(_DEFAULT_APPLICATION_TIMEZONE)
    return datetime.now(tz=tz).date()


def _resolve_relative_dream_date(text: str, *, today: date | None = None) -> date | None:
    normalized = text.casefold()
    current = today or _application_today()
    for marker, days_back in _RELATIVE_DATE_OFFSETS:
        if marker in normalized:
            return date.fromordinal(current.toordinal() - days_back)
    return None


def _resolve_absolute_dream_date(text: str, *, today: date | None = None) -> date | None:
    match = _ABSOLUTE_DREAM_DATE_RE.search(text)
    if match is None:
        return None

    current = today or _application_today()
    day = int(match.group(1))
    month = int(match.group(2))
    year_raw = match.group(3)
    if year_raw is None:
        year = current.year
    else:
        year = int(year_raw)
        if len(year_raw) == 2:
            year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _sanitize_write_error(error: str) -> str:
    sanitized = re.sub(r"[\r\n\t]+", " ", error).strip()
    sanitized = re.sub(r"(token|secret|key)=\S+", r"\1=<redacted>", sanitized, flags=re.IGNORECASE)
    return sanitized[:300]


def _normalize_source_event_key(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    # Store a privacy-safe fixed-width identity while allowing callers to use
    # descriptive event keys such as telegram:<chat>:message:<id>.
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


def _aggregate_processing_status(jobs: list[DreamProcessingJob]) -> str:
    statuses = {job.status for job in jobs}
    if statuses == {"succeeded"}:
        return "succeeded"
    if "running" in statuses:
        return "running"
    if "retryable" in statuses:
        return "retryable"
    if "failed" in statuses:
        return "failed"
    return "pending"


def _public_stage_status(status: str) -> str:
    if status in {"succeeded", "failed"}:
        return status
    return "pending"


def _sync_state_looks_stale(state: Any) -> bool:
    if getattr(state, "last_sync_status", None) != "running":
        return False
    started_at_raw = getattr(state, "last_sync_started_at", None)
    if not started_at_raw:
        return True
    try:
        started_at = datetime.fromisoformat(started_at_raw)
    except ValueError:
        return True
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    stale_after_seconds = max(get_settings().AUTO_SYNC_INTERVAL_SECONDS * 2, 300)
    return (datetime.now(timezone.utc) - started_at).total_seconds() > stale_after_seconds


def _prepare_dream_recording_input(
    raw_text: str, *, title: str | None = None
) -> DreamRecordingInput:
    normalized_text = raw_text.strip()
    extracted_title: str | None = None

    for pattern in _INLINE_TITLE_PATTERNS:
        match = pattern.search(normalized_text)
        if match is None:
            continue
        extracted_title = _clean_inline_title(match.group("title"))
        normalized_text = f"{normalized_text[: match.start()]} {normalized_text[match.end() :]}"
        break

    normalized_text = _DREAM_RECORD_COMMAND_PREFIX_RE.sub("", normalized_text, count=1)
    dream_date_hint = _resolve_technical_relative_date_directive(normalized_text)
    normalized_text = _TECHNICAL_RELATIVE_DATE_RE.sub(" ", normalized_text)
    leading_relative_hint = _resolve_leading_relative_date_directive(normalized_text)
    dream_date_hint = dream_date_hint or leading_relative_hint
    if leading_relative_hint is not None:
        normalized_text = _LEADING_RELATIVE_DATE_DIRECTIVE_RE.sub("", normalized_text, count=1)
    dream_date_hint = dream_date_hint or _resolve_leading_date_directive(normalized_text)
    normalized_text = _LEADING_DATE_DIRECTIVE_RE.sub("", normalized_text, count=1)
    normalized_text = _normalize_recording_text(normalized_text)
    prepared_title = extracted_title or (title.strip() if title and title.strip() else None)
    return DreamRecordingInput(
        raw_text=normalized_text,
        title=prepared_title,
        dream_date_hint=dream_date_hint,
    )


def _resolve_leading_date_directive(value: str) -> date | None:
    match = _LEADING_DATE_DIRECTIVE_RE.match(value)
    if match is None:
        return None
    return _resolve_absolute_dream_date(match.group("date"))


def _resolve_leading_relative_date_directive(value: str) -> date | None:
    match = _LEADING_RELATIVE_DATE_DIRECTIVE_RE.match(value)
    if match is None:
        return None
    return _resolve_relative_dream_date(match.group("marker"))


def _resolve_technical_relative_date_directive(value: str) -> date | None:
    match = _TECHNICAL_RELATIVE_DATE_RE.match(value)
    if match is None:
        return None
    return _resolve_relative_dream_date(match.group("marker"))


def _clean_inline_title(value: str) -> str | None:
    title = " ".join(value.strip(" \t\r\n\"'«»“”").split())
    if not title:
        return None
    return _strip_date_prefix(title)


def _normalize_recording_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).lstrip(" \t\r\n:;,.!?–—-").rstrip()


def _build_dream_interpretation_prompt(dream: DreamEntry, *, user_request: str) -> str:
    date_text = dream.date.isoformat() if dream.date is not None else "unknown"
    request_text = user_request.strip() or "Дай бережную интерпретацию этого сна."
    return "\n".join(
        [
            "Пользователь должен подтвердить именно этот запрос перед запуском LLM.",
            f"Запрос пользователя: {request_text}",
            "",
            "Сон для интерпретации:",
            f"id: {dream.id}",
            f"date: {date_text}",
            f"title: {dream.title or 'без названия'}",
            "raw_text:",
            dream.raw_text or "",
            "",
            "Формат ответа:",
            "- краткая сводка образов;",
            "- возможные темы и напряжения;",
            "- 2-4 осторожные гипотезы;",
            "- вопросы для самонаблюдения.",
        ]
    )


def _resolve_dream_title(
    raw_text: str, *, title: str | None, dream_date: date | None = None
) -> str:
    if title is not None and title.strip():
        return _strip_date_prefix(title.strip())
    return _generate_dream_title(raw_text, dream_date=dream_date)


def _build_dream_title_prompt(raw_text: str) -> str:
    return "\n".join(
        [
            "Прочитай сон и дай короткое смысловое название.",
            "Требования:",
            "1. 2-6 слов.",
            "2. Не начинай с «о ...».",
            "3. Не используй дату и слово «сон».",
            "4. Не пересказывай весь сюжет.",
            "5. Верни только название.",
            "",
            "Текст сна:",
            raw_text.strip(),
        ]
    )


def _clean_generated_dream_title(value: str) -> str | None:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines:
        return None

    title = lines[0].strip(" \t\r\n\"'«»“”")
    title = re.sub(r"(?is)^(?:название|заголовок|title)\s*[:\-–—]\s*", "", title).strip()
    title = _strip_date_prefix(title)
    title = re.sub(r"\s+", " ", title).strip(" \t\r\n:;,.!?–—-\"'«»“”")
    if not title:
        return None
    if len(title) > 80:
        return None
    word_count = len(_WORD_RE.findall(title))
    if word_count == 0 or word_count > 8:
        return None
    if "```" in title or title.startswith(("-", "*")):
        return None
    if title.casefold() in {"сон", "без названия"}:
        return None
    return title


def _generate_dream_title(raw_text: str, *, dream_date: date | None = None) -> str:
    del dream_date
    words: list[str] = []
    seen: set[str] = set()
    for raw_word in _WORD_RE.findall(raw_text.casefold()):
        word = raw_word.strip()
        if len(word) < 4 or word.isdigit() or word in _TITLE_STOPWORDS or word in seen:
            continue
        seen.add(word)
        words.append(word)
        if len(words) == 3:
            break
    if len(words) < 2:
        return "без названия"
    return " ".join(words).capitalize()


def _recurring_pattern_item(pattern: RecurringPattern) -> RecurringPatternItem:
    return RecurringPatternItem(
        category_id=pattern.category_id,
        name=pattern.name,
        count=pattern.count,
        percentage_of_dreams=pattern.percentage_of_dreams,
    )


def _co_occurrence_pattern_item(pattern: CoOccurrencePattern) -> CoOccurrencePatternItem:
    return CoOccurrencePatternItem(
        category_ids=tuple(sorted(pattern.category_ids, key=str)),
        count=pattern.count,
    )


def _motif_induction_item(motif: MotifInduction) -> MotifInductionItem:
    return MotifInductionItem(
        id=motif.id,
        label=motif.label,
        rationale=motif.rationale,
        confidence=motif.confidence,
        status=motif.status,
        fragments=list(motif.fragments) if motif.fragments else [],
        model_version=motif.model_version,
        created_at=motif.created_at.isoformat(),
    )