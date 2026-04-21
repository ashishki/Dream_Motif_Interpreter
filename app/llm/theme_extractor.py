from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

from app.llm.client import AnthropicLLMClient
from app.models.dream import DreamEntry
from app.models.theme import ThemeCategory
from app.shared.tracing import get_tracer

_VALID_MATCH_TYPES = {"literal", "semantic", "symbolic"}


class ThemeExtractionError(RuntimeError):
    """Raised when theme extraction cannot produce a valid draft response."""


@dataclass(frozen=True)
class ThemeAssignment:
    category_id: uuid.UUID
    salience: float
    match_type: str
    justification: str


class ThemeExtractor:
    def __init__(self, client: Any | None = None, *, max_retries: int = 1) -> None:
        self._client = client or AnthropicLLMClient()
        self._max_retries = max_retries

    async def extract(
        self,
        dream_entry: DreamEntry,
        categories: list[ThemeCategory],
    ) -> list[ThemeAssignment]:
        tracer = get_tracer(__name__)
        system_prompt = self._build_system_prompt(categories)
        user_prompt = self._build_user_prompt(dream_entry)
        allowed_ids = {category.id for category in categories}
        last_error: Exception | None = None

        with tracer.start_as_current_span("theme_extractor.extract"):
            for _attempt in range(self._max_retries + 1):
                try:
                    raw_response = await self._client.complete(
                        system_prompt,
                        user_prompt,
                        max_tokens=4000,
                    )
                    return self._parse_assignments(raw_response, allowed_ids)
                except (ThemeExtractionError, ValueError, json.JSONDecodeError) as exc:
                    last_error = exc

        raise ThemeExtractionError("Theme extraction failed after retry") from last_error

    def _build_system_prompt(self, categories: list[ThemeCategory]) -> str:
        category_lines = "\n".join(f"- {category.id}: {category.name}" for category in categories)
        return (
            "You extract draft theme assignments for a dream journal entry.\n"
            "Return JSON only using the schema "
            '{"themes":[{"category_id":"uuid","salience":0.0,"match_type":"literal|semantic|symbolic","justification":"..."}]}.\n'
            "Use only category IDs from this list.\n"
            "Treat every assignment as a draft suggestion, not a fact.\n"
            "Available categories:\n"
            f"{category_lines}"
        )

    def _build_user_prompt(self, dream_entry: DreamEntry) -> str:
        return (
            "Extract the most salient draft themes from this dream entry.\n"
            f"Dream title: {dream_entry.title}\n"
            f"Dream text:\n{dream_entry.raw_text}"
        )

    def _parse_assignments(
        self,
        raw_response: str,
        allowed_ids: set[uuid.UUID],
    ) -> list[ThemeAssignment]:
        payload = json.loads(_extract_json_payload(raw_response))
        themes = payload.get("themes")
        if not isinstance(themes, list):
            raise ThemeExtractionError("LLM response did not include a themes list")

        assignments: list[ThemeAssignment] = []
        for theme in themes:
            if not isinstance(theme, dict):
                raise ThemeExtractionError("Theme entries must be JSON objects")

            category_id = uuid.UUID(str(theme["category_id"]))
            if category_id not in allowed_ids:
                raise ThemeExtractionError(
                    f"Theme category_id {category_id} is not in the provided taxonomy"
                )

            salience = float(theme["salience"])
            if not 0.0 <= salience <= 1.0:
                raise ThemeExtractionError("Theme salience must be between 0.0 and 1.0")

            match_type = str(theme["match_type"])
            if match_type not in _VALID_MATCH_TYPES:
                raise ThemeExtractionError(f"Invalid match_type: {match_type}")

            justification = str(theme["justification"]).strip()
            if not justification:
                raise ThemeExtractionError("Theme justification must be a non-empty string")

            assignments.append(
                ThemeAssignment(
                    category_id=category_id,
                    salience=salience,
                    match_type=match_type,
                    justification=justification,
                )
            )

        return assignments


_JSON_CODE_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_json_payload(raw_response: str) -> str:
    """Strip markdown fences and leading text, return the first JSON object found.

    Raises ValueError so all LLM callers (regardless of domain) can catch it uniformly.
    """
    stripped = raw_response.strip()
    if not stripped:
        raise ValueError("LLM response was empty")

    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    code_block_match = _JSON_CODE_BLOCK_PATTERN.search(stripped)
    if code_block_match:
        return code_block_match.group(1).strip()

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and start < end:
        return stripped[start : end + 1].strip()

    raise ValueError("LLM response did not contain a JSON object")
