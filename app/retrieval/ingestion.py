from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import tiktoken
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.dream import DreamChunk, DreamEntry
from app.retrieval.types import (
    DreamEntryCandidate,
    EmbeddingClient,
    FetchedSourceDocument,
    NormalizedDocument,
    OpenAIEmbeddingClient as SharedOpenAIEmbeddingClient,
    OpenAIEmbeddingHTTPError,
    ResolvedParserProfile,
    SourceConnector,
)
from app.services.segmentation import parse_dream_entry_candidates
from app.shared.config import get_settings
from app.shared.tracing import get_logger, get_tracer

INDEX_SCHEMA_VERSION = "v1"
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIMENSIONS = 1536
MAX_CHUNK_TOKENS = 512
CHUNK_OVERLAP_TOKENS = 50
EMBEDDING_BATCH_SIZE = 100
_TOKENIZER = tiktoken.get_encoding("cl100k_base")
DEFAULT_NORMALIZED_CLIENT_ID = "default"

logger = get_logger(__name__)


@dataclass(frozen=True)
class ChunkDraft:
    chunk_index: int
    chunk_text: str


@dataclass(frozen=True)
class ParsedDocument:
    applied_profile: str
    parse_warnings: list[str]
    review_warnings: list["ReviewableParseWarning"]
    candidates: list[DreamEntryCandidate]


@dataclass(frozen=True)
class ValidatedDreamEntry:
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
class CanonicalDocumentPipeline:
    normalized_document: NormalizedDocument
    parsed_document: ParsedDocument
    validated_entries: list[ValidatedDreamEntry]


@dataclass(frozen=True)
class ReviewableParseWarning:
    code: str
    source_type: str
    external_id: str
    source_path: str
    client_id: str
    applied_profile: str
    warnings: list[str] = field(default_factory=list)


class DreamEntryValidationError(ValueError):
    pass


class EmbeddingServiceError(Exception):
    def __init__(self, status_code: int, dream_id: str | None) -> None:
        self.status_code = status_code
        self.dream_id = dream_id
        super().__init__(
            f"Embedding request failed with status_code={status_code} for dream_id={dream_id}"
        )


class OpenAIEmbeddingClient(SharedOpenAIEmbeddingClient):
    async def embed(self, texts: list[str], *, dream_id: str | None = None) -> list[list[float]]:
        try:
            return await super().embed(
                texts,
                span_attributes={"dream_id": dream_id} if dream_id is not None else None,
                error_context={"dream_id": dream_id} if dream_id is not None else None,
            )
        except OpenAIEmbeddingHTTPError as exc:
            raise EmbeddingServiceError(exc.status_code, exc.error_context.get("dream_id")) from exc


class RagIngestionService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        embedding_client: EmbeddingClient | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._embedding_client = embedding_client or OpenAIEmbeddingClient()

    async def index_dream(self, dream_id: uuid.UUID) -> int:
        tracer = get_tracer(__name__)

        with tracer.start_as_current_span("rag_ingestion.index_dream") as span:
            span.set_attribute("dream_id", str(dream_id))
            span.set_attribute("index_schema_version", INDEX_SCHEMA_VERSION)

            async with self._session_factory() as session:
                dream_entry = await self._load_dream(session, dream_id)
                chunk_drafts = chunk_dream_text(dream_entry.raw_text)
                embeddings = await self._embed_chunks(
                    dream_id, [chunk.chunk_text for chunk in chunk_drafts]
                )

                inserted_rows = 0
                for chunk_draft, embedding in zip(chunk_drafts, embeddings, strict=True):
                    inserted_rows += await self._upsert_chunk(
                        session=session,
                        dream_id=dream_entry.id,
                        chunk_draft=chunk_draft,
                        embedding=embedding,
                    )

                with tracer.start_as_current_span("db.query.rag_ingestion.commit") as commit_span:
                    commit_span.set_attribute("dream_id", str(dream_id))
                    await session.commit()
                return inserted_rows

    async def _load_dream(self, session: AsyncSession, dream_id: uuid.UUID) -> DreamEntry:
        tracer = get_tracer(__name__)

        with tracer.start_as_current_span("db.query.rag_ingestion.load_dream") as span:
            span.set_attribute("dream_id", str(dream_id))
            dream_entry = await session.get(DreamEntry, dream_id)

        if dream_entry is None:
            raise ValueError(f"Dream entry {dream_id} does not exist")

        return dream_entry

    async def _embed_chunks(self, dream_id: uuid.UUID, chunk_texts: list[str]) -> list[list[float]]:
        tracer = get_tracer(__name__)
        embeddings: list[list[float]] = []

        for batch in _batched(chunk_texts, EMBEDDING_BATCH_SIZE):
            with tracer.start_as_current_span("rag_ingestion.embed") as span:
                span.set_attribute("dream_id", str(dream_id))
                span.set_attribute("embedding_model", EMBEDDING_MODEL)
                span.set_attribute("batch_size", len(batch))
                batch_embeddings = await self._embedding_client.embed(batch, dream_id=str(dream_id))

            for embedding in batch_embeddings:
                if len(embedding) != EMBEDDING_DIMENSIONS:
                    raise ValueError(
                        f"Embedding dimension mismatch: expected {EMBEDDING_DIMENSIONS}, got {len(embedding)}"
                    )
            embeddings.extend(batch_embeddings)

        return embeddings

    async def _upsert_chunk(
        self,
        *,
        session: AsyncSession,
        dream_id: uuid.UUID,
        chunk_draft: ChunkDraft,
        embedding: list[float],
    ) -> int:
        tracer = get_tracer(__name__)

        with tracer.start_as_current_span("db.query.rag_ingestion.upsert_chunk") as span:
            span.set_attribute("dream_id", str(dream_id))
            span.set_attribute("chunk_index", chunk_draft.chunk_index)

            statement = (
                insert(DreamChunk)
                .values(
                    dream_id=dream_id,
                    chunk_index=chunk_draft.chunk_index,
                    chunk_text=chunk_draft.chunk_text,
                    embedding=_embedding_to_vector_literal(embedding),
                )
                .on_conflict_do_nothing(
                    index_elements=[DreamChunk.dream_id, DreamChunk.chunk_index]
                )
                .returning(DreamChunk.id)
            )
            result = await session.execute(statement)

        return 1 if result.scalar_one_or_none() is not None else 0


