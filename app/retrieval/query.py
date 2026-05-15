from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.retrieval.types import (
    EmbeddingClient,
    OpenAIEmbeddingClient as SharedOpenAIEmbeddingClient,
    OpenAIEmbeddingHTTPError,
)
from app.shared.config import get_settings
from app.shared.tracing import get_tracer

RRF_K = 60
VECTOR_CANDIDATE_LIMIT = 20
FTS_CANDIDATE_LIMIT = 20
RESULT_LIMIT = 20

logger = logging.getLogger(__name__)
QUERY_EXPANSION_MODEL = "claude-haiku-4-5-20251001"
QUERY_EXPANSION_SYSTEM_PROMPT = (
    "Expand the following dream search query with related symbolic and thematic synonyms. "
    "Return only the expanded query, no explanation."
)
RELIGIOUS_QUERY_EXPANSION_TERMS = (
    "молитва",
    "песнопение",
    "богослужение",
    "церковь",
    "храм",
    "икона",
    "Христос",
    "Бог",
    "Рождество",
)
RELIGIOUS_QUERY_MARKERS = (
    "молитв",
    "песноп",
    "богослуж",
    "церков",
    "религиоз",
    "храм",
    "икон",
    "христ",
    "рождествен",
)
DIVINE_NAME_RE = re.compile(r"\bбог(?:а|у|ом|е)?\b", re.IGNORECASE)
BROAD_QUERY_MARKERS = ("сюжет", "мотив", "тема", "образ")
CONCRETE_IMAGE_QUERY_MARKERS = (
    "сон с ",
    "сон со ",
    "сны с ",
    "сны со ",
    "найди ",
    "найти ",
    "где есть ",
    "где была ",
    "где был ",
    "где были ",
    "в котором есть ",
    "в которых есть ",
)
CONCRETE_IMAGE_QUERY_STOPWORDS = frozenset(
    {
        "сон",
        "сны",
        "сне",
        "сновидение",
        "сновидения",
        "найди",
        "найти",
        "покажи",
        "где",
        "есть",
        "был",
        "была",
        "было",
        "были",
        "про",
        "об",
        "о",
        "с",
        "со",
        "в",
        "во",
        "на",
        "и",
        "или",
        "котором",
        "которых",
        "который",
        "которая",
    }
)
RELIGIOUS_MULTI_QUERY_PROBES = (
    "церковь храм богослужение",
    "молитва песнопение Рождество",
    "икона Христос Бог",
)


@dataclass(frozen=True)
class FragmentMatch:
    text: str
    match_type: str
    char_offset: int


@dataclass(frozen=True)
class EvidenceBlock:
    dream_id: uuid.UUID
    date: date | None
    title: str | None
    chunk_text: str
    relevance_score: float
    matched_fragments: list[FragmentMatch]


@dataclass(frozen=True)
class InsufficientEvidence:
    reason: str


class QueryEmbeddingError(Exception):
    def __init__(self, status_code: int, query_length: int) -> None:
        self.status_code = status_code
        self.query_length = query_length
        super().__init__(
            f"Embedding request failed with status_code={status_code} for query_length={query_length}"
        )


class OpenAIEmbeddingClient(SharedOpenAIEmbeddingClient):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            return await super().embed(
                texts,
                span_attributes={"query_length": len(texts[0]) if texts else 0},
                error_context={"query_length": len(texts)},
            )
        except OpenAIEmbeddingHTTPError as exc:
            raise QueryEmbeddingError(exc.status_code, exc.error_context["query_length"]) from exc


