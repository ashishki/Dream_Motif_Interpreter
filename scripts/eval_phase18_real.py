from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.dream import DreamChunk, DreamEntry
from app.retrieval.ingestion import EMBEDDING_DIMENSIONS
from app.retrieval.query import (
    EvidenceBlock,
    FragmentMatch,
    InsufficientEvidence,
    RagQueryService,
    _apply_deterministic_query_profiles,
    _build_retrieval_probes,
)
from app.shared.config import get_settings

PHASE18_QUERIES = (
    "молитва",
    "где упоминается молитва",
    "где фигурирует молитва",
    "религиозные сюжеты",
    "церковь",
    "рождественское песнопение",
)
EVAL_MODE_AUTO = "auto"
EVAL_MODE_LIVE = "live"
EVAL_MODE_FTS = "fts"
FTS_PROBE_STOPWORDS = {
    "где",
    "упоминается",
    "фигурирует",
    "найди",
    "сны",
    "сон",
    "религиозные",
    "сюжеты",
}


@dataclass(frozen=True)
class RealEvalResult:
    query: str
    status: str
    result_count: int
    evidence_count: int
    top_titles: tuple[str, ...]


class ZeroEmbeddingClient:
    async def embed(self, texts: list[str], *, dream_id: str | None = None) -> list[list[float]]:
        del dream_id
        return [[0.0] * EMBEDDING_DIMENSIONS for _ in texts]


