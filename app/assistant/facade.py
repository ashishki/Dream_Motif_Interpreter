from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.dream import DreamEntry
from app.models.motif import MotifInduction
from app.models.note import DreamNote
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
        motif_service: MotifService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._rag_query_service = rag_query_service
        self._pattern_service = pattern_service
        self._versioning_service = versioning_service
        self._sync_job_enqueuer = sync_job_enqueuer
        self._analysis_service = analysis_service or AnalysisService()
        self._research_service = research_service or ResearchService()
        self._index_dream_callable = index_dream_callable or self._build_index_dream_callable()
        self._motif_service = motif_service or MotifService()

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
        self, query: str, limit: int = 10
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
                result = await session.execute(
                    select(DreamEntry)
                    .where(
                        or_(
                            DreamEntry.title.ilike(title_pattern, escape="\\"),
                            normalized_title.contains(normalized_query),
                        )
                    )
                    .order_by(DreamEntry.date.desc(), DreamEntry.created_at.desc())
                    .limit(bounded_limit)
                )
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
    ) -> CreatedDreamItem:
        normalized_text = raw_text.strip()
        if not normalized_text:
            raise ValueError("Dream text must not be empty")

        resolved_dream_date = (
            dream_date or _resolve_relative_dream_date(normalized_text) or _application_today()
        )
        resolved_title = _resolve_dream_title(
            normalized_text,
            title=title,
            dream_date=resolved_dream_date,
        )
        source_doc_id = f"telegram:{chat_id}" if chat_id is not None else "telegram:manual"
        content_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
        tracer = get_tracer(__name__)

        async with self._session_factory() as session:
            with tracer.start_as_current_span("assistant.create_dream.lookup_existing"):
                result = await session.execute(
                    select(DreamEntry).where(DreamEntry.content_hash == content_hash)
                )
            existing = result.scalar_one_or_none()
            if existing is not None:
                return CreatedDreamItem(
                    id=existing.id,
                    date=existing.date.isoformat() if existing.date is not None else None,
                    title=existing.title,
                    word_count=existing.word_count,
                    source_doc_id=existing.source_doc_id,
                    created_at=existing.created_at.isoformat(),
                    created=False,
                )

            dream = DreamEntry(
                id=uuid.uuid4(),
                source_doc_id=source_doc_id,
                date=resolved_dream_date,
                title=resolved_title,
                raw_text=normalized_text,
                word_count=len(normalized_text.split()),
                content_hash=content_hash,
                segmentation_confidence="low",
                parser_profile="telegram",
                parse_warnings=[],
                created_at=datetime.now(timezone.utc),
            )
            session.add(dream)
            with tracer.start_as_current_span("assistant.create_dream.commit"):
                await session.commit()

        await self._analysis_service.analyse_dream_with_session_factory(
            dream.id,
            self._session_factory,
        )
        await self._index_dream_callable(dream.id)

        if get_settings().MOTIF_INDUCTION_ENABLED:
            async with self._session_factory() as session:
                dream_entry = await session.get(DreamEntry, dream.id)
                if dream_entry is not None:
                    await self._motif_service.run(dream_entry, session)
                    await session.commit()

        written, written_doc_name = await self.write_dream_to_google_doc(dream_id=dream.id)

        return CreatedDreamItem(
            id=dream.id,
            date=dream.date.isoformat() if dream.date is not None else None,
            title=dream.title,
            word_count=dream.word_count,
            source_doc_id=dream.source_doc_id,
            created_at=dream.created_at.isoformat(),
            created=True,
            written_to_google_doc=written,
            written_to_doc_name=written_doc_name,
        )

    async def write_dream_to_google_doc(
        self,
        dream_id: uuid.UUID,
        doc_id: str | None = None,
        *,
        write_status_id: uuid.UUID | None = None,
    ) -> tuple[bool, str]:
        """Write a dream entry to Google Doc.

        Returns (success, doc_name). doc_name is the human-readable name of the
        target document, used so callers can tell the user exactly where the entry landed.
        """
        from app.shared.config import get_doc_name, get_effective_google_doc_id

        resolved_doc_id = doc_id or get_effective_google_doc_id()
        doc_name = get_doc_name(resolved_doc_id)
        tracer = get_tracer(__name__)
        with tracer.start_as_current_span("assistant.write_dream_to_google_doc"):
            write_status: DreamWriteStatus | None = None
            try:
                async with self._session_factory() as session:
                    with tracer.start_as_current_span("db.dream_write_status.prepare"):
                        dream = await session.get(DreamEntry, dream_id)
                        if dream is not None:
                            if write_status_id is not None:
                                write_status = await session.get(DreamWriteStatus, write_status_id)
                            if write_status is None:
                                write_status = DreamWriteStatus(
                                    dream_id=dream_id,
                                    target_doc_id=resolved_doc_id,
                                    status="pending",
                                    attempt_count=1,
                                    last_error=None,
                                    updated_at=datetime.now(timezone.utc),
                                )
                            else:
                                write_status.target_doc_id = resolved_doc_id
                                write_status.status = "pending"
                                write_status.attempt_count = (write_status.attempt_count or 0) + 1
                                write_status.last_error = None
                                write_status.updated_at = datetime.now(timezone.utc)
                            session.add(write_status)
                            await session.commit()
                if dream is None:
                    logger.warning(
                        "write_dream_to_google_doc: dream not found", dream_id=str(dream_id)
                    )
                    return False, doc_name

                date_str = dream.date.strftime("%d.%m.%y") if dream.date else "??.??.??"
                title_str = (
                    dream.title.strip() if dream.title and dream.title.strip() else "без названия"
                )
                raw_text = dream.raw_text or ""

                client = GDocsClient()
                client.append_dream_entry(resolved_doc_id, date_str, title_str, raw_text)
                logger.info(
                    "Dream written to Google Doc",
                    dream_id=str(dream_id),
                    doc_id=resolved_doc_id,
                )
                await self._mark_dream_write_status(
                    write_status,
                    status="succeeded",
                    last_error=None,
                )
                return True, doc_name
            except GDocsWriteError as exc:
                await self._mark_dream_write_status(
                    write_status,
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
                    write_status,
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
        write_status: DreamWriteStatus | None,
        *,
        status: str,
        last_error: str | None,
    ) -> None:
        if write_status is None:
            return
        write_status.status = status
        write_status.last_error = last_error
        write_status.updated_at = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            with get_tracer(__name__).start_as_current_span("db.dream_write_status.update"):
                session.add(write_status)
                await session.commit()

    async def retry_write_to_google_doc(
        self, dream_id: uuid.UUID | None = None, *, chat_id: int | None = None
    ) -> tuple[bool, str, str]:
        """Retry a failed Google Doc write.

        If dream_id is omitted, retry the latest failed write scoped to the current
        Telegram chat source when chat_id is available.
        Returns (success, doc_name, reason).
        """
        if dream_id is not None:
            write_status_id: uuid.UUID | None = None
            async with self._session_factory() as session:
                with get_tracer(__name__).start_as_current_span(
                    "db.dream_write_status.retry_lookup"
                ):
                    result = await session.execute(
                        select(DreamWriteStatus)
                        .where(DreamWriteStatus.dream_id == dream_id)
                        .where(DreamWriteStatus.status == "failed")
                        .order_by(DreamWriteStatus.updated_at.desc())
                        .limit(1)
                    )
                    write_status = result.scalar_one_or_none()
                    if write_status is not None:
                        write_status_id = write_status.id
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
                    .order_by(DreamWriteStatus.updated_at.desc())
                    .limit(1)
                )
                if chat_id is not None:
                    stmt = stmt.where(DreamEntry.source_doc_id == f"telegram:{chat_id}")
                result = await session.execute(stmt)
                write_status = result.scalar_one_or_none()
                if write_status is None:
                    return False, "", "nothing_to_retry"
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
        """Add a note to a dream. Returns (success, message)."""
        normalized_text = note_text.strip()
        if not normalized_text:
            return False, "Текст заметки пуст."

        tracer = get_tracer(__name__)

        async with self._session_factory() as session:
            with tracer.start_as_current_span("assistant.add_dream_note.resolve_dream"):
                dream = await self._resolve_note_target_dream(
                    session,
                    dream_id=dream_id,
                    chat_id=chat_id,
                )
            if dream is None:
                return False, "Не найден сон для добавления заметки."

            note = DreamNote(
                id=uuid.uuid4(),
                dream_id=dream.id,
                text=normalized_text,
                source="telegram",
                created_at=datetime.now(timezone.utc),
            )
            session.add(note)
            with tracer.start_as_current_span("assistant.add_dream_note.commit"):
                await session.commit()

        date_str = datetime.now(timezone.utc).strftime("%d.%m.%y")
        note_line = f"[Note {date_str}]: {normalized_text}"
        target_doc_id = self._resolve_note_doc_id(dream)
        gdocs_client = GDocsClient()
        try:
            with tracer.start_as_current_span("assistant.add_dream_note.write_google_doc"):
                placed = gdocs_client.insert_text_under_heading(
                    target_doc_id,
                    heading=_dream_doc_heading(dream),
                    text=note_line,
                )
                if not placed:
                    logger.info(
                        "Dream note heading not found; appending to Google Doc",
                        dream_id=str(dream.id),
                        doc_id=target_doc_id,
                    )
                    gdocs_client.append_text(target_doc_id, note_line)
        except GDocsWriteError:
            logger.warning(
                "Failed to write dream note to Google Doc",
                dream_id=str(dream.id),
                doc_id=target_doc_id,
            )
            return False, "Заметка сохранена в архиве, но не добавлена в Google Doc."
        except Exception:
            logger.error(
                "Unexpected error writing dream note to Google Doc",
                dream_id=str(dream.id),
                doc_id=target_doc_id,
            )
            return False, "Заметка сохранена в архиве, но не добавлена в Google Doc."

        if placed:
            return True, "Заметка добавлена под нужным сном."
        return True, "Заметка добавлена в конец Google Doc: заголовок сна не найден."

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
        if chat_id is not None:
            stmt = stmt.where(DreamEntry.source_doc_id == f"telegram:{chat_id}")
        stmt = stmt.order_by(DreamEntry.created_at.desc()).limit(1)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    def _resolve_note_doc_id(self, dream: DreamEntry) -> str:
        from app.shared.config import get_effective_google_doc_id

        if dream.source_doc_id.startswith("telegram:"):
            return get_effective_google_doc_id()
        return dream.source_doc_id


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
    clean_title = _DATE_PREFIX_RE.sub("", dream.title).strip()
    if dream.date is None:
        return clean_title
    return f"{dream.date.strftime('%d.%m.%y')} - {clean_title}"


_DATE_PREFIX_RE = re.compile(r"^\d{2}\.\d{2}\.\d{2,4}[\s\-,]+")
_WORD_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё]+")
_DEFAULT_APPLICATION_TIMEZONE = "Asia/Tbilisi"
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


def _sanitize_write_error(error: str) -> str:
    sanitized = re.sub(r"[\r\n\t]+", " ", error).strip()
    sanitized = re.sub(r"(token|secret|key)=\S+", r"\1=<redacted>", sanitized, flags=re.IGNORECASE)
    return sanitized[:300]


def _resolve_dream_title(
    raw_text: str, *, title: str | None, dream_date: date | None = None
) -> str:
    if title is not None and title.strip():
        return _strip_date_prefix(title.strip())
    return _generate_dream_title(raw_text, dream_date=dream_date)


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
    return f"о {' '.join(words)}"


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
