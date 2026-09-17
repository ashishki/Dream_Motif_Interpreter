from __future__ import annotations

import ast
from datetime import date
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
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


def test_exact_and_hybrid_search_include_simple_fts_for_english_text() -> None:
    source = (Path(__file__).resolve().parents[2] / "app/retrieval/query.py").read_text(
        encoding="utf-8"
    )

    assert "to_tsvector('simple', dc.chunk_text)" in source
    assert "websearch_to_tsquery('simple', :query)" in source
    assert "websearch_to_tsquery('simple', :fts_query)" in source


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
    assert query.extract_concrete_image_query("сон с рыбой") == "рыбой"
    assert query.extract_concrete_image_query("найди рыбу") == "рыбу"
    assert query.extract_concrete_image_query("сны где есть рыба") == "рыба"
    assert query.extract_concrete_image_query("найди красную дверь") == "красную дверь"


def test_extract_concrete_image_query_ignores_broad_queries() -> None:
    assert query.extract_concrete_image_query("образы воды") is None
    assert query.extract_concrete_image_query("религиозные сюжеты") is None
    assert query.extract_concrete_image_query("найди образы воды") is None
    assert query.extract_concrete_image_query("найди религиозные сюжеты") is None
    assert query.extract_concrete_image_query("найди образец ткани") == "образец ткани"


def test_build_evidence_queries_remove_wrappers_and_separate_alphabets() -> None:
    assert query._build_evidence_queries(
        "найди dream с рыбой и прозрачной водой near glass of a house"
    ) == (
        "рыбой OR прозрачной OR водой",
        "near OR glass OR house",
    )
    assert query._build_evidence_queries("черную рыбу", require_all=True) == (
        "черную рыбу",
        query.EMPTY_EVIDENCE_QUERY,
    )
    assert query._fragment_evidence_profile(
        "найди черную рыбу",
        "черная рыба вода дверь",
        "черную рыбу",
    ) == ("черную рыбу", True)


def test_exact_evidence_fragment_is_archive_sentence_with_real_offset() -> None:
    chunk_text = "Сначала была темнота. Рыба черного цвета плыла в прозрачной воде. Потом рассвет."

    fragment = query._extract_exact_evidence_fragment(chunk_text, "рыба")

    assert fragment == {
        "text": "Рыба черного цвета плыла в прозрачной воде",
        "match_type": "literal",
        "char_offset": 22,
    }


def test_exact_evidence_fragment_supports_inflected_fish_query() -> None:
    fragment = query._extract_exact_evidence_fragment(
        "В воде медленно двигалась рыба.",
        "рыбой",
    )

    assert fragment == {
        "text": "В воде медленно двигалась рыба",
        "match_type": "semantic",
        "char_offset": 0,
    }


def test_composite_exact_evidence_requires_terms_in_the_same_sentence() -> None:
    assert (
        query._extract_exact_evidence_fragment(
            "Красная рыба уплыла. Дверь была синяя.",
            "красная дверь",
        )
        is None
    )
    assert query._extract_exact_evidence_fragment(
        "Передо мной появилась красная дверь.",
        "красную дверь",
    ) == {
        "text": "Передо мной появилась красная дверь",
        "match_type": "semantic",
        "char_offset": 0,
    }
    assert (
        query._exact_rows_to_evidence_rows(
            [
                {
                    "dream_id": uuid4(),
                    "date": date(2026, 5, 9),
                    "title": "Split colors",
                    "chunk_text": "Красная рыба уплыла. Дверь была синяя.",
                }
            ],
            "красная дверь",
        )
        == []
    )


@pytest.mark.asyncio
async def test_embed_query_normalizes_timeout_to_query_embedding_error() -> None:
    embedding_client = Mock()
    embedding_client.embed = AsyncMock(side_effect=TimeoutError("provider timed out"))
    service = query.RagQueryService(
        session_factory=Mock(),
        embedding_client=embedding_client,
    )

    with pytest.raises(query.QueryEmbeddingError) as exc_info:
        await service._embed_query("рыба")

    assert exc_info.value.status_code == 0
    assert exc_info.value.query_length == len("рыба")


