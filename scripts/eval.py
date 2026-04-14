from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import statistics
import time
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.models.dream import DreamChunk, DreamEntry
from app.retrieval.ingestion import EMBEDDING_DIMENSIONS, RagIngestionService
from app.retrieval.query import EvidenceBlock, InsufficientEvidence, RagQueryService
from app.shared.config import get_settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOCS_PATH = PROJECT_ROOT / "docs" / "retrieval_eval.md"
DEFAULT_FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "seed_dreams.json"
EVAL_DATE = "2026-04-13"
CORPUS_VERSION = "synthetic-20-entries"
DEFAULT_TASK_ID = "T12"
EVAL_SOURCE = f"scripts/eval.py against §Evaluation Dataset (10 queries), run {EVAL_DATE}"
QUERY_SECTION = "## Evaluation Dataset"
BASELINE_SECTION = "## Baseline Metrics"
CURRENT_SECTION = "## Current Metrics"
NO_ANSWER_SECTION = "## No-Answer Behavior Quality"
HISTORY_SECTION = "## Evaluation History"
_STOPWORDS = {
    "a",
    "across",
    "after",
    "all",
    "an",
    "and",
    "as",
    "at",
    "different",
    "dream",
    "dreams",
    "following",
    "in",
    "into",
    "more",
    "multiple",
    "of",
    "on",
    "than",
    "the",
    "to",
    "with",
}


@dataclass(frozen=True)
class EvalQuery:
    query_id: str
    query: str
    query_type: str
    expected_titles: tuple[str, ...]
    notes: str


@dataclass(frozen=True)
class SeedDream:
    source_doc_id: str
    title: str
    raw_text: str
    entry_date: date


@dataclass(frozen=True)
class RetrievedDream:
    dream_id: uuid.UUID
    title: str
    relevance_score: float


@dataclass(frozen=True)
class QueryOutcome:
    query: EvalQuery
    result: list[RetrievedDream] | InsufficientEvidence
    latency_ms: int


@dataclass(frozen=True)
class EvaluationMetrics:
    hit_at_3: float
    hit_at_5: float
    mrr: float
    citation_precision: float
    no_answer_accuracy: float
    median_retrieval_latency_ms: int
    p95_retrieval_latency_ms: int


class ZeroEmbeddingClient:
    async def embed(self, texts: list[str], *, dream_id: str | None = None) -> list[list[float]]:
        return [[0.0] * EMBEDDING_DIMENSIONS for _ in texts]


class StubRetrievalService:
    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def retrieve(self, query: str) -> list[RetrievedDream] | InsufficientEvidence:
        cleaned_query = query.strip()
        if not cleaned_query:
            return InsufficientEvidence(reason="Query is empty")

        query_terms = _tokenize(cleaned_query)
        if not query_terms:
            return InsufficientEvidence(reason="No evidence met retrieval threshold")

        async with self._session_factory() as session:
            result = await session.execute(
                select(DreamEntry.id, DreamEntry.title, DreamChunk.chunk_text)
                .join(DreamChunk, DreamChunk.dream_id == DreamEntry.id)
                .order_by(DreamEntry.date.asc(), DreamEntry.created_at.asc())
            )

        scored: list[RetrievedDream] = []
        for dream_id, title, chunk_text in result.all():
            score = _lexical_score(cleaned_query, query_terms, f"{title} {chunk_text}")
            if score <= 0:
                continue
            scored.append(
                RetrievedDream(
                    dream_id=dream_id,
                    title=title,
                    relevance_score=score,
                )
            )

        scored.sort(key=lambda item: item.relevance_score, reverse=True)
        top_results = scored[:5]
        if not top_results:
            return InsufficientEvidence(reason="No evidence met retrieval threshold")

        return top_results


def load_evaluation_dataset(markdown_path: Path = DEFAULT_DOCS_PATH) -> list[EvalQuery]:
    table = _extract_table(markdown_path.read_text(encoding="utf-8"), QUERY_SECTION)
    queries: list[EvalQuery] = []
    for row in table:
        expected_titles = tuple(
            part.strip()
            for part in row["Expected top document(s)"].split(";")
            if part.strip() and part.strip() != "— (should return insufficient_evidence)"
        )
        queries.append(
            EvalQuery(
                query_id=row["ID"],
                query=row["Query"],
                query_type=row["Query Type"],
                expected_titles=expected_titles,
                notes=row["Notes"],
            )
        )
    return queries


