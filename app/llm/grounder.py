from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from app.llm.client import AnthropicLLMClient
from app.llm.theme_extractor import ThemeAssignment
from app.models.dream import DreamEntry
from app.shared.tracing import get_tracer

_VALID_MATCH_TYPES = {"literal", "semantic", "symbolic"}


class GroundingError(RuntimeError):
    """Raised when fragment grounding cannot produce a valid response."""


@dataclass(frozen=True)
class GroundedTheme:
    category_id: uuid.UUID
    salience: float
    fragments: list[dict[str, Any]]


class Grounder:
    def __init__(self, client: Any | None = None, *, max_retries: int = 1) -> None:
        self._client = client or AnthropicLLMClient(model="claude-sonnet-4-6")
        self._max_retries = max_retries

    async def ground(
        self,
        dream_entry: DreamEntry,
        theme_assignments: list[ThemeAssignment],
    ) -> list[GroundedTheme]:
        if not theme_assignments:
            return []

        tracer = get_tracer(__name__)
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(dream_entry, theme_assignments)
        allowed_ids = {assignment.category_id for assignment in theme_assignments}
        last_error: Exception | None = None

        with tracer.start_as_current_span("grounder.ground"):
            for _attempt in range(self._max_retries + 1):
                try:
                    raw_response = await self._client.complete(system_prompt, user_prompt)
                    return self._parse_grounded_themes(
                        raw_response,
                        allowed_ids=allowed_ids,
                        raw_text=dream_entry.raw_text,
                    )
                except (GroundingError, ValueError, json.JSONDecodeError) as exc:
                    last_error = exc

        raise GroundingError("Theme grounding failed after retry") from last_error

    def _build_system_prompt(self) -> str:
        return (
            "You rerank dream themes by salience and ground them to source text spans.\n"
            "Return JSON only using the schema "
            '{"themes":[{"category_id":"uuid","salience":0.0,"fragments":[{"text":"...","start_offset":0,"end_offset":0,"match_type":"literal|semantic|symbolic"}]}]}.\n'
            "Use only the provided category IDs.\n"
            "Offsets are character offsets into the original dream text.\n"
            "Treat the output as draft interpretive suggestions, not factual conclusions."
        )

    def _build_user_prompt(
        self,
        dream_entry: DreamEntry,
        theme_assignments: list[ThemeAssignment],
    ) -> str:
        assignment_lines = "\n".join(
            (
                f"- category_id={assignment.category_id}, salience={assignment.salience}, "
                f"match_type={assignment.match_type}, justification={assignment.justification}"
            )
            for assignment in theme_assignments
        )
        return (
            "Ground the following draft themes against the dream text.\n"
            "Dream text:\n"
            f"{dream_entry.raw_text}\n\n"
            "Draft themes:\n"
            f"{assignment_lines}"
        )

    def _parse_grounded_themes(
        self,
        raw_response: str,
        *,
        allowed_ids: set[uuid.UUID],
        raw_text: str,
    ) -> list[GroundedTheme]:
        payload = json.loads(raw_response)
        themes = payload.get("themes")
        if not isinstance(themes, list):
            raise GroundingError("LLM response did not include a themes list")

        grounded_themes: list[GroundedTheme] = []
        seen_ids: set[uuid.UUID] = set()
        for theme in themes:
            if not isinstance(theme, dict):
                raise GroundingError("Grounded theme entries must be JSON objects")

            category_id = uuid.UUID(str(theme["category_id"]))
            if category_id not in allowed_ids:
                raise GroundingError(
                    f"Grounded theme category_id {category_id} is not in the provided assignments"
                )
            if category_id in seen_ids:
                raise GroundingError(f"Duplicate grounded theme category_id: {category_id}")
            seen_ids.add(category_id)

            salience = float(theme["salience"])
            if not 0.0 <= salience <= 1.0:
                raise GroundingError("Grounded theme salience must be between 0.0 and 1.0")

            fragments_payload = theme.get("fragments")
            if not isinstance(fragments_payload, list):
                raise GroundingError("Grounded theme fragments must be a list")

            fragments = [
                self._parse_fragment(fragment, raw_text=raw_text) for fragment in fragments_payload
            ]
            grounded_themes.append(
                GroundedTheme(
                    category_id=category_id,
                    salience=salience,
                    fragments=fragments,
                )
            )

        return sorted(grounded_themes, key=lambda grounded: grounded.salience, reverse=True)

    def _parse_fragment(self, fragment: Any, *, raw_text: str) -> dict[str, Any]:
        if not isinstance(fragment, dict):
            raise GroundingError("Fragment entries must be JSON objects")

        text = str(fragment["text"])
        start_offset = int(fragment["start_offset"])
        end_offset = int(fragment["end_offset"])
        match_type = str(fragment["match_type"])
        if match_type not in _VALID_MATCH_TYPES:
            raise GroundingError(f"Invalid fragment match_type: {match_type}")

        verified = self._verify_fragment(
            raw_text=raw_text,
            text=text,
            start_offset=start_offset,
            end_offset=end_offset,
        )
        return {
            "text": text,
            "start_offset": start_offset,
            "end_offset": end_offset,
            "match_type": match_type,
            "verified": verified,
        }

    def _verify_fragment(
        self,
        *,
        raw_text: str,
        text: str,
        start_offset: int,
        end_offset: int,
    ) -> bool:
        if start_offset < 0 or end_offset < start_offset or end_offset > len(raw_text):
            return False

        return text == raw_text[start_offset:end_offset]
