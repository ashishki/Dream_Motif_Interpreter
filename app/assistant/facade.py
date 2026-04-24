from __future__ import annotations

import hashlib
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.dream import DreamEntry
from app.models.motif import MotifInduction
from app.models.theme import DreamTheme, ThemeCategory
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


@dataclass(frozen=True)
class DreamSummary:
    id: uuid.UUID
    date: str | None
    title: str
    raw_text_preview: str
    theme_names: list[str]


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
    async def enqueue_ingest(self, *, job_id: uuid.UUID, doc_id: str) -> None: ...


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
            if did not in grouped:
                grouped[did] = item
            else:
                existing = grouped[did]
                new_score = max(existing.relevance_score, item.relevance_score)
                new_text = existing.chunk_text + '\n---\n' + item.chunk_text
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
                result = await session.execute(
                    select(DreamTheme, ThemeCategory.name)
                    .join(ThemeCategory, ThemeCategory.id == DreamTheme.category_id)
                    .where(DreamTheme.dream_id == dream_id)
                    .order_by(DreamTheme.created_at.asc(), DreamTheme.id.asc())
                )

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
                for theme, category_name in result.all()
            ],
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

        resolved_title = _resolve_dream_title(
            normalized_text,
            title=title,
            dream_date=dream_date,
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
                date=dream_date,
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

        written = await self.write_dream_to_google_doc(dream_id=dream.id)

        return CreatedDreamItem(
            id=dream.id,
            date=dream.date.isoformat() if dream.date is not None else None,
            title=dream.title,
            word_count=dream.word_count,
            source_doc_id=dream.source_doc_id,
            created_at=dream.created_at.isoformat(),
            created=True,
            written_to_google_doc=written,
        )

    async def write_dream_to_google_doc(
        self, dream_id: uuid.UUID, doc_id: str | None = None
    ) -> bool:
        """Write a dream entry to Google Doc. Returns True on success, False on failure."""
        from app.shared.config import get_effective_google_doc_id

        resolved_doc_id = doc_id or get_effective_google_doc_id()
        tracer = get_tracer(__name__)
        with tracer.start_as_current_span("assistant.write_dream_to_google_doc"):
            try:
                async with self._session_factory() as session:
                    dream = await session.get(DreamEntry, dream_id)
                if dream is None:
                    logger.warning(
                        "write_dream_to_google_doc: dream not found", dream_id=str(dream_id)
                    )
                    return False

                date_str = dream.date.strftime("%d.%m.%y") if dream.date else "??.??.??"
                title_str = (
                    dream.title.strip()
                    if dream.title and dream.title.strip()
                    else "без названия"
                )
                header = f"{date_str} - {title_str}"
                raw_text = dream.raw_text or ""
                formatted = f"{header}\n\n{raw_text}"

                client = GDocsClient()
                client.append_text(resolved_doc_id, formatted)
                logger.info(
                    "Dream written to Google Doc",
                    dream_id=str(dream_id),
                    doc_id=resolved_doc_id,
                )
                return True
            except GDocsWriteError as exc:
                logger.warning(
                    "Failed to write dream to Google Doc",
                    dream_id=str(dream_id),
                    doc_id=resolved_doc_id,
                    error=str(exc),
                )
                return False
            except Exception as exc:
                logger.error(
                    "Unexpected error writing dream to Google Doc",
                    dream_id=str(dream_id),
                    error=str(exc),
                )
                return False

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

    async def trigger_sync(self, doc_id: str = "") -> list[SyncJobRef]:
        from app.shared.config import get_all_doc_ids

        if self._sync_job_enqueuer is None:
            raise RuntimeError("AssistantFacade trigger_sync requires a sync job enqueuer")

        doc_ids = [doc_id] if doc_id.strip() else get_all_doc_ids()
        refs: list[SyncJobRef] = []
        for resolved_doc_id in doc_ids:
            job_id = uuid.uuid4()
            await self._sync_job_enqueuer.enqueue_ingest(job_id=job_id, doc_id=resolved_doc_id)
            refs.append(SyncJobRef(job_id=job_id, status="queued", doc_id=resolved_doc_id))
        return refs

    def get_archive_source(self) -> str:
        from app.shared.config import get_effective_google_doc_id

        return get_effective_google_doc_id()

    def set_archive_source(self, doc_id: str) -> str:
        from app.shared.config import set_google_doc_id_override

        set_google_doc_id_override(doc_id)
        return doc_id

    def list_archive_sources(self) -> list[str]:
        from app.shared.config import get_all_doc_ids

        return get_all_doc_ids()

    def add_archive_source(self, doc_id: str) -> list[str]:
        from app.shared.config import (
            get_all_doc_ids,
            get_settings,
            set_google_doc_ids_override,
        )

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


def _dream_summary_item(
    dream: DreamEntry, *, theme_names: list[str] | None = None
) -> DreamSummary:
    return DreamSummary(
        id=dream.id,
        date=dream.date.isoformat() if dream.date is not None else None,
        title=dream.title,
        raw_text_preview=(dream.raw_text or "")[:400],
        theme_names=theme_names or [],
    )


def _resolve_dream_title(
    raw_text: str, *, title: str | None, dream_date: date | None = None
) -> str:
    del raw_text

    def fmt_date(d: date | None) -> str:
        if d is None:
            d = datetime.now().date()
        return d.strftime("%d.%m.%y")

    if title is not None and title.strip():
        if dream_date is not None:
            return f"{fmt_date(dream_date)} - {title.strip()}"
        return title.strip()

    return f"{fmt_date(dream_date)}, без названия"


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
