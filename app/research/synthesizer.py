from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal, TypedDict

from app.llm.client import AnthropicLLMClient
from app.shared.tracing import get_meter, get_tracer


AllowedConfidence = Literal["speculative", "plausible", "uncertain"]
_ALLOWED_CONFIDENCE_LEVELS = {"speculative", "plausible", "uncertain"}


class ResearchParallel(TypedDict):
    domain: str
    label: str
    source_url: str
    relevance_note: str
    confidence: AllowedConfidence


class ResearchSynthesisError(Exception):
    """Raised when research synthesis returns invalid JSON or schema."""


class ResearchSynthesizer:
    def __init__(self, llm_client: Any | None = None) -> None:
        self._client = llm_client or AnthropicLLMClient(model="claude-sonnet-4-6")
        self._tracer = get_tracer(__name__)
        self._meter = get_meter(__name__)
        self._synthesis_counter = self._meter.create_counter(
            "research.synthesis_total",
            description="Research synthesis calls",
        )

    async def synthesize(
        self, motif_label: str, sources: list[dict[str, str]]
    ) -> list[ResearchParallel]:
        with self._tracer.start_as_current_span("research_synthesizer.synthesize") as span:
            span.set_attribute("component", "research_synthesizer")
            system_prompt = self._build_system_prompt()
            user_prompt = self._build_user_prompt(motif_label, sources)

            try:
                try:
                    raw_response = await self._client.complete(
                        system_prompt,
                        user_prompt,
                        max_tokens=4000,
                    )
                    parallels = self._parse_parallels(raw_response)
                except (
                    json.JSONDecodeError,
                    TypeError,
                    ValueError,
                    ResearchSynthesisError,
                ) as exc:
                    raise ResearchSynthesisError(
                        "Research synthesis failed to parse valid parallels"
                    ) from exc

                self._synthesis_counter.add(1, {"status": "success"})
                return parallels
            except ResearchSynthesisError:
                self._synthesis_counter.add(1, {"status": "failure"})
                raise

    def _build_system_prompt(self) -> str:
        return (
            "You extract structural parallels and suggestions from external source excerpts.\n"
            "Return JSON only using the schema "
            '{"parallels":[{"domain":"...","label":"...","source_url":"...",'
            '"relevance_note":"...","confidence":"speculative|plausible|uncertain"}]}.\n'
            "Use only the terms parallels and suggestions for this task.\n"
            "Confidence must be one of: speculative, plausible, uncertain.\n"
            "Do not use confirmed, high, high confidence, verified, or established "
            "anywhere in the output.\n"
            "Identify only tentative structural parallels suggested by the source material. "
            "Do not claim certainty or verification.\n"
            "Return only the JSON object. No commentary."
        )

    def _build_user_prompt(self, motif_label: str, sources: list[dict[str, str]]) -> str:
        serialized_sources = json.dumps(sources, ensure_ascii=True)
        return (
            f"Motif label: {motif_label}\n\n"
            "From these external sources, extract structural parallels and suggestions "
            "related to the motif. "
            "Return JSON output only.\n\n"
            f"Sources:\n{serialized_sources}"
        )

    def _parse_parallels(self, raw_response: str) -> list[ResearchParallel]:
        from app.llm.theme_extractor import _extract_json_payload

        payload = json.loads(_extract_json_payload(raw_response))
        parallels_raw = payload.get("parallels")
        if not isinstance(parallels_raw, list):
            raise ResearchSynthesisError("LLM response did not include a parallels list")

        parallels: list[ResearchParallel] = []
        for item in parallels_raw:
            if not isinstance(item, Mapping):
                raise ResearchSynthesisError("Parallel entries must be JSON objects")

            domain = str(item.get("domain", "")).strip()
            label = str(item.get("label", "")).strip()
            source_url = str(item.get("source_url", "")).strip()
            relevance_note = str(item.get("relevance_note", "")).strip()
            confidence = str(item.get("confidence", "")).strip().lower()

            if not domain or not label or not source_url or not relevance_note:
                raise ResearchSynthesisError("Parallel fields must be non-empty")
            if confidence not in _ALLOWED_CONFIDENCE_LEVELS:
                raise ResearchSynthesisError(
                    "Parallel confidence must be one of: speculative, plausible, uncertain"
                )

            parallels.append(
                ResearchParallel(
                    domain=domain,
                    label=label,
                    source_url=source_url,
                    relevance_note=relevance_note,
                    confidence=confidence,  # type: ignore[arg-type]
                )
            )

        return parallels