def fetch_source_documents(connector: SourceConnector) -> list[FetchedSourceDocument]:
    return [connector.fetch_document(document) for document in connector.list_documents()]


def normalize_source_document(
    document: FetchedSourceDocument,
    *,
    client_id: str = DEFAULT_NORMALIZED_CLIENT_ID,
    fetched_at: datetime | None = None,
) -> NormalizedDocument:
    normalized_fetched_at = fetched_at or datetime.now(timezone.utc)
    metadata: dict[str, str] = {}
    if document.updated_at is not None:
        metadata["updated_at"] = document.updated_at.isoformat()

    return NormalizedDocument(
        client_id=client_id,
        source_type=document.source_type,
        external_id=document.external_id,
        source_path=document.source_path,
        title=document.title,
        raw_text="\n\n".join(document.raw_contents),
        sections=list(document.raw_contents),
        metadata=metadata,
        fetched_at=normalized_fetched_at,
    )


def fetch_normalized_documents(
    connector: SourceConnector,
    *,
    client_id: str = DEFAULT_NORMALIZED_CLIENT_ID,
    fetched_at: datetime | None = None,
) -> list[NormalizedDocument]:
    return [
        normalize_source_document(document, client_id=client_id, fetched_at=fetched_at)
        for document in fetch_source_documents(connector)
    ]


def parse_normalized_document(
    document: NormalizedDocument,
    *,
    explicit_profile_name: str | None = None,
) -> ParsedDocument:
    resolved_profile, candidates = parse_dream_entry_candidates(
        document,
        explicit_profile_name=explicit_profile_name,
    )
    return _parsed_document(resolved_profile, document, candidates)


def validate_dream_entry_candidates(
    candidates: list[DreamEntryCandidate],
) -> list[ValidatedDreamEntry]:
    validated_entries: list[ValidatedDreamEntry] = []
    seen_content_hashes: set[str] = set()

    for candidate in candidates:
        if not candidate.source_doc_id.strip():
            raise DreamEntryValidationError("Dream entry candidate source_doc_id is required")
        if not candidate.title.strip():
            raise DreamEntryValidationError("Dream entry candidate title is required")
        if not candidate.raw_text.strip():
            raise DreamEntryValidationError("Dream entry candidate raw_text is required")
        if candidate.word_count <= 0:
            raise DreamEntryValidationError("Dream entry candidate word_count must be positive")
        if not candidate.content_hash.strip():
            raise DreamEntryValidationError("Dream entry candidate content_hash is required")
        if candidate.segmentation_confidence not in {"high", "low"}:
            raise DreamEntryValidationError(
                "Dream entry candidate segmentation_confidence must be 'high' or 'low'"
            )
        if candidate.content_hash in seen_content_hashes:
            raise DreamEntryValidationError(
                "Dream entry candidates must not duplicate content_hash values within one document"
            )

        seen_content_hashes.add(candidate.content_hash)
        validated_entries.append(
            ValidatedDreamEntry(
                source_doc_id=candidate.source_doc_id,
                title=candidate.title,
                raw_text=candidate.raw_text,
                word_count=candidate.word_count,
                content_hash=candidate.content_hash,
                date=candidate.date,
                segmentation_confidence=candidate.segmentation_confidence,
                applied_profile=candidate.applied_profile,
                parse_warnings=list(candidate.parse_warnings),
            )
        )

    return validated_entries