class RagQueryService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        embedding_client: EmbeddingClient | None = None,
        relevance_threshold: float | None = None,
    ) -> None:
        settings = get_settings()
        self._session_factory = session_factory
        self._embedding_client = embedding_client or OpenAIEmbeddingClient()
        self._relevance_threshold = (
            relevance_threshold if relevance_threshold is not None else settings.RETRIEVAL_THRESHOLD
        )

    async def retrieve(self, query: str) -> list[EvidenceBlock] | InsufficientEvidence:
        start = time.monotonic()
        cleaned_query = query.strip()
        tracer = get_tracer(__name__)

        with tracer.start_as_current_span("rag_query.retrieve") as span:
            if not cleaned_query:
                result = InsufficientEvidence(reason="Query is empty")
                logger.info("insufficient_evidence", extra={"reason": result.reason})
                elapsed_ms = int((time.monotonic() - start) * 1000)
                span.set_attribute("retrieval_ms", elapsed_ms)
                return result

            span.set_attribute("query_length", len(cleaned_query))
            span.set_attribute("relevance_threshold", self._relevance_threshold)

            expanded_query = await self._expand_query_terms(cleaned_query)
            probes = _build_retrieval_probes(cleaned_query, expanded_query)
            rows = await self._search_probes(probes)
            span.set_attribute("probe_count", len(probes))
            elapsed_ms = int((time.monotonic() - start) * 1000)
            span.set_attribute("retrieval_ms", elapsed_ms)

        if not rows:
            result = InsufficientEvidence(reason="No evidence met retrieval threshold")
            logger.info("insufficient_evidence", extra={"reason": result.reason})
            return result

        return [
            EvidenceBlock(
                dream_id=row["dream_id"],
                date=row["date"],
                title=row["title"],
                chunk_text=row["chunk_text"],
                relevance_score=float(row["relevance_score"]),
                matched_fragments=_coerce_fragments(row["matched_fragments"]),
            )
            for row in rows
        ]

    async def exact_search(self, query: str) -> list[dict[str, Any]]:
        """Pure FTS search - no embedding, no threshold, limit 20."""
        tracer = get_tracer(__name__)
        statement = text(
            """
            SELECT
                dc.dream_id,
                de.date,
                de.title,
                dc.chunk_text
            FROM dream_chunks AS dc
            JOIN dream_entries AS de ON de.id = dc.dream_id
            WHERE
                to_tsvector('russian', dc.chunk_text) @@ websearch_to_tsquery('russian', :query)
                OR to_tsvector('simple', dc.chunk_text) @@ websearch_to_tsquery('simple', :query)
            ORDER BY GREATEST(
                ts_rank_cd(
                    to_tsvector('russian', dc.chunk_text),
                    websearch_to_tsquery('russian', :query)
                ),
                ts_rank_cd(
                    to_tsvector('simple', dc.chunk_text),
                    websearch_to_tsquery('simple', :query)
                )
            ) DESC,
            de.date DESC
            LIMIT 20
            """
        )
        with tracer.start_as_current_span("db.query.rag_query.exact_search") as span:
            span.set_attribute("query_length", len(query))
            async with self._session_factory() as session:
                result = await session.execute(statement, {"query": query})
        return [dict(row) for row in result.mappings().all()]

    async def _expand_query_terms(self, query: str) -> str:
        tracer = get_tracer(__name__)
        deterministic_query = _apply_deterministic_query_profiles(query)

        try:
            with tracer.start_as_current_span("rag_query.expand_query") as span:
                span.set_attribute("query_length", len(query))
                client = _get_anthropic_client_cls()(api_key=get_settings().ANTHROPIC_API_KEY)
                with tracer.start_as_current_span("anthropic.messages.create"):
                    response = await client.messages.create(
                        model=QUERY_EXPANSION_MODEL,
                        max_tokens=200,
                        system=QUERY_EXPANSION_SYSTEM_PROMPT,
                        messages=[{"role": "user", "content": deterministic_query}],
                    )
        except Exception as exc:
            logger.warning(
                "query_expansion_failed",
                extra={"query_length": len(query), "error_type": type(exc).__name__},
            )
            return deterministic_query

        content = getattr(response, "content", [])
        text_blocks = [
            block.text
            for block in content
            if getattr(block, "type", None) == "text" and getattr(block, "text", None)
        ]
        expanded_query = "\n".join(text_blocks).strip()
        if not expanded_query:
            return deterministic_query
        return _merge_query_terms(deterministic_query, expanded_query)

    async def _embed_query(self, query: str) -> list[float]:
        tracer = get_tracer(__name__)

        with tracer.start_as_current_span("rag_query.embed_query") as span:
            span.set_attribute("query_length", len(query))
            embeddings = await self._embedding_client.embed([query])

        if not embeddings:
            raise ValueError("Embedding client returned no embeddings for query")

        return embeddings[0]

    async def _search_probes(self, probes: list[str]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for probe in probes:
            query_embedding = await self._embed_query(probe)
            rows.extend(await self._search(probe, query_embedding))
        return _merge_probe_rows(rows)

    async def _search(self, query: str, query_embedding: list[float]) -> list[dict[str, Any]]:
        tracer = get_tracer(__name__)
        statement = text(
            """
            WITH cosine_candidates AS (
                SELECT
                    dc.id,
                    dc.dream_id,
                    de.date,
                    de.title,
                    dc.chunk_text,
                    1 - (dc.embedding <=> CAST(:query_embedding AS vector)) AS cosine_similarity,
                    ROW_NUMBER() OVER (ORDER BY dc.embedding <=> CAST(:query_embedding AS vector)) AS rank_cosine
                FROM dream_chunks AS dc
                JOIN dream_entries AS de ON de.id = dc.dream_id
                WHERE dc.embedding IS NOT NULL
                ORDER BY dc.embedding <=> CAST(:query_embedding AS vector)
                LIMIT :vector_candidate_limit
            ),
            fts_candidates AS (
                SELECT
                    raw_fts.id,
                    raw_fts.dream_id,
                    raw_fts.date,
                    raw_fts.title,
                    raw_fts.chunk_text,
                    raw_fts.fts_rank_raw / (1 + raw_fts.fts_rank_raw) AS fts_rank,
                    ROW_NUMBER() OVER (
                        ORDER BY raw_fts.fts_rank_raw DESC,
                        raw_fts.created_at DESC
                    ) AS rank_fts
                FROM (
                    SELECT
                        dc.id,
                        dc.dream_id,
                        de.date,
                        de.title,
                        dc.chunk_text,
                        dc.created_at,
                        GREATEST(
                            ts_rank_cd(
                                to_tsvector('russian', dc.chunk_text),
                                websearch_to_tsquery('russian', :fts_query)
                            ),
                            ts_rank_cd(
                                to_tsvector('simple', dc.chunk_text),
                                websearch_to_tsquery('simple', :fts_query)
                            )
                        ) AS fts_rank_raw
                    FROM dream_chunks AS dc
                    JOIN dream_entries AS de ON de.id = dc.dream_id
                    WHERE
                        to_tsvector('russian', dc.chunk_text)
                            @@ websearch_to_tsquery('russian', :fts_query)
                        OR to_tsvector('simple', dc.chunk_text)
                            @@ websearch_to_tsquery('simple', :fts_query)
                ) AS raw_fts
                ORDER BY raw_fts.fts_rank_raw DESC,
                raw_fts.created_at DESC
                LIMIT :fts_candidate_limit
            ),
            fused AS (
                SELECT
                    COALESCE(c.id, f.id) AS chunk_id,
                    COALESCE(c.dream_id, f.dream_id) AS dream_id,
                    COALESCE(c.date, f.date) AS date,
                    COALESCE(c.title, f.title) AS title,
                    COALESCE(c.chunk_text, f.chunk_text) AS chunk_text,
                    c.cosine_similarity,
                    f.fts_rank,
                    c.rank_cosine,
                    f.rank_fts,
                    COALESCE(1.0 / (:rrf_k + c.rank_cosine), 0.0)
                    + COALESCE(1.0 / (:rrf_k + f.rank_fts), 0.0) AS fused_score
                FROM cosine_candidates AS c
                FULL OUTER JOIN fts_candidates AS f ON c.id = f.id
            )
            SELECT
                fused.dream_id,
                fused.date,
                fused.title,
                fused.chunk_text,
                GREATEST(
                    COALESCE(fused.cosine_similarity, 0.0),
                    COALESCE(fused.fts_rank, 0.0)
                ) AS relevance_score,
                COALESCE(
                    (
                        SELECT jsonb_agg(
                            jsonb_build_object(
                                'text',
                                fragment_text,
                                'match_type',
                                'semantic',
                                'char_offset',
                                0
                            )
                            ORDER BY fragment_text
                        )
                        FROM (
                            SELECT DISTINCT fragment->>'text' AS fragment_text
                            FROM dream_themes AS dt
                            CROSS JOIN LATERAL jsonb_array_elements(dt.fragments) AS fragment
                            WHERE dt.dream_id = fused.dream_id
                              AND dt.deprecated = false
                              AND dt.status IN ('draft', 'confirmed')
                              AND fragment ? 'text'
                              AND NULLIF(fragment->>'text', '') IS NOT NULL
                              AND POSITION(fragment->>'text' IN fused.chunk_text) > 0
                        ) AS matched_fragments
                    ),
                    '[]'::jsonb
                ) AS matched_fragments
            FROM fused
            WHERE GREATEST(
                COALESCE(fused.cosine_similarity, 0.0),
                COALESCE(fused.fts_rank, 0.0)
            ) >= :relevance_threshold
            ORDER BY fused.fused_score DESC, relevance_score DESC
            LIMIT :result_limit
            """
        )

        params = {
            "query_embedding": _embedding_to_vector_literal(query_embedding),
            "fts_query": query,
            "rrf_k": RRF_K,
            "vector_candidate_limit": VECTOR_CANDIDATE_LIMIT,
            "fts_candidate_limit": FTS_CANDIDATE_LIMIT,
            "relevance_threshold": self._relevance_threshold,
            "result_limit": RESULT_LIMIT,
        }

        with tracer.start_as_current_span("db.query.rag_query.search") as span:
            span.set_attribute("vector_candidate_limit", VECTOR_CANDIDATE_LIMIT)
            span.set_attribute("fts_candidate_limit", FTS_CANDIDATE_LIMIT)
            async with self._session_factory() as session:
                result = await session.execute(statement, params)

        return [dict(row) for row in result.mappings().all()]


def _coerce_fragments(value: Any) -> list[FragmentMatch]:
    if value is None:
        return []
    if isinstance(value, list):
        fragments: list[FragmentMatch] = []
        for fragment in value:
            if not isinstance(fragment, dict):
                continue
            text_value = fragment.get("text")
            match_type = fragment.get("match_type")
            char_offset = fragment.get("char_offset")
            if not isinstance(text_value, str) or not isinstance(match_type, str):
                continue
            if not isinstance(char_offset, int):
                char_offset = 0
            fragments.append(
                FragmentMatch(
                    text=text_value,
                    match_type=match_type,
                    char_offset=char_offset,
                )
            )
        return fragments
    return []


def _embedding_to_vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in embedding) + "]"