def load_evaluation_history(markdown_path: Path = DEFAULT_DOCS_PATH) -> list[dict[str, str]]:
    return _extract_table(markdown_path.read_text(encoding="utf-8"), HISTORY_SECTION)


def calculate_metrics(outcomes: list[QueryOutcome]) -> EvaluationMetrics:
    answerable = [outcome for outcome in outcomes if outcome.query.query_type != "no-answer"]
    no_answer = [outcome for outcome in outcomes if outcome.query.query_type == "no-answer"]

    hit_at_3 = _mean(
        _has_expected_title(outcome.result, outcome.query.expected_titles, limit=3)
        for outcome in answerable
    )
    hit_at_5 = _mean(
        _has_expected_title(outcome.result, outcome.query.expected_titles, limit=5)
        for outcome in answerable
    )
    mrr = _mean(
        _reciprocal_rank(outcome.result, outcome.query.expected_titles) for outcome in answerable
    )
    citation_precision = _citation_precision(answerable)
    no_answer_accuracy = _mean(
        isinstance(outcome.result, InsufficientEvidence) for outcome in no_answer
    )
    latencies = [outcome.latency_ms for outcome in outcomes]
    median_latency = int(statistics.median(latencies)) if latencies else 0
    p95_latency = (
        max(latencies) if len(latencies) < 2 else int(statistics.quantiles(latencies, n=100)[94])
    )

    return EvaluationMetrics(
        hit_at_3=hit_at_3,
        hit_at_5=hit_at_5,
        mrr=mrr,
        citation_precision=citation_precision,
        no_answer_accuracy=no_answer_accuracy,
        median_retrieval_latency_ms=median_latency,
        p95_retrieval_latency_ms=p95_latency,
    )


async def run_evaluation(
    *,
    docs_path: Path = DEFAULT_DOCS_PATH,
    fixture_path: Path = DEFAULT_FIXTURE_PATH,
    write_markdown: bool = True,
    task_id: str = DEFAULT_TASK_ID,
) -> tuple[EvaluationMetrics, list[QueryOutcome]]:
    session_factory = await _prepare_seeded_session_factory(fixture_path)
    try:
        queries = load_evaluation_dataset(docs_path)
        use_stub = _should_use_stub_embeddings()
        retriever = await _build_retriever(session_factory=session_factory, use_stub=use_stub)
        outcomes = await _evaluate_queries(
            retriever=retriever,
            session_factory=session_factory,
            queries=queries,
        )
        metrics = calculate_metrics(outcomes)

        if write_markdown:
            _write_retrieval_eval_doc(
                docs_path=docs_path,
                metrics=metrics,
                outcomes=outcomes,
                task_id=task_id,
            )

        return metrics, outcomes
    finally:
        await session_factory.kw["bind"].dispose()


async def _build_retriever(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    use_stub: bool,
) -> RagQueryService | StubRetrievalService:
    if use_stub:
        return StubRetrievalService(session_factory=session_factory)
    return RagQueryService(session_factory=session_factory)


async def _evaluate_queries(
    *,
    retriever: RagQueryService | StubRetrievalService,
    session_factory: async_sessionmaker[AsyncSession],
    queries: list[EvalQuery],
) -> list[QueryOutcome]:
    title_lookup = await _load_title_lookup(session_factory)
    outcomes: list[QueryOutcome] = []
    for eval_query in queries:
        start = time.monotonic()
        result = await retriever.retrieve(eval_query.query)
        latency_ms = int((time.monotonic() - start) * 1000)
        normalized_result = _normalize_result(result, title_lookup)
        outcomes.append(
            QueryOutcome(
                query=eval_query,
                result=normalized_result,
                latency_ms=latency_ms,
            )
        )
    return outcomes


def _normalize_result(
    result: list[EvidenceBlock] | list[RetrievedDream] | InsufficientEvidence,
    title_lookup: dict[uuid.UUID, str],
) -> list[RetrievedDream] | InsufficientEvidence:
    if isinstance(result, InsufficientEvidence):
        return result
    if result and isinstance(result[0], RetrievedDream):
        return result
    return [
        RetrievedDream(
            dream_id=block.dream_id,
            title=title_lookup.get(block.dream_id, ""),
            relevance_score=block.relevance_score,
        )
        for block in result
    ]


