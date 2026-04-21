from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dream import DreamEntry
from app.retrieval.types import (
    DreamEntryCandidate,
    NormalizedDocument,
    ParserProfileMatch,
    ResolvedParserProfile,
)
from app.shared.tracing import get_tracer

_DATE_PATTERNS = (
    ("%Y-%m-%d", re.compile(r"^(?P<value>\d{4}-\d{2}-\d{2})$")),
    ("%d.%m.%Y", re.compile(r"^(?P<value>\d{2}\.\d{2}\.\d{4})$")),
    ("%B %d, %Y", re.compile(r"^(?P<value>[A-Za-z]+ \d{1,2}, \d{4})$")),
)
_SECRET_PATTERNS = (
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bsk-[0-9A-Za-z_-]{16,}\b"),
    re.compile(r"\bya29\.[0-9A-Za-z._-]+\b"),
    re.compile(r"\b(?:oauth|api|access|refresh)[-_ ]?token\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"\bclient[_-]?secret\s*[:=]\s*\S+", re.IGNORECASE),
)
_AUTODETECT_CONFIDENCE_THRESHOLD = 0.6
_HEADING_WORD_LIMIT = 8
_HEADING_CHAR_LIMIT = 80
_HEADING_TERMINAL_PUNCTUATION = (".", "!", "?", ":", ";")


@dataclass(frozen=True)
class _SegmentDraft:
    date: date | None
    title: str
    paragraphs: list[str]
    segmentation_confidence: str
    parse_warnings: list[str]


@dataclass(frozen=True)
class ParserProfile:
    name: str
    detect: Callable[[NormalizedDocument], ParserProfileMatch]
    parse: Callable[[NormalizedDocument], list[DreamEntryCandidate]]


def get_parser_profile_registry() -> dict[str, ParserProfile]:
    return {
        "default": ParserProfile(
            name="default",
            detect=_detect_default_profile,
            parse=_parse_default_profile,
        ),
        "dated_entries": ParserProfile(
            name="dated_entries",
            detect=_detect_dated_entries_profile,
            parse=_parse_dated_entries_profile,
        ),
        "heading_based": ParserProfile(
            name="heading_based",
            detect=_detect_heading_based_profile,
            parse=_parse_heading_based_profile,
        ),
    }


def resolve_parser_profile(
    document: NormalizedDocument,
    *,
    explicit_profile_name: str | None = None,
    confidence_threshold: float = _AUTODETECT_CONFIDENCE_THRESHOLD,
) -> ResolvedParserProfile:
    registry = get_parser_profile_registry()
    profile_name = explicit_profile_name or _explicit_profile_name_from_metadata(document)

    if profile_name is not None:
        if profile_name not in registry:
            raise ValueError(f"Unknown parser profile: {profile_name}")
        return ResolvedParserProfile(profile_name=profile_name, confidence=1.0, parse_warnings=[])

    matches = [
        registry["dated_entries"].detect(document),
        registry["heading_based"].detect(document),
    ]
    best_match = max(matches, key=lambda match: match.confidence)
    if best_match.confidence >= confidence_threshold:
        return ResolvedParserProfile(
            profile_name=best_match.profile_name,
            confidence=best_match.confidence,
            parse_warnings=list(best_match.warnings),
        )

    warning = (
        "Parser autodetect confidence "
        f"{best_match.confidence:.2f} below threshold {confidence_threshold:.2f}; "
        "falling back to default profile."
    )
    return ResolvedParserProfile(
        profile_name="default",
        confidence=best_match.confidence,
        parse_warnings=[*best_match.warnings, warning],
    )


def parse_dream_entry_candidates(
    document: NormalizedDocument,
    *,
    explicit_profile_name: str | None = None,
) -> tuple[ResolvedParserProfile, list[DreamEntryCandidate]]:
    if not isinstance(document, NormalizedDocument):
        raise TypeError("segment_paragraphs requires a NormalizedDocument input")

    resolved_profile = resolve_parser_profile(
        document,
        explicit_profile_name=explicit_profile_name,
    )
    parser_profile = get_parser_profile_registry()[resolved_profile.profile_name]
    candidates = parser_profile.parse(document)
    merged_candidates = [
        DreamEntryCandidate(
            source_doc_id=candidate.source_doc_id,
            title=candidate.title,
            raw_text=candidate.raw_text,
            word_count=candidate.word_count,
            content_hash=candidate.content_hash,
            date=candidate.date,
            segmentation_confidence=candidate.segmentation_confidence,
            applied_profile=resolved_profile.profile_name,
            parse_warnings=[*resolved_profile.parse_warnings, *candidate.parse_warnings],
        )
        for candidate in candidates
    ]
    return resolved_profile, merged_candidates


def segment_paragraphs(
    document: NormalizedDocument,
    *,
    llm_boundary_detector: Callable[[list[_SegmentDraft]], list[_SegmentDraft]] | None = None,
) -> list[DreamEntry]:
    del llm_boundary_detector
    _, candidates = parse_dream_entry_candidates(document)
    return [_candidate_to_dream_entry(candidate) for candidate in candidates]


async def segment_and_store(
    document: NormalizedDocument,
    session: AsyncSession,
    *,
    llm_boundary_detector: Callable[[list[_SegmentDraft]], list[_SegmentDraft]] | None = None,
) -> list[DreamEntry]:
    del llm_boundary_detector
    tracer = get_tracer(__name__)
    entries = segment_paragraphs(document)
    stored_entries: list[DreamEntry] = []

    with tracer.start_as_current_span("segmentation.segment_and_store"):
        for entry in entries:
            values = {
                "source_doc_id": entry.source_doc_id,
                "date": entry.date,
                "title": entry.title,
                "raw_text": entry.raw_text,
                "word_count": entry.word_count,
                "content_hash": entry.content_hash,
                "segmentation_confidence": entry.segmentation_confidence,
                "parser_profile": entry.parser_profile,
                "parse_warnings": entry.parse_warnings,
            }
            statement = (
                insert(DreamEntry)
                .values(**values)
                .on_conflict_do_nothing(index_elements=[DreamEntry.content_hash])
                .returning(DreamEntry)
            )
            with tracer.start_as_current_span("db.query.segmentation.upsert_dream_entry"):
                result = await session.execute(statement)
            stored_entry = result.scalar_one_or_none()
            if stored_entry is not None:
                stored_entries.append(stored_entry)

        with tracer.start_as_current_span("db.query.segmentation.commit"):
            await session.commit()

    return stored_entries


def _detect_default_profile(document: NormalizedDocument) -> ParserProfileMatch:
    del document
    return ParserProfileMatch(profile_name="default", confidence=0.1)


def _detect_dated_entries_profile(document: NormalizedDocument) -> ParserProfileMatch:
    paragraphs = _sanitize_document_sections(document)
    if not paragraphs:
        return ParserProfileMatch(profile_name="dated_entries", confidence=0.0)

    date_headers = sum(1 for paragraph in paragraphs if _parse_date_header(paragraph) is not None)
    confidence = min(1.0, date_headers / max(1, len(paragraphs) / 2))
    warnings: list[str] = []
    if date_headers == 0:
        warnings.append("No date headers detected for dated_entries profile.")
    return ParserProfileMatch(
        profile_name="dated_entries",
        confidence=confidence,
        warnings=warnings,
    )


def _detect_heading_based_profile(document: NormalizedDocument) -> ParserProfileMatch:
    paragraphs = _sanitize_document_sections(document)
    heading_indexes = _heading_indexes(paragraphs)
    heading_count = len(heading_indexes)
    if heading_count == 0:
        return ParserProfileMatch(
            profile_name="heading_based",
            confidence=0.0,
            warnings=["No heading-style boundaries detected for heading_based profile."],
        )

    confidence = min(0.98, 0.45 + (heading_count * 0.15))
    return ParserProfileMatch(
        profile_name="heading_based",
        confidence=confidence,
        warnings=[],
    )


def _parse_default_profile(document: NormalizedDocument) -> list[DreamEntryCandidate]:
    paragraphs = _sanitize_document_sections(document)
    raw_text = "\n\n".join(paragraphs).strip()
    if not raw_text:
        return []

    return [
        DreamEntryCandidate(
            source_doc_id=document.external_id,
            title=_build_title(paragraphs),
            raw_text=raw_text,
            word_count=_word_count(raw_text),
            content_hash=_content_hash(raw_text),
            segmentation_confidence="low",
            applied_profile="default",
        )
    ]


def _parse_dated_entries_profile(document: NormalizedDocument) -> list[DreamEntryCandidate]:
    paragraphs = _sanitize_document_sections(document)
    boundary_indexes: list[tuple[int, date]] = []
    for index, paragraph in enumerate(paragraphs):
        parsed_date = _parse_date_header(paragraph)
        if parsed_date is not None:
            boundary_indexes.append((index, parsed_date))

    if not boundary_indexes:
        return _parse_default_profile(document)

    drafts = _segment_by_date_headers(paragraphs, boundary_indexes)
    return [_draft_to_candidate(document, draft, applied_profile="dated_entries") for draft in drafts]


def _parse_heading_based_profile(document: NormalizedDocument) -> list[DreamEntryCandidate]:
    paragraphs = _sanitize_document_sections(document)
    heading_indexes = _heading_indexes(paragraphs)
    if not heading_indexes:
        return _parse_default_profile(document)

    drafts: list[_SegmentDraft] = []
    for position, start_index in enumerate(heading_indexes):
        end_index = heading_indexes[position + 1] if position + 1 < len(heading_indexes) else len(paragraphs)
        title = paragraphs[start_index].strip()
        body = [paragraph for paragraph in paragraphs[start_index + 1 : end_index] if paragraph.strip()]
        if not body:
            drafts.append(
                _SegmentDraft(
                    date=None,
                    title=title,
                    paragraphs=[title],
                    segmentation_confidence="low",
                    parse_warnings=[f"Heading '{title}' had no body paragraphs; stored as single-paragraph entry."],
                )
            )
            continue
        drafts.append(
            _SegmentDraft(
                date=None,
                title=title,
                paragraphs=body,
                segmentation_confidence="high",
                parse_warnings=[],
            )
        )

    return [_draft_to_candidate(document, draft, applied_profile="heading_based") for draft in drafts]


def _segment_by_date_headers(
    paragraphs: list[str],
    boundary_indexes: list[tuple[int, date]],
) -> list[_SegmentDraft]:
    drafts: list[_SegmentDraft] = []
    for position, (start_index, parsed_date) in enumerate(boundary_indexes):
        end_index = boundary_indexes[position + 1][0] if position + 1 < len(boundary_indexes) else len(paragraphs)
        body = [paragraph for paragraph in paragraphs[start_index + 1 : end_index] if paragraph.strip()]
        if not body:
            continue
        drafts.append(
            _SegmentDraft(
                date=parsed_date,
                title=_build_title(body),
                paragraphs=body,
                segmentation_confidence="high",
                parse_warnings=[],
            )
        )
    return drafts


def _draft_to_candidate(
    document: NormalizedDocument,
    draft: _SegmentDraft,
    *,
    applied_profile: str,
) -> DreamEntryCandidate:
    raw_text = "\n\n".join(draft.paragraphs).strip()
    return DreamEntryCandidate(
        source_doc_id=document.external_id,
        title=draft.title or _build_title(draft.paragraphs),
        raw_text=raw_text,
        word_count=_word_count(raw_text),
        content_hash=_content_hash(raw_text),
        date=draft.date,
        segmentation_confidence=draft.segmentation_confidence,
        applied_profile=applied_profile,
        parse_warnings=list(draft.parse_warnings),
    )


def _candidate_to_dream_entry(candidate: DreamEntryCandidate) -> DreamEntry:
    return DreamEntry(
        source_doc_id=candidate.source_doc_id,
        date=candidate.date,
        title=candidate.title,
        raw_text=candidate.raw_text,
        word_count=candidate.word_count,
        content_hash=candidate.content_hash,
        segmentation_confidence=candidate.segmentation_confidence,
        parser_profile=candidate.applied_profile,
        parse_warnings=list(candidate.parse_warnings),
    )


def _sanitize_document_sections(document: NormalizedDocument) -> list[str]:
    return [
        sanitized
        for paragraph in document.sections
        if paragraph
        for sanitized in [_sanitize_paragraph(paragraph)]
        if sanitized
    ]


def _explicit_profile_name_from_metadata(document: NormalizedDocument) -> str | None:
    profile_name = document.metadata.get("parser_profile")
    return profile_name if isinstance(profile_name, str) and profile_name else None


def _heading_indexes(paragraphs: list[str]) -> list[int]:
    indexes: list[int] = []
    for index, paragraph in enumerate(paragraphs):
        if index == len(paragraphs) - 1:
            continue
        if _is_heading_candidate(paragraph) and not _is_heading_candidate(paragraphs[index + 1]):
            indexes.append(index)
    return indexes


def _is_heading_candidate(paragraph: str) -> bool:
    stripped = paragraph.strip()
    if not stripped:
        return False
    if len(stripped) > _HEADING_CHAR_LIMIT:
        return False
    if stripped.endswith(_HEADING_TERMINAL_PUNCTUATION):
        return False
    if _parse_date_header(stripped) is not None:
        return False
    return _word_count(stripped) <= _HEADING_WORD_LIMIT


def _parse_date_header(paragraph: str) -> date | None:
    value = paragraph.strip()
    for date_format, pattern in _DATE_PATTERNS:
        match = pattern.fullmatch(value)
        if match is None:
            continue
        return datetime.strptime(match.group("value"), date_format).date()
    return None


def _sanitize_paragraph(paragraph: str) -> str:
    sanitized = paragraph

    for env_value in _environment_secret_values():
        sanitized = sanitized.replace(env_value, "[REDACTED]")

    for pattern in _SECRET_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)

    return sanitized.strip()


def _environment_secret_values() -> set[str]:
    values: set[str] = set()
    for key, value in os.environ.items():
        if not value or len(value.strip()) < 4:
            continue
        if key.endswith(("KEY", "TOKEN", "SECRET", "PASSWORD")) or key.startswith(
            ("GOOGLE_", "OPENAI_", "ANTHROPIC_")
        ):
            values.add(value)
    return values


def _build_title(paragraphs: list[str]) -> str:
    first_paragraph = next((paragraph.strip() for paragraph in paragraphs if paragraph.strip()), "")
    return first_paragraph[:120] if first_paragraph else "Untitled Dream Entry"


def _content_hash(raw_text: str) -> str:
    return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


def _word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))