def _apply_deterministic_query_profiles(query: str) -> str:
    if not _matches_religious_query_profile(query):
        return query
    return _merge_query_terms(query, " ".join(RELIGIOUS_QUERY_EXPANSION_TERMS))


def _build_retrieval_probes(original_query: str, expanded_query: str) -> list[str]:
    probes = [expanded_query]
    if _matches_broad_religious_query(original_query):
        probes.extend(
            _merge_query_terms(original_query, probe) for probe in RELIGIOUS_MULTI_QUERY_PROBES
        )
    return _dedupe_strings(probes)


def extract_concrete_image_query(query: str) -> str | None:
    normalized = query.casefold()
    if not any(marker in normalized for marker in CONCRETE_IMAGE_QUERY_MARKERS):
        return None

    tokens = re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", normalized)
    content_tokens = [
        _normalize_concrete_image_token(token)
        for token in tokens
        if token not in CONCRETE_IMAGE_QUERY_STOPWORDS and len(token) >= 3
    ]
    content_tokens = _dedupe_strings(content_tokens)
    if not content_tokens or len(content_tokens) > 3:
        return None
    return " ".join(content_tokens)


def _normalize_concrete_image_token(token: str) -> str:
    if not re.fullmatch(r"[а-яё]+", token):
        return token
    if len(token) > 4 and token.endswith(("ою", "ею")):
        return token[:-2] + "а"
    if len(token) > 4 and token.endswith(("ой", "ей")):
        return token[:-2] + "а"
    if len(token) > 3 and token.endswith("у"):
        return token[:-1] + "а"
    if len(token) > 3 and token.endswith("ю"):
        return token[:-1] + "я"
    return token


