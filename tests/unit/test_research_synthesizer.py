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


def _response_with_source(*, source_url: str, source_id: str = "") -> str:
    parallel = {
        "domain": "folklore",
        "label": "guarded threshold",
        "source_url": source_url,
        "relevance_note": "The source suggests a blocked passage motif.",
        "overlap_degree": "partial",
    }
    if source_id:
        parallel["source_id"] = source_id
    return json.dumps({"parallels": [parallel]})


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
    assert '"source_id": "source-1"' in client.last_user


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "injected_url",
    [
        "javascript:alert(document.domain)",
        "data:text/html,<script>alert(1)</script>",
        "https://accounts.example.evil/phishing",
    ],
)
async def test_synthesize_rejects_unsafe_or_unretrieved_citation_urls(
    injected_url: str,
) -> None:
    synthesizer = ResearchSynthesizer(
        llm_client=StubLLMClient(_response_with_source(source_url=injected_url))
    )

    with pytest.raises(ResearchSynthesisError):
        await synthesizer.synthesize("blocked ascent", SOURCES)


@pytest.mark.asyncio
async def test_synthesize_preserves_exact_retrieved_https_url_after_normalized_match() -> None:
    retrieved_url = "https://Example.com:443/threshold#retrieved-section"
    sources = [{**SOURCES[0], "url": retrieved_url}]
    response = _response_with_source(
        source_url="HTTPS://example.com/threshold#model-invented-fragment"
    )
    synthesizer = ResearchSynthesizer(llm_client=StubLLMClient(response))

    parallels = await synthesizer.synthesize("blocked ascent", sources)

    assert parallels[0]["source_url"] == retrieved_url


@pytest.mark.asyncio
async def test_synthesize_resolves_source_id_without_trusting_a_model_url() -> None:
    response = json.dumps(
        {
            "parallels": [
                {
                    "domain": "folklore",
                    "label": "guarded threshold",
                    "source_id": "source-1",
                    "relevance_note": "The source suggests a blocked passage motif.",
                    "overlap_degree": "partial",
                }
            ]
        }
    )
    synthesizer = ResearchSynthesizer(llm_client=StubLLMClient(response))

    parallels = await synthesizer.synthesize("blocked ascent", SOURCES)

    assert parallels[0]["source_url"] == SOURCES[0]["url"]


@pytest.mark.asyncio
async def test_synthesize_rejects_malicious_url_even_with_a_valid_source_id() -> None:
    response = _response_with_source(
        source_id="source-1",
        source_url="javascript:alert(document.domain)",
    )
    synthesizer = ResearchSynthesizer(llm_client=StubLLMClient(response))

    with pytest.raises(ResearchSynthesisError):
        await synthesizer.synthesize("blocked ascent", SOURCES)


@pytest.mark.asyncio
async def test_synthesize_does_not_allow_a_non_http_url_even_if_retrieved() -> None:
    unsafe_url = "data:text/html,<script>alert(1)</script>"
    sources = [{**SOURCES[0], "url": unsafe_url}]
    synthesizer = ResearchSynthesizer(
        llm_client=StubLLMClient(_response_with_source(source_url=unsafe_url))
    )

    with pytest.raises(ResearchSynthesisError):
        await synthesizer.synthesize("blocked ascent", sources)

    assert '"source_id"' not in synthesizer._client.last_user
