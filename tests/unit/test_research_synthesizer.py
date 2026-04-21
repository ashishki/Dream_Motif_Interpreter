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


def _valid_response(confidence: str = "plausible") -> str:
    return json.dumps(
        {
            "parallels": [
                {
                    "domain": "folklore",
                    "label": "guarded threshold",
                    "source_url": "https://example.com/threshold",
                    "relevance_note": "The source suggests a blocked passage motif.",
                    "confidence": confidence,
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
        "confidence",
    }
    assert "parallels" in client.last_system.lower()
    assert "suggestions" in client.last_system.lower()
    assert "findings" not in client.last_system.lower()
    assert "results" not in client.last_system.lower()


@pytest.mark.asyncio
async def test_synthesize_raises_on_parse_failure() -> None:
    synthesizer = ResearchSynthesizer(llm_client=StubLLMClient("not json"))

    with pytest.raises(ResearchSynthesisError):
        await synthesizer.synthesize("blocked ascent", SOURCES)


@pytest.mark.asyncio
async def test_confidence_values_are_restricted() -> None:
    for confidence in ("speculative", "plausible", "uncertain"):
        synthesizer = ResearchSynthesizer(llm_client=StubLLMClient(_valid_response(confidence)))
        parallels = await synthesizer.synthesize("blocked ascent", SOURCES)
        assert parallels[0]["confidence"] == confidence

    bad_synthesizer = ResearchSynthesizer(llm_client=StubLLMClient(_valid_response("verified")))
    with pytest.raises(ResearchSynthesisError):
        await bad_synthesizer.synthesize("blocked ascent", SOURCES)