def process_source_document(
    document: FetchedSourceDocument,
    *,
    client_id: str = DEFAULT_NORMALIZED_CLIENT_ID,
    fetched_at: datetime | None = None,
    explicit_profile_name: str | None = None,
) -> CanonicalDocumentPipeline:
    tracer = get_tracer(__name__)

    with tracer.start_as_current_span("ingestion.normalize_document"):
        normalized_document = normalize_source_document(
            document,
            client_id=client_id,
            fetched_at=fetched_at,
        )

    resolved_profile_name = explicit_profile_name or get_settings().resolve_operator_parser_profile(
        client_id=normalized_document.client_id,
        source_path=normalized_document.source_path,
    )

    with tracer.start_as_current_span("ingestion.parse_document"):
        parsed_document = parse_normalized_document(
            normalized_document,
            explicit_profile_name=resolved_profile_name,
        )

    logger.info(
        "ingestion.parser_profile_applied",
        applied_profile=parsed_document.applied_profile,
        client_id=normalized_document.client_id,
        external_id=normalized_document.external_id,
        source_path=normalized_document.source_path,
        source_type=normalized_document.source_type,
    )

    with tracer.start_as_current_span("ingestion.validate_candidates"):
        validated_entries = validate_dream_entry_candidates(parsed_document.candidates)

    return CanonicalDocumentPipeline(
        normalized_document=normalized_document,
        parsed_document=parsed_document,
        validated_entries=validated_entries,
    )


def chunk_dream_text(
    raw_text: str,
    *,
    max_chunk_tokens: int = MAX_CHUNK_TOKENS,
    overlap_tokens: int = CHUNK_OVERLAP_TOKENS,
) -> list[ChunkDraft]:
    paragraphs = [paragraph.strip() for paragraph in raw_text.split("\n\n") if paragraph.strip()]
    if not paragraphs:
        return []

    chunks: list[ChunkDraft] = []
    current_paragraphs: list[str] = []
    current_tokens = 0

    for paragraph in paragraphs:
        paragraph_tokens = _token_count(paragraph)
        if current_paragraphs and current_tokens + paragraph_tokens > max_chunk_tokens:
            chunks.append(
                ChunkDraft(
                    chunk_index=len(chunks),
                    chunk_text="\n\n".join(current_paragraphs).strip(),
                )
            )
            overlap_text = _last_overlap_text(chunks[-1].chunk_text, overlap_tokens)
            current_paragraphs = [overlap_text, paragraph] if overlap_text else [paragraph]
            current_tokens = _token_count(" ".join(current_paragraphs))
            continue

        current_paragraphs.append(paragraph)
        current_tokens += paragraph_tokens

    if current_paragraphs:
        chunks.append(
            ChunkDraft(
                chunk_index=len(chunks),
                chunk_text="\n\n".join(current_paragraphs).strip(),
            )
        )

    return chunks


async def fetch_indexed_chunks(
    session: AsyncSession,
    dream_id: uuid.UUID,
) -> list[DreamChunk]:
    tracer = get_tracer(__name__)
    with tracer.start_as_current_span("db.query.rag_ingestion.fetch_indexed_chunks") as span:
        span.set_attribute("dream_id", str(dream_id))
        result = await session.execute(
            select(DreamChunk)
            .where(DreamChunk.dream_id == dream_id)
            .order_by(DreamChunk.chunk_index.asc())
        )
    return list(result.scalars().all())


def _batched(items: list[str], batch_size: int) -> list[list[str]]:
    return [items[index : index + batch_size] for index in range(0, len(items), batch_size)]


def _parsed_document(
    resolved_profile: ResolvedParserProfile,
    document: NormalizedDocument,
    candidates: list[DreamEntryCandidate],
) -> ParsedDocument:
    warning_set = {warning for candidate in candidates for warning in candidate.parse_warnings}
    warning_set.update(resolved_profile.parse_warnings)
    review_warnings = _review_warnings(document, resolved_profile, candidates, sorted(warning_set))
    return ParsedDocument(
        applied_profile=resolved_profile.profile_name,
        parse_warnings=sorted(warning_set),
        review_warnings=review_warnings,
        candidates=candidates,
    )


def _review_warnings(
    document: NormalizedDocument,
    resolved_profile: ResolvedParserProfile,
    candidates: list[DreamEntryCandidate],
    parse_warnings: list[str],
) -> list[ReviewableParseWarning]:
    has_low_confidence_candidate = any(
        candidate.segmentation_confidence == "low" for candidate in candidates
    )
    if not has_low_confidence_candidate:
        return []

    return [
        ReviewableParseWarning(
            code="low_confidence_parse",
            source_type=document.source_type,
            external_id=document.external_id,
            source_path=document.source_path,
            client_id=document.client_id,
            applied_profile=resolved_profile.profile_name,
            warnings=parse_warnings,
        )
    ]


def _embedding_to_vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in embedding) + "]"


def _last_overlap_text(text: str, overlap_tokens: int) -> str:
    token_ids = _TOKENIZER.encode(text)
    if not token_ids or overlap_tokens <= 0:
        return ""
    return _TOKENIZER.decode(token_ids[-overlap_tokens:])


def _token_count(text: str) -> int:
    return len(_TOKENIZER.encode(text))
