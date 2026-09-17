from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

from app.retrieval.query import EvidenceBlock, FragmentMatch, RagQueryService
from app.retrieval import query


def _embedding(seed: float) -> list[float]:
    return [seed, *([0.0] * (query.EMBEDDING_DIMENSIONS - 1))]


@pytest.mark.asyncio
async def test_query_expansion_fallback() -> None:
    dream_id = uuid4()
    embedding_client = Mock()
    query_embedding = _embedding(0.1)
    embedding_client.embed = AsyncMock(return_value=[query_embedding])
    service = RagQueryService(session_factory=Mock(), embedding_client=embedding_client)
    service._search = AsyncMock(
        return_value=[  # type: ignore[method-assign]
            {
                "dream_id": dream_id,
                "date": date(2026, 4, 14),
                "title": "Lantern dream",
                "chunk_text": "A lantern glowed near the stairwell.",
                "relevance_score": 0.92,
                "matched_fragments": [
                    {"text": "lantern", "match_type": "semantic", "char_offset": 0}
                ],
            }
        ]
    )

    failing_client = SimpleNamespace(
        messages=SimpleNamespace(create=AsyncMock(side_effect=RuntimeError("boom")))
    )
    with patch(
        "app.retrieval.query._get_anthropic_client_cls", return_value=lambda **_: failing_client
    ):
        result = await service.retrieve("lantern staircase")

    assert result == [
        EvidenceBlock(
            dream_id=dream_id,
            date=date(2026, 4, 14),
            title="Lantern dream",
            chunk_text="A lantern glowed near the stairwell.",
            relevance_score=0.92,
            matched_fragments=[FragmentMatch(text="lantern", match_type="semantic", char_offset=0)],
        )
    ]
    embedding_client.embed.assert_awaited_once_with(["lantern staircase"])


@pytest.mark.asyncio
async def test_prayer_query_uses_deterministic_religious_expansion_when_llm_fails() -> None:
    embedding_client = Mock()
    query_embedding = _embedding(0.1)
    embedding_client.embed = AsyncMock(return_value=[query_embedding])
    service = RagQueryService(session_factory=Mock(), embedding_client=embedding_client)
    service._search = AsyncMock(return_value=[])  # type: ignore[method-assign]

    failing_client = SimpleNamespace(
        messages=SimpleNamespace(create=AsyncMock(side_effect=RuntimeError("boom")))
    )
    with patch(
        "app.retrieval.query._get_anthropic_client_cls", return_value=lambda **_: failing_client
    ):
        await service.retrieve("где упоминается молитва")

    expanded_query = embedding_client.embed.await_args.args[0][0]
    for term in query.RELIGIOUS_QUERY_EXPANSION_TERMS:
        assert term in expanded_query
    service._search.assert_awaited_once_with(
        expanded_query,
        query_embedding,
        evidence_query=expanded_query,
        require_all_evidence_terms=False,
    )


@pytest.mark.asyncio
async def test_religious_query_merges_deterministic_and_llm_expansion() -> None:
    embedding_client = Mock()
    embedding_client.embed = AsyncMock(return_value=[_embedding(0.1)])
    service = RagQueryService(session_factory=Mock(), embedding_client=embedding_client)
    service._search = AsyncMock(return_value=[])  # type: ignore[method-assign]

    successful_client = SimpleNamespace(
        messages=SimpleNamespace(
            create=AsyncMock(
                return_value=SimpleNamespace(
                    content=[
                        SimpleNamespace(type="text", text="литургия свечи молитва"),
                    ]
                )
            )
        )
    )
    with patch(
        "app.retrieval.query._get_anthropic_client_cls", return_value=lambda **_: successful_client
    ):
        await service.retrieve("молитва")

    expanded_query = embedding_client.embed.await_args.args[0][0]
    assert "литургия" in expanded_query
    assert expanded_query.count("молитва") == 1
    for term in query.RELIGIOUS_QUERY_EXPANSION_TERMS:
        assert term in expanded_query


@pytest.mark.asyncio
async def test_broad_religious_query_runs_multiple_retrieval_probes() -> None:
    embedding_client = Mock()
    embedding_client.embed = AsyncMock(
        side_effect=[
            [_embedding(0.1)],
            [_embedding(0.2)],
            [_embedding(0.3)],
            [_embedding(0.4)],
        ]
    )
    service = RagQueryService(session_factory=Mock(), embedding_client=embedding_client)
    service._search = AsyncMock(return_value=[])  # type: ignore[method-assign]

    failing_client = SimpleNamespace(
        messages=SimpleNamespace(create=AsyncMock(side_effect=RuntimeError("boom")))
    )
    with patch(
        "app.retrieval.query._get_anthropic_client_cls", return_value=lambda **_: failing_client
    ):
        await service.retrieve("религиозные сюжеты")

    assert embedding_client.embed.await_count == 4
    search_queries = [call.args[0] for call in service._search.await_args_list]
    assert search_queries == [
        "религиозные сюжеты молитва песнопение богослужение церковь храм икона Христос Бог Рождество",
        "религиозные сюжеты церковь храм богослужение",
        "религиозные сюжеты молитва песнопение Рождество",
        "религиозные сюжеты икона Христос Бог",
    ]


def test_religious_query_profile_matches_domain_terms() -> None:
    assert query._matches_religious_query_profile("молитва")
    assert query._matches_religious_query_profile("рождественское песнопение")
    assert query._matches_religious_query_profile("религиозные сюжеты")
    assert query._matches_religious_query_profile("церковь")
    assert not query._matches_religious_query_profile("lantern staircase")
