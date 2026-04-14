from __future__ import annotations

import re
import uuid
from functools import lru_cache

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.models.dream import DreamEntry
from app.models.theme import DreamTheme
from app.retrieval.query import InsufficientEvidence, RagQueryService
from app.shared.config import get_settings
from app.shared.tracing import get_tracer

router = APIRouter()


class SearchThemeMatch(BaseModel):
    category_id: uuid.UUID
    match_type: str
    status: str


class SearchResultItem(BaseModel):
    dream_id: uuid.UUID
    date: str | None
    matched_fragments: list[str]
    relevance_score: float
    theme_matches: list[SearchThemeMatch]


class SearchResultsResponse(BaseModel):
    query: str
    expanded_terms: list[str]
    results: list[SearchResultItem]


class SearchInsufficientEvidenceResponse(BaseModel):
    result: str
    query: str
    expanded_terms: list[str]


class DreamThemeResponseItem(BaseModel):
    category_id: uuid.UUID
    salience: float
    match_type: str
    status: str
    fragments: list[dict[str, object]]


class DreamThemesResponse(BaseModel):
    dream_id: uuid.UUID
    themes: list[DreamThemeResponseItem]


@router.get(
    "/search",
    response_model=SearchResultsResponse | SearchInsufficientEvidenceResponse,
)
async def search(
    q: str = Query(..., min_length=1),
    theme_ids: list[uuid.UUID] | None = Query(default=None),
) -> SearchResultsResponse | SearchInsufficientEvidenceResponse:
    expanded_terms = _expand_terms(q)
    retrieval = await _get_rag_query_service().retrieve(q)

    if isinstance(retrieval, InsufficientEvidence):
        return SearchInsufficientEvidenceResponse(
            result="insufficient_evidence",
            query=q,
            expanded_terms=expanded_terms,
        )

    theme_filter_ids = set(theme_ids or [])
    tracer = get_tracer(__name__)

    async with _get_session_factory()() as session:
        theme_map = await _load_theme_matches(
            session,
            [block.dream_id for block in retrieval],
            tracer=tracer,
        )

    filtered_results = [
        SearchResultItem(
            dream_id=block.dream_id,
            date=block.date.isoformat() if block.date is not None else None,
            matched_fragments=block.matched_fragments,
            relevance_score=block.relevance_score,
            theme_matches=theme_map.get(block.dream_id, []),
        )
        for block in retrieval
        if not theme_filter_ids or _matches_theme_filter(theme_map.get(block.dream_id, []), theme_filter_ids)
    ]

    if not filtered_results:
        return SearchInsufficientEvidenceResponse(
            result="insufficient_evidence",
            query=q,
            expanded_terms=expanded_terms,
        )

    return SearchResultsResponse(
        query=q,
        expanded_terms=expanded_terms,
        results=filtered_results[:5],
    )


@router.get("/dreams/{dream_id}/themes", response_model=DreamThemesResponse)
async def get_dream_themes(dream_id: uuid.UUID) -> DreamThemesResponse:
    tracer = get_tracer(__name__)

    async with _get_session_factory()() as session:
        with tracer.start_as_current_span("db.query.search.dream_exists"):
            dream = await session.get(DreamEntry, dream_id)

        if dream is None:
            raise HTTPException(status_code=404, detail="Dream not found")

        with tracer.start_as_current_span("db.query.search.dream_themes"):
            result = await session.execute(
                select(DreamTheme)
                .where(
                    DreamTheme.dream_id == dream_id,
                    DreamTheme.deprecated.is_(False),
                    DreamTheme.status.in_(("draft", "confirmed")),
                )
                .order_by(DreamTheme.salience.desc(), DreamTheme.created_at.desc())
            )

    return DreamThemesResponse(
        dream_id=dream_id,
        themes=[
            DreamThemeResponseItem(
                category_id=theme.category_id,
                salience=theme.salience,
                match_type=theme.match_type,
                status=theme.status,
                fragments=_coerce_theme_fragments(theme.fragments),
            )
            for theme in result.scalars().all()
        ],
    )


@lru_cache(maxsize=1)
def _get_engine() -> AsyncEngine:
    return create_async_engine(get_settings().DATABASE_URL)


@lru_cache(maxsize=1)
def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(_get_engine(), expire_on_commit=False)


@lru_cache(maxsize=1)
def _get_rag_query_service() -> RagQueryService:
    return RagQueryService(session_factory=_get_session_factory())


async def _load_theme_matches(
    session: AsyncSession,
    dream_ids: list[uuid.UUID],
    *,
    tracer,
) -> dict[uuid.UUID, list[SearchThemeMatch]]:
    if not dream_ids:
        return {}

    with tracer.start_as_current_span("db.query.search.theme_matches"):
        result = await session.execute(
            select(DreamTheme)
            .where(
                DreamTheme.dream_id.in_(dream_ids),
                DreamTheme.deprecated.is_(False),
                DreamTheme.status.in_(("draft", "confirmed")),
            )
            .order_by(DreamTheme.salience.desc(), DreamTheme.created_at.desc())
        )

    matches: dict[uuid.UUID, list[SearchThemeMatch]] = {}
    for theme in result.scalars().all():
        matches.setdefault(theme.dream_id, []).append(
            SearchThemeMatch(
                category_id=theme.category_id,
                match_type=theme.match_type,
                status=theme.status,
            )
        )
    return matches


def _matches_theme_filter(
    theme_matches: list[SearchThemeMatch],
    theme_filter_ids: set[uuid.UUID],
) -> bool:
    return any(
        theme.status == "confirmed" and theme.category_id in theme_filter_ids for theme in theme_matches
    )


def _expand_terms(query: str) -> list[str]:
    cleaned_query = query.strip()
    if not cleaned_query:
        return []

    expanded_terms = [cleaned_query]
    expanded_terms.extend(
        token
        for token in re.findall(r"[A-Za-z0-9']+", cleaned_query.lower())
        if token != cleaned_query.lower()
    )

    deduped_terms: list[str] = []
    for term in expanded_terms:
        if term not in deduped_terms:
            deduped_terms.append(term)
    return deduped_terms


def _coerce_theme_fragments(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [fragment for fragment in value if isinstance(fragment, dict)]