def _matches_religious_query_profile(query: str) -> bool:
    normalized = query.casefold()
    return any(marker in normalized for marker in RELIGIOUS_QUERY_MARKERS) or bool(
        DIVINE_NAME_RE.search(query)
    )


def _matches_broad_religious_query(query: str) -> bool:
    normalized = query.casefold()
    return _matches_religious_query_profile(query) and any(
        marker in normalized for marker in BROAD_QUERY_MARKERS
    )


def _merge_probe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[uuid.UUID, dict[str, Any]] = {}
    order: list[uuid.UUID] = []

    for row in rows:
        dream_id = row["dream_id"]
        if dream_id not in grouped:
            grouped[dream_id] = dict(row)
            grouped[dream_id]["matched_fragments"] = _dedupe_fragment_dicts(
                _fragment_dicts(row.get("matched_fragments"))
            )
            order.append(dream_id)
            continue

        existing = grouped[dream_id]
        existing_score = float(existing.get("relevance_score") or 0.0)
        row_score = float(row.get("relevance_score") or 0.0)
        if row_score > existing_score:
            existing["date"] = row["date"]
            existing["title"] = row["title"]
            existing["relevance_score"] = row_score

        existing["chunk_text"] = _merge_chunk_texts(
            str(existing.get("chunk_text") or ""),
            str(row.get("chunk_text") or ""),
        )
        existing["matched_fragments"] = _dedupe_fragment_dicts(
            _fragment_dicts(existing.get("matched_fragments"))
            + _fragment_dicts(row.get("matched_fragments"))
        )

    return sorted(
        (grouped[dream_id] for dream_id in order),
        key=lambda item: float(item.get("relevance_score") or 0.0),
        reverse=True,
    )


def _merge_chunk_texts(existing: str, new: str) -> str:
    if not new or new == existing:
        return existing
    chunks = existing.split("\n---\n") if existing else []
    if new not in chunks:
        chunks.append(new)
    return "\n---\n".join(chunks)


def _fragment_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [fragment for fragment in value if isinstance(fragment, dict)]


def _dedupe_fragment_dicts(fragments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for fragment in fragments:
        text_value = fragment.get("text")
        match_type = fragment.get("match_type")
        char_offset = fragment.get("char_offset")
        if not isinstance(text_value, str) or not isinstance(match_type, str):
            continue
        if not isinstance(char_offset, int):
            char_offset = 0
        key = (text_value, match_type, char_offset)
        if key in seen:
            continue
        seen.add(key)
        deduped.append({"text": text_value, "match_type": match_type, "char_offset": char_offset})
    return deduped


def _dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(value)
    return deduped


def _merge_query_terms(*parts: str) -> str:
    tokens: list[str] = []
    seen: set[str] = set()
    for part in parts:
        for token in part.split():
            normalized = token.casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            tokens.append(token)
    return " ".join(tokens)


def _get_anthropic_client_cls():
    from anthropic import AsyncAnthropic

    return AsyncAnthropic
