from __future__ import annotations

import json
from typing import Any, TypedDict

from app.llm.client import AnthropicLLMClient
from app.shared.tracing import get_tracer


class ImageryFragment(TypedDict):
    text: str
    start_offset: int
    end_offset: int


class ImageryExtractionError(RuntimeError):
    """Raised when imagery extraction cannot produce a valid response."""


class ImageryExtractor:
    """Extract grounded imagery fragments with character offsets from dream text."""

    def __init__(self, llm_client: Any | None = None, *, max_retries: int = 1) -> None:
        self._client = llm_client or AnthropicLLMClient(model="claude-haiku-4-5")
        self._max_retries = max_retries

    async def extract(self, dream_text: str) -> list[ImageryFragment]:
        tracer = get_tracer(__name__)
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(dream_text)
        last_error: Exception | None = None

        with tracer.start_as_current_span("imagery_extractor.extract"):
            for _attempt in range(self._max_retries + 1):
                try:
                    raw_response = await self._client.complete(system_prompt, user_prompt)
                    return self._parse_fragments(raw_response, dream_text)
                except (ImageryExtractionError, ValueError, json.JSONDecodeError) as exc:
                    last_error = exc

        raise ImageryExtractionError(
            "Imagery extraction failed after retry"
        ) from last_error

    def _build_system_prompt(self) -> str:
        return (
            "You extract concrete imagery fragments from dream journal text.\n"
            "Return JSON only using the schema "
            '{"fragments":[{"text":"...","start_offset":0,"end_offset":0}]}.\n'
            "Each fragment must be an exact substring of the dream text provided.\n"
            "start_offset and end_offset are character positions in the source text "
            "(start_offset inclusive, end_offset exclusive).\n"
            "Extract only literal, concrete imagery: objects, settings, actions, "
            "sensory details. Do not interpret, explain, or abstract.\n"
            "Return only the JSON object. No commentary."
        )

    def _build_user_prompt(self, dream_text: str) -> str:
        return (
            "Extract all concrete imagery fragments from the following dream text. "
            "Include character offsets for each fragment.\n\n"
            f"Dream text:\n{dream_text}"
        )

    def _parse_fragments(
        self, raw_response: str, dream_text: str
    ) -> list[ImageryFragment]:
        payload = json.loads(raw_response)
        fragments_raw = payload.get("fragments")
        if not isinstance(fragments_raw, list):
            raise ImageryExtractionError(
                "LLM response did not include a fragments list"
            )

        fragments: list[ImageryFragment] = []
        for item in fragments_raw:
            if not isinstance(item, dict):
                raise ImageryExtractionError("Fragment entries must be JSON objects")

            text = str(item.get("text", "")).strip()
            if not text:
                raise ImageryExtractionError("Fragment text must be non-empty")

            start_offset = int(item["start_offset"])
            end_offset = int(item["end_offset"])

            if start_offset < 0 or end_offset < 0:
                raise ImageryExtractionError(
                    "Fragment offsets must be non-negative"
                )
            if start_offset >= end_offset:
                raise ImageryExtractionError(
                    "Fragment start_offset must be less than end_offset"
                )
            if end_offset > len(dream_text):
                raise ImageryExtractionError(
                    "Fragment end_offset exceeds source text length"
                )

            fragments.append(
                ImageryFragment(
                    text=text,
                    start_offset=start_offset,
                    end_offset=end_offset,
                )
            )

        return fragments
