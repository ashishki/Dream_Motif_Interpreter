"""Unit tests for MotifInductor (AC-2, AC-3, AC-5 of WS-9.2).

All tests use a stub LLM client — no real API calls are made.
AC-3 is verified by inspecting the system prompt for absence of any
theme_categories list.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.services.imagery import ImageryFragment
from app.services.motif_inductor import MotifInductionError, MotifInductor


FRAGMENTS: list[ImageryFragment] = [
    {"text": "crumbling stairs", "start_offset": 0, "end_offset": 16},
    {"text": "a locked door at the top", "start_offset": 17, "end_offset": 41},
    {"text": "my feet sinking into the floor", "start_offset": 42, "end_offset": 72},
]


class StubLLMClient:
    """Stub LLM client that captures prompts and returns canned responses."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.calls = 0
        self.last_system: str = ""
        self.last_user: str = ""

    async def complete(self, system: str, user: str) -> str:
        self.last_system = system
        self.last_user = user
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


def _valid_response() -> str:
    return json.dumps(
        {
            "motifs": [
                {
                    "label": "obstructed vertical movement",
                    "rationale": (
                        "The imagery of crumbling stairs, a locked door above, "
                        "and feet sinking all point to upward movement that is blocked."
                    ),
                    "confidence": "high",
                    "imagery_indices": [0, 1, 2],
                }
            ]
        }
    )


# ---------------------------------------------------------------------------
# AC-2: returns list of MotifCandidate dicts with required keys
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_induce_returns_motif_candidate_list() -> None:
    client = StubLLMClient([_valid_response()])
    inductor = MotifInductor(llm_client=client)

    candidates = await inductor.induce(FRAGMENTS)

    assert isinstance(candidates, list)
    assert len(candidates) == 1


@pytest.mark.asyncio
async def test_motif_candidate_has_required_keys() -> None:
    client = StubLLMClient([_valid_response()])
    inductor = MotifInductor(llm_client=client)

    candidates = await inductor.induce(FRAGMENTS)
    candidate = candidates[0]

    assert "label" in candidate
    assert "rationale" in candidate
    assert "confidence" in candidate
    assert "imagery_indices" in candidate


@pytest.mark.asyncio
async def test_motif_candidate_values_are_correct() -> None:
    client = StubLLMClient([_valid_response()])
    inductor = MotifInductor(llm_client=client)

    candidates = await inductor.induce(FRAGMENTS)
    candidate = candidates[0]

    assert candidate["label"] == "obstructed vertical movement"
    assert isinstance(candidate["rationale"], str) and candidate["rationale"]
    assert candidate["confidence"] == "high"
    assert candidate["imagery_indices"] == [0, 1, 2]


@pytest.mark.asyncio
async def test_motif_confidence_valid_values() -> None:
    for level in ("high", "moderate", "low"):
        response = json.dumps(
            {
                "motifs": [
                    {
                        "label": "test motif",
                        "rationale": "some rationale",
                        "confidence": level,
                        "imagery_indices": [0],
                    }
                ]
            }
        )
        client = StubLLMClient([response])
        candidates = await MotifInductor(llm_client=client).induce(FRAGMENTS)
        assert candidates[0]["confidence"] == level


# ---------------------------------------------------------------------------
# AC-3: prompt must not include theme_categories or predefined vocabulary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_system_prompt_does_not_include_theme_categories() -> None:
    client = StubLLMClient([_valid_response()])
    inductor = MotifInductor(llm_client=client)
    await inductor.induce(FRAGMENTS)

    assert "theme_categories" not in client.last_system
    assert "theme_categories" not in client.last_user


@pytest.mark.asyncio
async def test_system_prompt_instructs_open_vocabulary_generation() -> None:
    client = StubLLMClient([_valid_response()])
    inductor = MotifInductor(llm_client=client)
    await inductor.induce(FRAGMENTS)

    system = client.last_system.lower()
    assert "do not use predefined" in system or "open" in system or "generate" in system


@pytest.mark.asyncio
async def test_system_prompt_explicit_no_predefined_categories_instruction() -> None:
    """The exact required instruction must appear in the prompt."""
    client = StubLLMClient([_valid_response()])
    inductor = MotifInductor(llm_client=client)
    await inductor.induce(FRAGMENTS)

    assert "Do not use predefined psychological categories." in client.last_system
    assert "Do not interpret the dream." in client.last_system
    assert (
        "Name only the structural or thematic pattern visible in the imagery." in client.last_system
    )


