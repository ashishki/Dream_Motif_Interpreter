from __future__ import annotations

import asyncio
import contextvars
import json
from dataclasses import dataclass, field
from collections.abc import Mapping
from datetime import datetime
from datetime import date
from typing import Any, Protocol
from urllib import error as urllib_error
from urllib import request

from app.shared.config import Settings, get_settings
from app.shared.tracing import get_logger, get_tracer

OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"


@dataclass(frozen=True)
class SourceDocumentRef:
    source_type: str
    external_id: str
    title: str
    source_path: str
    updated_at: datetime | None = None


@dataclass(frozen=True)
class FetchedSourceDocument:
    source_type: str
    external_id: str
    title: str
    source_path: str
    updated_at: datetime | None
    raw_contents: list[str]


@dataclass(frozen=True)
class NormalizedDocument:
    client_id: str
    source_type: str
    external_id: str
    source_path: str
    title: str
    raw_text: str
    sections: list[str]
    metadata: dict[str, Any]
    fetched_at: datetime


@dataclass(frozen=True)
class DreamEntryCandidate:
    source_doc_id: str
    title: str
    raw_text: str
    word_count: int
    content_hash: str
    date: date | None = None
    segmentation_confidence: str = "low"
    applied_profile: str = "default"
    parse_warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ParserProfileMatch:
    profile_name: str
    confidence: float
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResolvedParserProfile:
    profile_name: str
    confidence: float
    parse_warnings: list[str] = field(default_factory=list)


class SourceConnector(Protocol):
    def list_documents(self) -> list[SourceDocumentRef]: ...

    def fetch_document(self, document: SourceDocumentRef) -> FetchedSourceDocument: ...


class EmbeddingClient(Protocol):
    async def embed(
        self,
        texts: list[str],
        *,
        span_attributes: Mapping[str, Any] | None = None,
        error_context: Mapping[str, Any] | None = None,
    ) -> list[list[float]]: ...


class OpenAIEmbeddingHTTPError(Exception):
    def __init__(self, status_code: int, error_context: Mapping[str, Any]) -> None:
        self.status_code = status_code
        self.error_context = dict(error_context)
        super().__init__(f"OpenAI embedding request failed with status_code={status_code}")


class OpenAIEmbeddingClient:
    def __init__(self, *, settings: Settings | None = None) -> None:
        self._settings = settings
        self._logger = get_logger(__name__)
        self._tracer = get_tracer(__name__)

    async def embed(
        self,
        texts: list[str],
        *,
        span_attributes: Mapping[str, Any] | None = None,
        error_context: Mapping[str, Any] | None = None,
    ) -> list[list[float]]:
        if not texts:
            return []

        settings = self._settings or get_settings()
        payload = json.dumps(
            {
                "model": settings.EMBEDDING_MODEL,
                "input": texts,
            }
        ).encode("utf-8")
        http_request = request.Request(
            OPENAI_EMBEDDINGS_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        context = contextvars.copy_context()
        safe_error_context = dict(error_context or {})

        with self._tracer.start_as_current_span("openai.embeddings.request") as span:
            span.set_attribute("openai.input_count", len(texts))
            for key, value in (span_attributes or {}).items():
                span.set_attribute(key, value)

            try:
                raw_response = await asyncio.to_thread(
                    context.run,
                    _send_embedding_request,
                    http_request,
                )
            except urllib_error.HTTPError as exc:
                self._logger.error(
                    "OpenAI embedding request failed",
                    status_code=exc.code,
                    **safe_error_context,
                )
                raise OpenAIEmbeddingHTTPError(exc.code, safe_error_context) from exc

        response = json.loads(raw_response)
        data = sorted(response["data"], key=lambda item: item["index"])
        return [item["embedding"] for item in data]


def _send_embedding_request(http_request: request.Request) -> str:
    with request.urlopen(http_request, timeout=30) as response:  # noqa: S310
        return response.read().decode("utf-8")
