from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.dream import DreamEntry
from app.models.theme import DreamTheme, ThemeCategory
from app.retrieval.query import EvidenceBlock, InsufficientEvidence, RagQueryService
from app.services.analysis import AnalysisService
from app.services.patterns import CoOccurrencePattern, PatternService, RecurringPattern
from app.services.versioning import VersioningService
from app.shared.tracing import get_tracer


@dataclass(frozen=True)
class SearchResultItem:
    dream_id: uuid.UUID
    date: date | None
    chunk_text: str
    relevance_score: float
    matched_fragments: list[dict[str, Any]]


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
    word_count: int
    source_doc_id: str
    created_at: str


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
    ) -> None:
        self._session_factory = session_factory
        self._rag_query_service = rag_query_service
        self._pattern_service = pattern_service
        self._versioning_service = versioning_service
        self._sync_job_enqueuer = sync_job_enqueuer
        self._analysis_service = analysis_service

    async def search_dreams(self, query: str) -> SearchResult:
        result = await self._rag_query_service.retrieve(query)
        if isinstance(result, InsufficientEvidence):
            return SearchResult(items=[], insufficient_reason=result.reason)

        return SearchResult(items=[_search_result_item(block) for block in result])

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

        return [_dream_summary_item(dream) for dream in result.scalars().all()]

    async def get_patterns(self) -> PatternSummary:
        async with self._session_factory() as session:
            recurring = await self._pattern_service.list_recurring_patterns(session)
            co_occurrence = await self._pattern_service.list_co_occurrence_patterns(session)

        return PatternSummary(
            recurring=[_recurring_pattern_item(pattern) for pattern in recurring],
            co_occurrence=[_co_occurrence_pattern_item(pattern) for pattern in co_occurrence],
        )

    async def get_theme_history(self, dream_id: uuid.UUID) -> list[ThemeHistoryEntry]:
        async with self._session_factory() as session:
            _, versions = await self._versioning_service.list_theme_history(session, dream_id=dream_id)

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

    async def trigger_sync(self, doc_id: str) -> SyncJobRef:
        if self._sync_job_enqueuer is None:
            raise RuntimeError("AssistantFacade trigger_sync requires a sync job enqueuer")

        job_id = uuid.uuid4()
        await self._sync_job_enqueuer.enqueue_ingest(job_id=job_id, doc_id=doc_id)
        return SyncJobRef(job_id=job_id, status="queued", doc_id=doc_id)


def _search_result_item(block: EvidenceBlock) -> SearchResultItem:
    return SearchResultItem(
        dream_id=block.dream_id,
        date=block.date,
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
    )


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


def _dream_summary_item(dream: DreamEntry) -> DreamSummary:
    return DreamSummary(
        id=dream.id,
        date=dream.date.isoformat() if dream.date is not None else None,
        title=dream.title,
        word_count=dream.word_count,
        source_doc_id=dream.source_doc_id,
        created_at=dream.created_at.isoformat(),
    )


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
