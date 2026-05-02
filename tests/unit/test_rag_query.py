from __future__ import annotations

import ast
from datetime import date
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from uuid import uuid4

import pytest

from app.retrieval import query


def test_query_does_not_import_ingestion_module() -> None:
    source_path = Path(__file__).resolve().parents[2] / "app/retrieval/query.py"
    module = ast.parse(source_path.read_text(encoding="utf-8"))

    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            assert all(alias.name != "app.retrieval.ingestion" for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.module != "app.retrieval.ingestion"


def _build_settings() -> SimpleNamespace:
    return SimpleNamespace(
        OPENAI_API_KEY="test-openai-key", EMBEDDING_MODEL="text-embedding-3-small"
    )


def _build_http_error(status_code: int) -> HTTPError:
    return HTTPError(
        url="https://api.openai.com/v1/embeddings",
        code=status_code,
        msg="error",
        hdrs=None,
        fp=BytesIO(b'{"error":"failed"}'),
    )


@pytest.mark.asyncio
async def test_query_embed_raises_on_429() -> None:
    client = query.OpenAIEmbeddingClient()

    with patch("app.retrieval.types.get_settings", return_value=_build_settings()):
        with patch(
            "app.retrieval.types._send_embedding_request",
            side_effect=_build_http_error(429),
        ):
            with pytest.raises(query.QueryEmbeddingError) as exc_info:
                await client.embed(["dream text"])

    assert exc_info.value.status_code == 429
    assert exc_info.value.query_length == 1


@pytest.mark.asyncio
async def test_query_embed_raises_on_500() -> None:
    client = query.OpenAIEmbeddingClient()

    with patch("app.retrieval.types.get_settings", return_value=_build_settings()):
        with patch(
            "app.retrieval.types._send_embedding_request",
            side_effect=_build_http_error(500),
        ):
            with pytest.raises(query.QueryEmbeddingError) as exc_info:
                await client.embed(["dream text"])

    assert exc_info.value.status_code == 500
    assert exc_info.value.query_length == 1


@pytest.mark.asyncio
async def test_query_embed_logs_on_error() -> None:
    with patch("app.retrieval.types.request.urlopen", side_effect=_build_http_error(429)):
        with patch("app.retrieval.types.get_settings", return_value=_build_settings()):
            with patch("app.retrieval.types.get_logger") as get_logger:
                logger_error = get_logger.return_value.error
                client = query.OpenAIEmbeddingClient()
                with pytest.raises(query.QueryEmbeddingError):
                    await client.embed(["dream text"])

    logger_error.assert_called_once_with(
        "OpenAI embedding request failed",
        status_code=429,
        query_length=1,
    )


@pytest.mark.asyncio
async def test_retrieve_returns_insufficient_evidence_on_empty_query() -> None:
    service = query.RagQueryService(session_factory=Mock())

    result = await service.retrieve("")

    assert result == query.InsufficientEvidence(reason="Query is empty")


def test_coerce_fragments_returns_fragment_matches() -> None:
    fragments = query._coerce_fragments(
        [{"text": "spiral staircase", "match_type": "semantic", "char_offset": 0}]
    )

    assert fragments == [
        query.FragmentMatch(
            text="spiral staircase",
            match_type="semantic",
            char_offset=0,
        )
    ]


def test_broad_religious_query_builds_multiple_retrieval_probes() -> None:
    probes = query._build_retrieval_probes(
        "религиозные сюжеты",
        "религиозные сюжеты молитва церковь",
    )

    assert probes == [
        "религиозные сюжеты молитва церковь",
        "религиозные сюжеты церковь храм богослужение",
        "религиозные сюжеты молитва песнопение Рождество",
        "религиозные сюжеты икона Христос Бог",
    ]


def test_extract_concrete_image_query_normalizes_fish_object_queries() -> None:
    assert query.extract_concrete_image_query("сон с рыбой") == "рыба"
    assert query.extract_concrete_image_query("найди рыбу") == "рыба"
    assert query.extract_concrete_image_query("сны где есть рыба") == "рыба"


def test_extract_concrete_image_query_ignores_broad_queries() -> None:
    assert query.extract_concrete_image_query("образы воды") is None
    assert query.extract_concrete_image_query("религиозные сюжеты") is None


def test_merge_probe_rows_dedupes_by_dream_id_and_preserves_evidence() -> None:
    dream_id = uuid4()
    other_dream_id = uuid4()

    rows = query._merge_probe_rows(
        [
            {
                "dream_id": dream_id,
                "date": date(2026, 4, 15),
                "title": "Church dream",
                "chunk_text": "Я вошел в церковь.",
                "relevance_score": 0.52,
                "matched_fragments": [
                    {"text": "церковь", "match_type": "semantic", "char_offset": 8}
                ],
            },
            {
                "dream_id": dream_id,
                "date": date(2026, 4, 15),
                "title": "Church dream",
                "chunk_text": "На стене была икона.",
                "relevance_score": 0.91,
                "matched_fragments": [
                    {"text": "икона", "match_type": "semantic", "char_offset": 15}
                ],
            },
            {
                "dream_id": other_dream_id,
                "date": date(2026, 4, 12),
                "title": "Song dream",
                "chunk_text": "Звучало рождественское песнопение.",
                "relevance_score": 0.75,
                "matched_fragments": [],
            },
        ]
    )

    assert [row["dream_id"] for row in rows] == [dream_id, other_dream_id]
    assert rows[0]["relevance_score"] == 0.91
    assert rows[0]["chunk_text"] == "Я вошел в церковь.\n---\nНа стене была икона."
    assert rows[0]["matched_fragments"] == [
        {"text": "церковь", "match_type": "semantic", "char_offset": 8},
        {"text": "икона", "match_type": "semantic", "char_offset": 15},
    ]
