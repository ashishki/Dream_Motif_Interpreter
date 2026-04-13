from __future__ import annotations

import ast
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError

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