@pytest.mark.parametrize(
    "malformed_vector",
    [
        [],
        [0.1, 0.2, 0.3],
        [float("nan"), *([0.0] * (query.EMBEDDING_DIMENSIONS - 1))],
    ],
)
@pytest.mark.asyncio
async def test_embed_query_rejects_malformed_provider_vector(
    malformed_vector: list[float],
) -> None:
    embedding_client = Mock()
    embedding_client.embed = AsyncMock(return_value=[malformed_vector])
    service = query.RagQueryService(
        session_factory=Mock(),
        embedding_client=embedding_client,
    )

    with pytest.raises(query.QueryEmbeddingError) as exc_info:
        await service._embed_query("рыба")

    assert exc_info.value.status_code == 0


def test_verified_semantic_threshold_has_floor_and_honors_stricter_config() -> None:
    assert query._verified_semantic_threshold(0.20) == 0.40
    assert query._verified_semantic_threshold(0.40) == 0.40
    assert query._verified_semantic_threshold(0.65) == 0.65


@pytest.mark.asyncio
async def test_retrieve_fuses_concrete_exact_and_semantic_rows() -> None:
    dream_id = uuid4()
    service = query.RagQueryService(session_factory=Mock())
    service._expand_query_terms = AsyncMock(return_value="сон с рыбой вода")  # type: ignore[method-assign]
    service._exact_search_rows = AsyncMock(  # type: ignore[method-assign]
        return_value=[
            {
                "dream_id": dream_id,
                "date": date(2026, 5, 9),
                "title": "Запретная рыба",
                "chunk_text": "Рыба черного цвета плыла в воде.",
            }
        ]
    )
    service._search_probes = AsyncMock(  # type: ignore[method-assign]
        return_value=[
            {
                "dream_id": dream_id,
                "date": date(2026, 5, 9),
                "title": "Запретная рыба",
                "chunk_text": "Рыба черного цвета плыла в воде.",
                "relevance_score": 0.72,
                "matched_fragments": [],
            }
        ]
    )

    result = await service.retrieve("сон с рыбой")

    assert result == [
        query.EvidenceBlock(
            dream_id=dream_id,
            date=date(2026, 5, 9),
            title="Запретная рыба",
            chunk_text="Рыба черного цвета плыла в воде.",
            relevance_score=1.0,
            matched_fragments=[
                query.FragmentMatch(
                    text="Рыба черного цвета плыла в воде",
                    match_type="semantic",
                    char_offset=0,
                )
            ],
        )
    ]
    service._exact_search_rows.assert_awaited_once_with("рыбой", result_limit=None)
    service._search_probes.assert_awaited_once()


@pytest.mark.asyncio
async def test_retrieve_preserves_exact_fish_evidence_when_semantic_search_fails() -> None:
    dream_id = uuid4()
    service = query.RagQueryService(session_factory=Mock())
    service._expand_query_terms = AsyncMock(return_value="сон с рыбой")  # type: ignore[method-assign]
    service._exact_search_rows = AsyncMock(  # type: ignore[method-assign]
        return_value=[
            {
                "dream_id": dream_id,
                "date": date(2026, 5, 9),
                "title": "Запретная рыба",
                "chunk_text": "Рыба черного цвета, она очень красивая.",
            }
        ]
    )
    service._search_probes = AsyncMock(  # type: ignore[method-assign]
        side_effect=query.QueryEmbeddingError(503, 12)
    )

    result = await service.retrieve("сон с рыбой")

    assert isinstance(result, list)
    assert result[0].dream_id == dream_id
    assert result[0].relevance_score == 1.0
    assert result[0].matched_fragments[0].text == "Рыба черного цвета, она очень красивая"


@pytest.mark.asyncio
async def test_retrieve_does_not_mask_non_embedding_semantic_failure() -> None:
    service = query.RagQueryService(session_factory=Mock())
    service._expand_query_terms = AsyncMock(return_value="сон с рыбой")  # type: ignore[method-assign]
    service._exact_search_rows = AsyncMock(  # type: ignore[method-assign]
        return_value=[
            {
                "dream_id": uuid4(),
                "date": date(2026, 5, 9),
                "title": "Рыба",
                "chunk_text": "Рыба плыла в воде.",
            }
        ]
    )
    service._search_probes = AsyncMock(  # type: ignore[method-assign]
        side_effect=RuntimeError("SQL programming error")
    )

    with pytest.raises(RuntimeError, match="SQL programming error"):
        await service.retrieve("сон с рыбой")


