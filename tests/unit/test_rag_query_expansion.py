from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

from app.retrieval.query import EvidenceBlock, FragmentMatch, RagQueryService


@pytest.mark.asyncio
async def test_query_expansion_fallback() -> None:
    dream_id = uuid4()
    embedding_client = Mock()
    embedding_client.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    service = RagQueryService(session_factory=Mock(), embedding_client=embedding_client)
    service._search = AsyncMock(
        return_value=[  # type: ignore[method-assign]
            {
                "dream_id": dream_id,
                "date": date(2026, 4, 14),
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
            chunk_text="A lantern glowed near the stairwell.",
            relevance_score=0.92,
            matched_fragments=[FragmentMatch(text="lantern", match_type="semantic", char_offset=0)],
        )
    ]
    embedding_client.embed.assert_awaited_once_with(["lantern staircase"])