async def _prepare_seeded_session_factory(
    fixture_path: Path,
) -> async_sessionmaker[AsyncSession]:
    database_url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "TEST_DATABASE_URL or DATABASE_URL is required to run retrieval evaluation"
        )

    os.environ["DATABASE_URL"] = database_url
    get_settings.cache_clear()

    reset_engine = create_async_engine(
        database_url,
        poolclass=NullPool,
        connect_args={"statement_cache_size": 0},
    )
    await _reset_public_schema(reset_engine)
    await reset_engine.dispose()
    await asyncio.to_thread(command.upgrade, _alembic_config(), "head")

    engine = create_async_engine(
        database_url,
        poolclass=NullPool,
        connect_args={"statement_cache_size": 0},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    await _seed_corpus(session_factory=session_factory, fixture_path=fixture_path)
    return session_factory


async def _seed_corpus(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    fixture_path: Path,
) -> None:
    dreams = _load_seed_dreams(fixture_path)

    async with session_factory() as session:
        for dream in dreams:
            entry = DreamEntry(
                source_doc_id=dream.source_doc_id,
                date=dream.entry_date,
                title=dream.title,
                raw_text=dream.raw_text,
                word_count=len(dream.raw_text.split()),
                content_hash=hashlib.sha256(
                    f"{dream.source_doc_id}:{dream.raw_text}".encode("utf-8")
                ).hexdigest(),
                segmentation_confidence="high",
            )
            session.add(entry)
        await session.commit()

        ids = list(
            (
                await session.execute(
                    select(DreamEntry.id).order_by(
                        DreamEntry.date.asc(), DreamEntry.created_at.asc()
                    )
                )
            ).scalars()
        )

    embedding_client = None if not _should_use_stub_embeddings() else ZeroEmbeddingClient()
    ingestion_service = RagIngestionService(
        session_factory=session_factory,
        embedding_client=embedding_client,
    )
    for dream_id in ids:
        await ingestion_service.index_dream(dream_id)


async def _load_title_lookup(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[uuid.UUID, str]:
    async with session_factory() as session:
        result = await session.execute(select(DreamEntry.id, DreamEntry.title))
    return {dream_id: title for dream_id, title in result.all()}


def _load_seed_dreams(fixture_path: Path) -> list[SeedDream]:
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    return [
        SeedDream(
            source_doc_id=item["source_doc_id"],
            title=item["title"],
            raw_text=item["raw_text"],
            entry_date=date.fromisoformat(item["date"]),
        )
        for item in raw
    ]


def _write_retrieval_eval_doc(
    *,
    docs_path: Path,
    metrics: EvaluationMetrics,
    outcomes: list[QueryOutcome],
    task_id: str,
) -> None:
    content = docs_path.read_text(encoding="utf-8")
    content = re.sub(
        r"Last updated: \d{4}-\d{2}-\d{2}", f"Last updated: {EVAL_DATE}", content, count=1
    )
    content = re.sub(
        r"Changed by: .+",
        "Changed by: T12 — Retrieval Evaluation Baseline",
        content,
        count=1,
    )
    content = re.sub(
        r"- Index readiness: .+",
        "- Index readiness: 20 seeded dream entries indexed for the synthetic baseline",
        content,
        count=1,
    )
    content = _replace_section_table(content, BASELINE_SECTION, _baseline_metrics_table(metrics))
    content = _replace_section_table(content, CURRENT_SECTION, _current_metrics_table(metrics))
    content = _replace_section_table(content, NO_ANSWER_SECTION, _no_answer_table(outcomes))
    content = _append_evaluation_history(content, metrics=metrics, task_id=task_id)
    content = re.sub(
        r"## Regression Notes\n\n.*?\n\n---",
        (
            "## Regression Notes\n\n"
            "No retrieval regression is recorded for T12. This baseline uses the synthetic 20-entry corpus "
            "and falls back to stub embeddings plus lexical ranking when `OPENAI_API_KEY` is absent or starts "
            "with `test-`, so the local evaluation remains executable without live OpenAI access.\n\n---"
        ),
        content,
        count=1,
        flags=re.DOTALL,
    )
    docs_path.write_text(content, encoding="utf-8")


def _baseline_metrics_table(metrics: EvaluationMetrics) -> str:
    rows = [
        "| Metric | Value | Notes |",
        "|--------|-------|-------|",
        f"| hit@3 | {_fmt(metrics.hit_at_3)} | Fraction of queries where correct doc is in top 3 results |",
        f"| hit@5 | {_fmt(metrics.hit_at_5)} | Fraction of queries where correct doc is in top 5 results |",
        f"| MRR | {_fmt(metrics.mrr)} | Mean Reciprocal Rank across query set |",
        f"| Citation precision | {_fmt(metrics.citation_precision)} | Fraction of cited docs that are relevant to the query |",
        f"| No-answer accuracy | {_fmt(metrics.no_answer_accuracy)} | Fraction of no-answer queries correctly returning insufficient_evidence |",
        f"| Median retrieval latency | {metrics.median_retrieval_latency_ms} ms | p50 latency for the retrieve stage (ms) |",
        f"| p95 retrieval latency | {metrics.p95_retrieval_latency_ms} ms | p95 latency for the retrieve stage (ms) |",
    ]
    return "\n".join(rows)


def _current_metrics_table(metrics: EvaluationMetrics) -> str:
    rows = [
        "| Metric | Previous | Current | Delta | Regression? |",
        "|--------|----------|---------|-------|-------------|",
        f"| hit@3 | — | {_fmt(metrics.hit_at_3)} | — | No |",
        f"| hit@5 | — | {_fmt(metrics.hit_at_5)} | — | No |",
        f"| MRR | — | {_fmt(metrics.mrr)} | — | No |",
        f"| Citation precision | — | {_fmt(metrics.citation_precision)} | — | No |",
        f"| No-answer accuracy | — | {_fmt(metrics.no_answer_accuracy)} | — | No |",
        f"| Median retrieval latency | — | {metrics.median_retrieval_latency_ms} ms | — | No |",
        f"| p95 retrieval latency | — | {metrics.p95_retrieval_latency_ms} ms | — | No |",
    ]
    return "\n".join(rows)


def _no_answer_table(outcomes: list[QueryOutcome]) -> str:
    rows = [
        "| Query ID | Result | Expected | Pass? |",
        "|----------|--------|----------|-------|",
    ]
    for outcome in outcomes:
        if outcome.query.query_type != "no-answer":
            continue
        result = (
            "insufficient_evidence"
            if isinstance(outcome.result, InsufficientEvidence)
            else "retrieved_evidence"
        )
        passed = "Yes" if result == "insufficient_evidence" else "No"
        rows.append(f"| {outcome.query.query_id} | {result} | insufficient_evidence | {passed} |")
    return "\n".join(rows)


def _append_evaluation_history(markdown: str, *, metrics: EvaluationMetrics, task_id: str) -> str:
    rows = _extract_table(markdown, HISTORY_SECTION)
    rows.append(_evaluation_history_row(metrics=metrics, task_id=task_id))
    return _replace_section_table(markdown, HISTORY_SECTION, _render_history_table(rows))


def _evaluation_history_row(metrics: EvaluationMetrics, *, task_id: str) -> dict[str, str]:
    return {
        "Date": EVAL_DATE,
        "Task": task_id,
        "Corpus Version": CORPUS_VERSION,
        "Eval Source": EVAL_SOURCE,
        "hit@3": _fmt(metrics.hit_at_3),
        "MRR": _fmt(metrics.mrr),
        "No-answer acc.": _fmt(metrics.no_answer_accuracy),
        "Faithfulness": "—",
        "Completeness": "—",
        "Note": "synthetic seeded baseline established",
    }


def _render_history_table(rows: list[dict[str, str]]) -> str:
    headers = [
        "Date",
        "Task",
        "Corpus Version",
        "Eval Source",
        "hit@3",
        "MRR",
        "No-answer acc.",
        "Faithfulness",
        "Completeness",
        "Note",
    ]
    rendered_rows = [
        "| Date | Task | Corpus Version | Eval Source | hit@3 | MRR | No-answer acc. | Faithfulness | Completeness | Note |",
        "|------|------|----------------|-------------|-------|-----|----------------|--------------|--------------|------|",
    ]
    for row in rows:
        rendered_rows.append("| " + " | ".join(row.get(header, "") for header in headers) + " |")
    return "\n".join(rendered_rows)


def _extract_table(markdown: str, heading: str) -> list[dict[str, str]]:
    section = _extract_section(markdown, heading)
    lines = [line.strip() for line in section.splitlines() if line.strip()]
    table_lines = [line for line in lines if line.startswith("|")]
    if len(table_lines) < 2:
        return []

    headers = [cell.strip() for cell in table_lines[0].strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for line in table_lines[2:]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != len(headers):
            continue
        rows.append(dict(zip(headers, cells, strict=True)))
    return rows


def _extract_section(markdown: str, heading: str) -> str:
    pattern = rf"{re.escape(heading)}\n\n(.*?)(?:\n---|\n## |\Z)"
    match = re.search(pattern, markdown, flags=re.DOTALL)
    if not match:
        raise ValueError(f"Unable to locate section: {heading}")
    return match.group(1)


def _replace_section_table(markdown: str, heading: str, new_table: str) -> str:
    section = _extract_section(markdown, heading)
    table_match = re.search(
        r"\|.*?(?=\n\n(?:Notes:|Rules:|Scoring:|<!--)|\Z)", section, flags=re.DOTALL
    )
    if table_match is None:
        raise ValueError(f"Unable to replace table for section: {heading}")
    updated_section = section[: table_match.start()] + new_table + section[table_match.end() :]
    return markdown.replace(section, updated_section, 1)


def _tokenize(text_value: str) -> list[str]:
    return [
        token for token in re.findall(r"[a-z0-9]+", text_value.lower()) if token not in _STOPWORDS
    ]


def _lexical_score(query: str, query_terms: list[str], haystack: str) -> float:
    haystack_lower = haystack.lower()
    haystack_terms = _tokenize(haystack_lower)
    if not haystack_terms:
        return 0.0

    overlap = sum(1 for term in query_terms if term in haystack_terms)
    phrase_bonus = 1.0 if query.lower() in haystack_lower else 0.0
    title_bonus = (
        0.5 if any(term in haystack_lower.split(" dream")[0] for term in query_terms) else 0.0
    )
    return overlap + phrase_bonus + title_bonus


def _has_expected_title(
    result: list[RetrievedDream] | InsufficientEvidence,
    expected_titles: tuple[str, ...],
    *,
    limit: int,
) -> bool:
    if isinstance(result, InsufficientEvidence):
        return False
    expected = set(expected_titles)
    return any(item.title in expected for item in result[:limit])


def _reciprocal_rank(
    result: list[RetrievedDream] | InsufficientEvidence,
    expected_titles: tuple[str, ...],
) -> float:
    if isinstance(result, InsufficientEvidence):
        return 0.0
    expected = set(expected_titles)
    for index, item in enumerate(result, start=1):
        if item.title in expected:
            return 1.0 / index
    return 0.0


def _citation_precision(outcomes: list[QueryOutcome]) -> float:
    relevant = 0
    total = 0
    for outcome in outcomes:
        if isinstance(outcome.result, InsufficientEvidence):
            continue
        expected = set(outcome.query.expected_titles)
        cited = outcome.result[:3]
        relevant += sum(1 for item in cited if item.title in expected)
        total += len(cited)
    return 0.0 if total == 0 else relevant / total


def _mean(values: Any) -> float:
    values_list = [float(value) for value in values]
    return 0.0 if not values_list else sum(values_list) / len(values_list)


def _fmt(value: float) -> str:
    return f"{value:.2f}"


def _should_use_stub_embeddings() -> bool:
    api_key = os.getenv("OPENAI_API_KEY", "")
    return not api_key or api_key.startswith("test-")


def _alembic_config() -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    return config


async def _reset_public_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
        await connection.execute(text("GRANT ALL ON SCHEMA public TO public"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", default=DEFAULT_TASK_ID, help="Task ID to tag this eval run")
    args = parser.parse_args()
    asyncio.run(run_evaluation(task_id=args.task_id))


if __name__ == "__main__":
    main()