def test_query_sql_conditions_theme_fragments_and_filters_weak_vector_only_rows() -> None:
    source = (Path(__file__).resolve().parents[2] / "app/retrieval/query.py").read_text(
        encoding="utf-8"
    )

    assert "websearch_to_tsquery('russian', :evidence_query_russian)" in source
    assert "websearch_to_tsquery('simple', :evidence_query_simple)" in source
    assert "fused.fts_rank IS NOT NULL" in source
    assert "fused.cosine_similarity, 0.0) >= :verified_semantic_threshold" in source


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
                    {"text": "церковь", "match_type": "semantic", "char_offset": 10}
                ],
            },
            {
                "dream_id": dream_id,
                "date": date(2026, 4, 15),
                "title": "Church dream",
                "chunk_text": "На стене была икона.",
                "relevance_score": 0.91,
                "matched_fragments": [
                    {"text": "икона", "match_type": "semantic", "char_offset": 14}
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
        {"text": "церковь", "match_type": "semantic", "char_offset": 10},
        {
            "text": "икона",
            "match_type": "semantic",
            "char_offset": len("Я вошел в церковь.\n---\n") + 14,
        },
    ]
    for fragment in rows[0]["matched_fragments"]:
        offset = fragment["char_offset"]
        assert rows[0]["chunk_text"][offset:].startswith(fragment["text"])


def test_merge_probe_rows_dedupes_chunks_and_rebases_composite_fragments() -> None:
    dream_id = uuid4()
    separator = "\n---\n"
    rows = query._merge_probe_rows(
        [
            {
                "dream_id": dream_id,
                "date": date(2026, 5, 9),
                "title": "Composite",
                "chunk_text": "Chunk B",
                "relevance_score": 1.0,
                "matched_fragments": [{"text": "B", "match_type": "literal", "char_offset": 6}],
            },
            {
                "dream_id": dream_id,
                "date": date(2026, 5, 9),
                "title": "Composite",
                "chunk_text": f"Chunk A{separator}Chunk B",
                "_evidence_chunks": ["Chunk A", "Chunk B"],
                "relevance_score": 0.8,
                "matched_fragments": [
                    {"text": "A", "match_type": "semantic", "char_offset": 6},
                    {
                        "text": "B",
                        "match_type": "semantic",
                        "char_offset": len(f"Chunk A{separator}") + 6,
                    },
                ],
            },
        ]
    )

    assert rows[0]["chunk_text"] == f"Chunk B{separator}Chunk A"
    assert rows[0]["chunk_text"].count("Chunk B") == 1
    for fragment in rows[0]["matched_fragments"]:
        offset = fragment["char_offset"]
        assert rows[0]["chunk_text"][offset:].startswith(fragment["text"])


def test_merge_probe_rows_caps_final_fusion_at_result_limit() -> None:
    rows = query._merge_probe_rows(
        [
            {
                "dream_id": uuid4(),
                "date": date(2026, 5, 9),
                "title": f"Dream {index}",
                "chunk_text": f"Chunk {index}",
                "relevance_score": 1.0 - index / 100,
                "matched_fragments": [],
            }
            for index in range(query.RESULT_LIMIT + 7)
        ]
    )

    assert len(rows) == query.RESULT_LIMIT
    assert rows[0]["title"] == "Dream 0"
    assert rows[-1]["title"] == f"Dream {query.RESULT_LIMIT - 1}"


def test_merge_probe_rows_preserves_literal_separator_inside_archive_chunk() -> None:
    dream_id = uuid4()
    chunk_text = "Повтор\n---\nПовтор"
    second_offset = len("Повтор\n---\n")

    rows = query._merge_probe_rows(
        [
            {
                "dream_id": dream_id,
                "date": date(2026, 5, 9),
                "title": "Literal separator",
                "chunk_text": chunk_text,
                "relevance_score": 0.8,
                "matched_fragments": [
                    {
                        "text": "Повтор",
                        "match_type": "literal",
                        "char_offset": second_offset,
                    }
                ],
            }
        ]
    )

    assert rows[0]["chunk_text"] == chunk_text
    assert rows[0]["chunk_text"].count("Повтор") == 2
    assert rows[0]["matched_fragments"][0]["char_offset"] == second_offset
