from __future__ import annotations

import json

import pytest

from app.research.synthesizer import ResearchSynthesizer, ResearchSynthesisError


SOURCES = [
    {
        "url": "https://example.com/threshold",
        "excerpt": "A figure approaches a guarded threshold and cannot cross.",
        "retrieved_at": "2026-04-17T10:00:00+00:00",
    }
]


class StubLLMClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.last_system: str = ""
        self.last_user: str = ""

    async def complete(self, system: str, user: str, *, max_tokens: int = 1000) -> str:
        del max_tokens
        self.last_system = system
        self.last_user = user
        return self.response


def _valid_response(overlap_degree: str = "partial") -> str:
    return json.dumps(
        {
            "parallels": [
                {
                    "domain": "folklore",
                    "label": "guarded threshold",
                    "source_url": "https://example.com/threshold",
                    "relevance_note": "The source suggests a blocked passage motif.",
                    "overlap_degree": overlap_degree,
                }
            ]
        }
    )


@pytest.mark.asyncio
async def test_synthesize_returns_parallel_objects_with_required_keys() -> None:
    client = StubLLMClient(_valid_response())
    synthesizer = ResearchSynthesizer(llm_client=client)

    parallels = await synthesizer.synthesize("blocked ascent", SOURCES)

    assert len(parallels) == 1
    assert parallels[0].keys() == {
        "domain",
        "label",
        "source_url",
        "relevance_note",
        "overlap_degree",
    }
    assert "parallels" in client.last_system.lower()
    assert "overlap_degree" in client.last_system.lower()


@pytest.mark.asyncio
async def test_synthesize_raises_on_parse_failure() -> None:
    synthesizer = ResearchSynthesizer(llm_client=StubLLMClient("not json"))

    with pytest.raises(ResearchSynthesisError):
        await synthesizer.synthesize("blocked ascent", SOURCES)


@pytest.mark.asyncio
async def test_overlap_degree_values_are_restricted() -> None:
    for degree in ("full", "partial", "structural"):
        synthesizer = ResearchSynthesizer(llm_client=StubLLMClient(_valid_response(degree)))
        parallels = await synthesizer.synthesize("blocked ascent", SOURCES)
        assert parallels[0]["overlap_degree"] == degree

    bad_synthesizer = ResearchSynthesizer(llm_client=StubLLMClient(_valid_response("speculative")))
    with pytest.raises(ResearchSynthesisError):
        await bad_synthesizer.synthesize("blocked ascent", SOURCES)