async def run_real_eval(
    *,
    database_url: str | None = None,
    queries: Sequence[str] = PHASE18_QUERIES,
    limit: int = 5,
    mode: str = EVAL_MODE_AUTO,
) -> list[RealEvalResult]:
    effective_database_url = (
        database_url or os.getenv("DATABASE_URL") or get_settings().DATABASE_URL
    )
    if not effective_database_url:
        raise RuntimeError("DATABASE_URL is required for read-only Phase 18 real eval")

    os.environ["DATABASE_URL"] = effective_database_url
    get_settings.cache_clear()

    engine = create_async_engine(effective_database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await _assert_archive_is_indexed(session_factory)
        resolved_mode = _resolve_eval_mode(mode)
        retriever = _build_retriever(session_factory=session_factory, mode=resolved_mode)
        results: list[RealEvalResult] = []
        for query in queries:
            result = await retriever.retrieve(query)
            results.append(_summarize_result(query=query, result=result, limit=limit))
            _print_result(query=query, result=result, limit=limit)
        return results
    finally:
        await engine.dispose()


class FtsOnlyRetrievalService:
    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._rag_query_service = RagQueryService(
            session_factory=session_factory,
            embedding_client=ZeroEmbeddingClient(),
        )

    async def retrieve(self, query: str) -> list[EvidenceBlock] | InsufficientEvidence:
        expanded_query = _apply_deterministic_query_profiles(query)
        probes = _build_retrieval_probes(query, expanded_query)
        blocks_by_dream: dict[str, EvidenceBlock] = {}

        for probe in _fts_probe_terms(probes):
            rows = await self._rag_query_service.exact_search(probe)
            for row in rows:
                dream_id = row["dream_id"]
                if str(dream_id) in blocks_by_dream:
                    continue
                chunk_text = row.get("chunk_text", "")
                blocks_by_dream[str(dream_id)] = EvidenceBlock(
                    dream_id=dream_id,
                    date=row.get("date"),
                    title=row.get("title"),
                    chunk_text=chunk_text,
                    relevance_score=1.0,
                    matched_fragments=[
                        FragmentMatch(text=fragment, match_type="fts", char_offset=0)
                        for fragment in _matching_fragments(chunk_text, probe)
                    ],
                )

        blocks = list(blocks_by_dream.values())
        if not blocks:
            return InsufficientEvidence(reason="No FTS evidence matched Phase 18 probes")
        return blocks


async def _assert_archive_is_indexed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        dream_count = await session.scalar(select(func.count()).select_from(DreamEntry))
        chunk_count = await session.scalar(select(func.count()).select_from(DreamChunk))

    if not dream_count:
        raise RuntimeError("No dream_entries found; run sync/index before real eval")
    if not chunk_count:
        raise RuntimeError("No dream_chunks found; run indexing before real eval")


def _summarize_result(
    *,
    query: str,
    result: list[EvidenceBlock] | InsufficientEvidence,
    limit: int,
) -> RealEvalResult:
    if isinstance(result, InsufficientEvidence):
        return RealEvalResult(
            query=query,
            status="insufficient_evidence",
            result_count=0,
            evidence_count=0,
            top_titles=(),
        )

    top = result[:limit]
    return RealEvalResult(
        query=query,
        status="ok",
        result_count=len(result),
        evidence_count=sum(1 for block in top if _evidence_text(block)),
        top_titles=tuple((block.title or "без названия") for block in top),
    )


def _print_result(
    *,
    query: str,
    result: list[EvidenceBlock] | InsufficientEvidence,
    limit: int,
) -> None:
    print(f"\n## {query}")
    if isinstance(result, InsufficientEvidence):
        print("status: insufficient_evidence")
        print(f"reason: {result.reason}")
        return

    print("status: ok")
    print(f"results: {len(result)}")
    for index, block in enumerate(result[:limit], start=1):
        title = block.title or "без названия"
        date_label = block.date.isoformat() if block.date is not None else "unknown date"
        evidence_text = _evidence_text(block)
        print(f"{index}. dream_id: {block.dream_id}")
        print(f"   date: {date_label}")
        print(f"   title: {title}")
        print(f"   score: {block.relevance_score:.2f}")
        print(f"   evidence_text: {evidence_text!r}")


def _evidence_text(block: EvidenceBlock) -> str:
    if block.matched_fragments:
        return "\n---\n".join(fragment.text for fragment in block.matched_fragments)
    return block.chunk_text.strip()


def _build_retriever(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    mode: str,
) -> RagQueryService | FtsOnlyRetrievalService:
    if mode == EVAL_MODE_FTS:
        return FtsOnlyRetrievalService(session_factory=session_factory)
    return RagQueryService(session_factory=session_factory)


def _resolve_eval_mode(mode: str) -> str:
    if mode not in {EVAL_MODE_AUTO, EVAL_MODE_LIVE, EVAL_MODE_FTS}:
        raise ValueError(f"Unknown eval mode: {mode}")
    if mode != EVAL_MODE_AUTO:
        return mode
    api_key = os.getenv("OPENAI_API_KEY") or get_settings().OPENAI_API_KEY
    if not api_key or api_key.startswith("test-") or "placeholder" in api_key:
        return EVAL_MODE_FTS
    return EVAL_MODE_LIVE


def _matching_fragments(chunk_text: str, query: str) -> list[str]:
    normalized = chunk_text.casefold()
    matches: list[str] = []
    for token in query.split():
        clean_token = token.strip().casefold()
        if len(clean_token) < 3 or clean_token not in normalized:
            continue
        matches.append(token)
    return matches[:5] or [chunk_text[:240]]


def _fts_probe_terms(probes: Sequence[str]) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for probe in probes:
        for token in probe.split():
            clean_token = token.strip(".,;:!?()[]{}\"'«»").casefold()
            if len(clean_token) < 4 or clean_token in seen or clean_token in FTS_PROBE_STOPWORDS:
                continue
            seen.add(clean_token)
            terms.append(token.strip(".,;:!?()[]{}\"'«»"))
    return tuple(terms)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only Phase 18 retrieval eval against an already indexed archive."
    )
    parser.add_argument("--database-url", default=None, help="Override DATABASE_URL")
    parser.add_argument("--limit", type=int, default=5, help="Max results to print per query")
    parser.add_argument(
        "--mode",
        choices=[EVAL_MODE_AUTO, EVAL_MODE_LIVE, EVAL_MODE_FTS],
        default=EVAL_MODE_AUTO,
        help="auto uses live hybrid retrieval only when OPENAI_API_KEY looks real; otherwise FTS-only.",
    )
    parser.add_argument("queries", nargs="*", help="Optional custom queries")
    args = parser.parse_args()
    queries = tuple(args.queries) if args.queries else PHASE18_QUERIES
    asyncio.run(
        run_real_eval(
            database_url=args.database_url,
            queries=queries,
            limit=args.limit,
            mode=args.mode,
        )
    )


if __name__ == "__main__":
    main()
