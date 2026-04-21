"""Unit tests for ImageryExtractor (AC-1, AC-5 of WS-9.2).

All tests use a stub LLM client — no real API calls are made.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.services.imagery import ImageryExtractionError, ImageryExtractor


DREAM_TEXT = (
    "I was back in my childhood house and water kept rising through the rooms. "
    "My mother watched from the stairs while I tried to seal the doors."
)


class StubLLMClient:
    """Stub LLM client that returns canned responses for testing."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.calls = 0

    async def complete(self, system: str, user: str, *, max_tokens: int = 1000) -> str:
        del system, user, max_tokens
        response = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return response


class StubCounter:
    def __init__(self) -> None:
        self.calls: list[tuple[int, dict[str, str]]] = []

    def add(self, amount: int, attributes: dict[str, str]) -> None:
        self.calls.append((amount, attributes))


class StubMeter:
    def __init__(self, counter: StubCounter) -> None:
        self.counter = counter
        self.created_names: list[str] = []

    def create_counter(self, name: str) -> StubCounter:
        self.created_names.append(name)
        return self.counter


def _valid_response(dream_text: str) -> str:
    """Build a valid JSON response with real offsets from DREAM_TEXT."""
    fragment_text = "water kept rising through the rooms"
    start = dream_text.index(fragment_text)
    end = start + len(fragment_text)
    return json.dumps(
        {
            "fragments": [
                {
                    "text": fragment_text,
                    "start_offset": start,
                    "end_offset": end,
                }
            ]
        }
    )


# ---------------------------------------------------------------------------
# AC-1: returns list of ImageryFragment dicts with required keys and offsets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_returns_fragment_list() -> None:
    client = StubLLMClient([_valid_response(DREAM_TEXT)])
    extractor = ImageryExtractor(llm_client=client)

    fragments = await extractor.extract(DREAM_TEXT)

    assert isinstance(fragments, list)
    assert len(fragments) == 1
    frag = fragments[0]
    assert "text" in frag
    assert "start_offset" in frag
    assert "end_offset" in frag


@pytest.mark.asyncio
async def test_extract_fragment_text_and_offsets_are_correct() -> None:
    fragment_text = "water kept rising through the rooms"
    start = DREAM_TEXT.index(fragment_text)
    end = start + len(fragment_text)
    response = json.dumps(
        {"fragments": [{"text": fragment_text, "start_offset": start, "end_offset": end}]}
    )
    client = StubLLMClient([response])
    extractor = ImageryExtractor(llm_client=client)

    fragments = await extractor.extract(DREAM_TEXT)

    assert fragments[0]["text"] == fragment_text
    assert fragments[0]["start_offset"] == start
    assert fragments[0]["end_offset"] == end


@pytest.mark.asyncio
async def test_extract_multiple_fragments() -> None:
    frag1 = "childhood house"
    frag2 = "seal the doors"
    start1 = DREAM_TEXT.index(frag1)
    end1 = start1 + len(frag1)
    start2 = DREAM_TEXT.index(frag2)
    end2 = start2 + len(frag2)
    response = json.dumps(
        {
            "fragments": [
                {"text": frag1, "start_offset": start1, "end_offset": end1},
                {"text": frag2, "start_offset": start2, "end_offset": end2},
            ]
        }
    )
    client = StubLLMClient([response])
    fragments = await ImageryExtractor(llm_client=client).extract(DREAM_TEXT)

    assert len(fragments) == 2
    assert fragments[0]["text"] == frag1
    assert fragments[1]["text"] == frag2


# ---------------------------------------------------------------------------
# AC-5: retry once on JSON parse failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_retries_on_json_parse_failure() -> None:
    invalid_response = "not valid json {"
    valid_response = _valid_response(DREAM_TEXT)
    client = StubLLMClient([invalid_response, valid_response])
    extractor = ImageryExtractor(llm_client=client, max_retries=1)

    fragments = await extractor.extract(DREAM_TEXT)

    assert client.calls == 2
    assert len(fragments) == 1


@pytest.mark.asyncio
async def test_extract_raises_after_max_retries_exceeded() -> None:
    client = StubLLMClient(["not valid json {", "also not json {"])
    extractor = ImageryExtractor(llm_client=client, max_retries=1)

    with pytest.raises(ImageryExtractionError):
        await extractor.extract(DREAM_TEXT)

    assert client.calls == 2


# ---------------------------------------------------------------------------
# Validation: malformed fragment entries raise errors on retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_retries_on_missing_fragments_key() -> None:
    bad_response = json.dumps({"imagery": []})
    valid_response = _valid_response(DREAM_TEXT)
    client = StubLLMClient([bad_response, valid_response])
    extractor = ImageryExtractor(llm_client=client, max_retries=1)

    fragments = await extractor.extract(DREAM_TEXT)

    assert client.calls == 2
    assert len(fragments) == 1


@pytest.mark.asyncio
async def test_extract_raises_on_invalid_offsets() -> None:
    """start_offset >= end_offset triggers ImageryExtractionError."""
    bad_fragment = json.dumps({"fragments": [{"text": "foo", "start_offset": 10, "end_offset": 5}]})
    client = StubLLMClient([bad_fragment, bad_fragment])
    extractor = ImageryExtractor(llm_client=client, max_retries=1)

    with pytest.raises(ImageryExtractionError):
        await extractor.extract(DREAM_TEXT)


@pytest.mark.asyncio
async def test_extract_raises_on_offset_beyond_text_length() -> None:
    beyond = len(DREAM_TEXT) + 1
    bad_fragment = json.dumps(
        {"fragments": [{"text": "foo", "start_offset": 0, "end_offset": beyond}]}
    )
    client = StubLLMClient([bad_fragment, bad_fragment])
    extractor = ImageryExtractor(llm_client=client, max_retries=1)

    with pytest.raises(ImageryExtractionError):
        await extractor.extract(DREAM_TEXT)


# ---------------------------------------------------------------------------
# AC-5: stub client is used; no real AnthropicLLMClient is instantiated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stub_client_is_used_without_api_key() -> None:
    """Passing llm_client bypasses AnthropicLLMClient entirely."""
    client = StubLLMClient([_valid_response(DREAM_TEXT)])
    extractor = ImageryExtractor(llm_client=client)
    fragments = await extractor.extract(DREAM_TEXT)
    assert fragments is not None


@pytest.mark.asyncio
async def test_extract_increments_success_counter() -> None:
    counter = StubCounter()
    meter = StubMeter(counter)
    client = StubLLMClient([_valid_response(DREAM_TEXT)])

    with patch("app.services.imagery.get_meter", return_value=meter):
        extractor = ImageryExtractor(llm_client=client)
        await extractor.extract(DREAM_TEXT)

    assert meter.created_names == ["motif.imagery_extract_total"]
    assert counter.calls == [(1, {"status": "success"})]


@pytest.mark.asyncio
async def test_extract_increments_failure_counter() -> None:
    counter = StubCounter()
    meter = StubMeter(counter)
    client = StubLLMClient(["not valid json {", "still not valid json {"])

    with patch("app.services.imagery.get_meter", return_value=meter):
        extractor = ImageryExtractor(llm_client=client, max_retries=1)
        with pytest.raises(ImageryExtractionError):
            await extractor.extract(DREAM_TEXT)

    assert counter.calls == [(1, {"status": "failure"})]
