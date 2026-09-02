from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal, TypedDict
from urllib.parse import SplitResult, urlsplit, urlunsplit

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
                    parallels = self._parse_parallels(raw_response, sources)
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
            '{"parallels":[{"domain":"...","label":"...","source_id":"source-1",'
            '"relevance_note":"...","overlap_degree":"full|partial|structural"}]}.\n'
            "Copy source_id exactly from one of the supplied sources. Never invent a source or URL.\n"
            "overlap_degree measures how many elements of the dream motif are present in the parallel:\n"
            "  full     — all or nearly all key elements of the motif match the source material\n"
            "  partial  — some elements match, others are absent or substituted\n"
            "  structural — only the abstract structural pattern matches; specific elements differ\n"
            "Identify only tentative parallels suggested by the source material. "
            "Do not claim certainty or interpretation.\n"
            "Return only the JSON object. No commentary."
        )

    def _build_user_prompt(self, motif_label: str, sources: list[dict[str, str]]) -> str:
        prompt_sources = [
            {**source, "source_id": source_id}
            for source_id, source in _safe_sources_by_id(sources).items()
        ]
        serialized_sources = json.dumps(prompt_sources, ensure_ascii=True)
        return (
            f"Motif label: {motif_label}\n\n"
            "From these external sources, extract structural parallels and suggestions "
            "related to the motif. "
            "Return JSON output only.\n\n"
            f"Sources:\n{serialized_sources}"
        )

    def _parse_parallels(
        self,
        raw_response: str,
        sources: list[dict[str, str]],
    ) -> list[ResearchParallel]:
        from app.llm.theme_extractor import _extract_json_payload

        payload = json.loads(_extract_json_payload(raw_response))
        parallels_raw = payload.get("parallels")
        if not isinstance(parallels_raw, list):
            raise ResearchSynthesisError("LLM response did not include a parallels list")

        safe_sources_by_id = _safe_sources_by_id(sources)
        safe_sources_by_url = {
            normalized_url: source["url"]
            for source in safe_sources_by_id.values()
            if (normalized_url := _normalize_http_url(source["url"])) is not None
        }

        parallels: list[ResearchParallel] = []
        for item in parallels_raw:
            if not isinstance(item, Mapping):
                raise ResearchSynthesisError("Parallel entries must be JSON objects")

            domain = str(item.get("domain", "")).strip()
            label = str(item.get("label", "")).strip()
            source_id = str(item.get("source_id", "")).strip()
            supplied_source_url = str(item.get("source_url", "")).strip()
            relevance_note = str(item.get("relevance_note", "")).strip()
            overlap_degree = str(item.get("overlap_degree", "")).strip().lower()

            if not domain or not label or not relevance_note:
                raise ResearchSynthesisError("Parallel fields must be non-empty")
            if overlap_degree not in _ALLOWED_OVERLAP_DEGREES:
                raise ResearchSynthesisError(
                    "Parallel overlap_degree must be one of: full, partial, structural"
                )

            source_url = _resolve_source_url(
                source_id=source_id,
                supplied_source_url=supplied_source_url,
                safe_sources_by_id=safe_sources_by_id,
                safe_sources_by_url=safe_sources_by_url,
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


def _safe_sources_by_id(sources: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    """Return only browser-safe sources, with stable IDs scoped to this LLM call."""

    safe_sources: dict[str, dict[str, str]] = {}
    for index, source in enumerate(sources, start=1):
        source_url = str(source.get("url", "")).strip()
        if _normalize_http_url(source_url) is None:
            continue
        safe_sources[f"source-{index}"] = {**source, "url": source_url}
    return safe_sources


def _resolve_source_url(
    *,
    source_id: str,
    supplied_source_url: str,
    safe_sources_by_id: dict[str, dict[str, str]],
    safe_sources_by_url: dict[str, str],
) -> str:
    """Resolve an LLM citation to the exact URL returned by the retriever.

    The model never gets to create a clickable URL. It may cite a call-scoped
    source ID (preferred) or repeat a retrieved URL for backwards compatibility.
    In both cases the returned value is taken from the retriever input.
    """

    source_from_id = safe_sources_by_id.get(source_id) if source_id else None
    if source_id and source_from_id is None:
        raise ResearchSynthesisError("Parallel source_id was not present in retrieved sources")

    normalized_supplied_url = (
        _normalize_http_url(supplied_source_url) if supplied_source_url else None
    )
    if supplied_source_url and normalized_supplied_url is None:
        raise ResearchSynthesisError("Parallel source_url must use http or https")

    source_from_url = (
        safe_sources_by_url.get(normalized_supplied_url) if normalized_supplied_url else None
    )
    if supplied_source_url and source_from_url is None:
        raise ResearchSynthesisError("Parallel source_url was not present in retrieved sources")

    if source_from_id is not None:
        retrieved_url = source_from_id["url"]
        if source_from_url is not None:
            normalized_retrieved_url = _normalize_http_url(retrieved_url)
            if normalized_retrieved_url != normalized_supplied_url:
                raise ResearchSynthesisError("Parallel source_id and source_url do not match")
        return retrieved_url

    if source_from_url is not None:
        return source_from_url

    raise ResearchSynthesisError("Parallel must cite a retrieved source")


def _normalize_http_url(value: str) -> str | None:
    """Build a conservative comparison key for an absolute HTTP(S) URL."""

    if not value or any(character.isspace() or ord(character) < 32 for character in value):
        return None
    if "\\" in value:
        return None

    try:
        parsed = urlsplit(value)
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None

        hostname = parsed.hostname.rstrip(".").lower().encode("idna").decode("ascii")
        if not hostname or "%" in hostname:
            return None
        if ":" in hostname:
            hostname = f"[{hostname}]"

        port = parsed.port
        if port is not None and not (
            (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
        ):
            hostname = f"{hostname}:{port}"

        normalized = SplitResult(
            scheme=scheme,
            netloc=hostname,
            path=parsed.path or "/",
            query=parsed.query,
            fragment="",
        )
        return urlunsplit(normalized)
    except (UnicodeError, ValueError):
        return None
