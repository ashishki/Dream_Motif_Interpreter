from __future__ import annotations

import ast
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError

import pytest
import tiktoken

from app.retrieval import ingestion
from app.retrieval.ingestion import chunk_dream_text


def _paragraph(token: str, count: int) -> str:
    return " ".join(f"{token}{index}" for index in range(count))


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


def _build_text_with_exact_token_count(token_count: int) -> str:
    seed_text = (
        "In the dream I crossed a quiet hallway, noticed a mirrored door, "
        "heard distant water, and returned to the same room again. "
    )
    token_ids: list[int] = []
    while len(token_ids) < token_count:
        token_ids.extend(ingestion._TOKENIZER.encode(seed_text))
    return ingestion._TOKENIZER.decode(token_ids[:token_count])


def test_chunking_boundary() -> None:
    long_entry = "\n\n".join(
        [
            _build_text_with_exact_token_count(220),
            _build_text_with_exact_token_count(220),
            _build_text_with_exact_token_count(220),
        ]
    )
    short_entry = "\n\n".join(
        [_build_text_with_exact_token_count(120), _build_text_with_exact_token_count(120)]
    )

    long_chunks = chunk_dream_text(long_entry)
    short_chunks = chunk_dream_text(short_entry)

    assert len(long_chunks) == 2
    assert long_chunks[0].chunk_index == 0
    assert long_chunks[1].chunk_index == 1
    assert len(short_chunks) == 1
    assert short_chunks[0].chunk_index == 0


def test_ingestion_does_not_import_query_module() -> None:
    source_path = Path(__file__).resolve().parents[2] / "app/retrieval/ingestion.py"
    module = ast.parse(source_path.read_text(encoding="utf-8"))

    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            assert all(alias.name != "app.retrieval.query" for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.module != "app.retrieval.query"


def test_token_count_uses_tiktoken() -> None:
    prose = " ".join(f"dreamword{index}" for index in range(100))
    tokenizer = tiktoken.get_encoding("cl100k_base")

    assert ingestion._token_count(prose) == len(tokenizer.encode(prose))


def test_chunks_do_not_exceed_512_real_tokens() -> None:
    prose = _build_text_with_exact_token_count(600)
    token_ids = ingestion._TOKENIZER.encode(prose)
    split_point = 300
    chunk_input = "\n\n".join(
        [
            ingestion._TOKENIZER.decode(token_ids[:split_point]),
            ingestion._TOKENIZER.decode(token_ids[split_point:]),
        ]
    )

    chunks = chunk_dream_text(chunk_input)

    assert chunks
    assert all(ingestion._token_count(chunk.chunk_text) <= 512 for chunk in chunks)


def test_tiktoken_in_requirements() -> None:
    requirements_path = Path(__file__).resolve().parents[2] / "requirements.txt"

    assert "tiktoken" in requirements_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_embed_raises_on_429() -> None:
    client = ingestion.OpenAIEmbeddingClient()

    with patch("app.retrieval.types.get_settings", return_value=_build_settings()):
        with patch(
            "app.retrieval.types._send_embedding_request",
            side_effect=HTTPError(
                url="https://api.openai.com/v1/embeddings",
                code=429,
                msg="error",
                hdrs=None,
                fp=BytesIO(b'{"error":"failed"}'),
            ),
        ):
            with pytest.raises(ingestion.EmbeddingServiceError) as exc_info:
                await client.embed(["dream text"], dream_id="dream-429")

    assert exc_info.value.status_code == 429
    assert exc_info.value.dream_id == "dream-429"


@pytest.mark.asyncio
async def test_embed_raises_on_500() -> None:
    client = ingestion.OpenAIEmbeddingClient()

    with patch("app.retrieval.types.get_settings", return_value=_build_settings()):
        with patch(
            "app.retrieval.types._send_embedding_request",
            side_effect=HTTPError(
                url="https://api.openai.com/v1/embeddings",
                code=500,
                msg="error",
                hdrs=None,
                fp=BytesIO(b'{"error":"failed"}'),
            ),
        ):
            with pytest.raises(ingestion.EmbeddingServiceError) as exc_info:
                await client.embed(["dream text"], dream_id="dream-500")

    assert exc_info.value.status_code == 500
    assert exc_info.value.dream_id == "dream-500"


@pytest.mark.asyncio
async def test_embed_logs_dream_id_on_error() -> None:
    with patch("app.retrieval.types.request.urlopen", side_effect=_build_http_error(429)):
        with patch("app.retrieval.types.get_settings", return_value=_build_settings()):
            with patch("app.retrieval.types.get_logger") as get_logger:
                logger_error = get_logger.return_value.error
                client = ingestion.OpenAIEmbeddingClient()
                with pytest.raises(ingestion.EmbeddingServiceError):
                    await client.embed(["dream text"], dream_id="dream-log")

    logger_error.assert_called_once_with(
        "OpenAI embedding request failed",
        status_code=429,
        dream_id="dream-log",
    )
