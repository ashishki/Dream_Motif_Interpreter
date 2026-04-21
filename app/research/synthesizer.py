from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal, TypedDict

from app.llm.client import AnthropicLLMClient
from app.shared.tracing import get_meter, get_tracer


AllowedOverlapDegree = Literal["full", "partial", "structural"]
_ALLOWED_OVERLAP_DEGREES = {"full", "partial", "structural"}


class ResearchParallel(TypedDict):
    domain: str
    label: str
    source_url: str
    relevance_note: str
    overlap_degree: AllowedOverlapDegree


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
            "You extract structural parallels from external source excerpts for a dream motif.\n"
            "Return JSON only using the schema "
            '{"parallels":[{"domain":"...","label":"...","source_url":"...",'
            '"relevance_note":"...","overlap_degree":"full|partial|structural"}]}.\n'
            "overlap_degree measures how many elements of the dream motif are present in the parallel:\n"
            "  full     — all or nearly all key elements of the motif match the source material\n"
            "  partial  — some elements match, others are absent or substituted\n"
            "  structural — only the abstract structural pattern matches; specific elements differ\n"
            "Identify only tentative parallels suggested by the source material. "
            "Do not claim certainty or interpretation.\n"
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
            overlap_degree = str(item.get("overlap_degree", "")).strip().lower()

            if not domain or not label or not source_url or not relevance_note:
                raise ResearchSynthesisError("Parallel fields must be non-empty")
            if overlap_degree not in _ALLOWED_OVERLAP_DEGREES:
                raise ResearchSynthesisError(
                    "Parallel overlap_degree must be one of: full, partial, structural"
                )

            parallels.append(
                ResearchParallel(
                    domain=domain,
                    label=label,
                    source_url=source_url,
                    relevance_note=relevance_note,
                    overlap_degree=overlap_degree,  # type: ignore[arg-type]
                )
            )

        return parallels