# ---------------------------------------------------------------------------
# AC-5: retry once on JSON parse failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_induce_retries_on_json_parse_failure() -> None:
    invalid_response = "not valid json {"
    client = StubLLMClient([invalid_response, _valid_response()])
    inductor = MotifInductor(llm_client=client, max_retries=1)

    candidates = await inductor.induce(FRAGMENTS)

    assert client.calls == 2
    assert len(candidates) == 1


@pytest.mark.asyncio
async def test_induce_raises_after_max_retries_exceeded() -> None:
    client = StubLLMClient(["not valid json {", "also not json {"])
    inductor = MotifInductor(llm_client=client, max_retries=1)

    with pytest.raises(MotifInductionError):
        await inductor.induce(FRAGMENTS)

    assert client.calls == 2


@pytest.mark.asyncio
async def test_induce_retries_on_missing_motifs_key() -> None:
    bad_response = json.dumps({"result": []})
    client = StubLLMClient([bad_response, _valid_response()])
    inductor = MotifInductor(llm_client=client, max_retries=1)

    candidates = await inductor.induce(FRAGMENTS)

    assert client.calls == 2
    assert len(candidates) == 1


# ---------------------------------------------------------------------------
# Validation: invalid confidence, out-of-range indices raise errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_induce_raises_on_invalid_confidence() -> None:
    bad_response = json.dumps(
        {
            "motifs": [
                {
                    "label": "some motif",
                    "rationale": "some rationale",
                    "confidence": "very_high",
                    "imagery_indices": [0],
                }
            ]
        }
    )
    client = StubLLMClient([bad_response, bad_response])
    inductor = MotifInductor(llm_client=client, max_retries=1)

    with pytest.raises(MotifInductionError):
        await inductor.induce(FRAGMENTS)


@pytest.mark.asyncio
async def test_induce_raises_on_out_of_range_imagery_index() -> None:
    bad_response = json.dumps(
        {
            "motifs": [
                {
                    "label": "some motif",
                    "rationale": "some rationale",
                    "confidence": "low",
                    "imagery_indices": [99],
                }
            ]
        }
    )
    client = StubLLMClient([bad_response, bad_response])
    inductor = MotifInductor(llm_client=client, max_retries=1)

    with pytest.raises(MotifInductionError):
        await inductor.induce(FRAGMENTS)


@pytest.mark.asyncio
async def test_induce_with_empty_fragment_list() -> None:
    """Inductor handles empty fragment list gracefully."""
    response = json.dumps({"motifs": []})
    client = StubLLMClient([response])
    candidates = await MotifInductor(llm_client=client).induce([])
    assert candidates == []


# ---------------------------------------------------------------------------
# AC-5: stub client is used; no real AnthropicLLMClient is instantiated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stub_client_is_used_without_api_key() -> None:
    client = StubLLMClient([_valid_response()])
    inductor = MotifInductor(llm_client=client)
    candidates = await inductor.induce(FRAGMENTS)
    assert candidates is not None


@pytest.mark.asyncio
async def test_induce_increments_success_counter() -> None:
    counter = StubCounter()
    meter = StubMeter(counter)
    client = StubLLMClient([_valid_response()])

    with patch("app.services.motif_inductor.get_meter", return_value=meter):
        inductor = MotifInductor(llm_client=client)
        await inductor.induce(FRAGMENTS)

    assert meter.created_names == ["motif.induction_total"]
    assert counter.calls == [(1, {"status": "success"})]


@pytest.mark.asyncio
async def test_induce_increments_failure_counter() -> None:
    counter = StubCounter()
    meter = StubMeter(counter)
    client = StubLLMClient(["not valid json {", "still not valid json {"])

    with patch("app.services.motif_inductor.get_meter", return_value=meter):
        inductor = MotifInductor(llm_client=client, max_retries=1)
        with pytest.raises(MotifInductionError):
            await inductor.induce(FRAGMENTS)

    assert counter.calls == [(1, {"status": "failure"})]
