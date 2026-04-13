from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dream import DreamEntry
from app.shared.config import get_settings
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
_LLM_BOUNDARY_FALLBACK_WORD_THRESHOLD = 1000


@dataclass(frozen=True)
class _SegmentDraft:
    date: date | None
    paragraphs: list[str]
    segmentation_confidence: str


def segment_paragraphs(
    paragraphs: list[str],
    *,
    llm_boundary_detector: Callable[[list[str]], list[_SegmentDraft]] | None = None,
) -> list[DreamEntry]:
    sanitized_paragraphs = [
        sanitized
        for paragraph in paragraphs
        if paragraph
        for sanitized in [_sanitize_paragraph(paragraph)]
        if sanitized
    ]
    drafts = _build_segment_drafts(
        sanitized_paragraphs,
        llm_boundary_detector=llm_boundary_detector,
    )

    entries: list[DreamEntry] = []
    settings = get_settings()
    for draft in drafts:
        raw_text = "\n\n".join(draft.paragraphs).strip()
        if not raw_text:
            continue

        entries.append(
            DreamEntry(
                source_doc_id=settings.GOOGLE_DOC_ID,
                date=draft.date,
                title=_build_title(draft.paragraphs),
                raw_text=raw_text,
                word_count=_word_count(raw_text),
                content_hash=_content_hash(raw_text),
                segmentation_confidence=draft.segmentation_confidence,
            )
        )

    return entries


async def segment_and_store(
    paragraphs: list[str],
    session: AsyncSession,
    *,
    llm_boundary_detector: Callable[[list[str]], list[_SegmentDraft]] | None = None,
) -> list[DreamEntry]:
    tracer = get_tracer(__name__)
    entries = segment_paragraphs(paragraphs, llm_boundary_detector=llm_boundary_detector)
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


def _build_segment_drafts(
    paragraphs: list[str],
    *,
    llm_boundary_detector: Callable[[list[str]], list[_SegmentDraft]] | None = None,
) -> list[_SegmentDraft]:
    boundary_indexes: list[tuple[int, date]] = []
    for index, paragraph in enumerate(paragraphs):
        parsed_date = _parse_date_header(paragraph)
        if parsed_date is not None:
            boundary_indexes.append((index, parsed_date))

    if boundary_indexes:
        return _segment_by_date_headers(paragraphs, boundary_indexes)

    if _word_count(" ".join(paragraphs)) > _LLM_BOUNDARY_FALLBACK_WORD_THRESHOLD:
        detector = llm_boundary_detector or _segment_with_llm_fallback
        return detector(paragraphs)

    return [
        _SegmentDraft(
            date=None,
            paragraphs=paragraphs,
            segmentation_confidence="low",
        )
    ]


def _segment_by_date_headers(
    paragraphs: list[str], boundary_indexes: list[tuple[int, date]]
) -> list[_SegmentDraft]:
    drafts: list[_SegmentDraft] = []
    for position, (start_index, parsed_date) in enumerate(boundary_indexes):
        end_index = (
            boundary_indexes[position + 1][0]
            if position + 1 < len(boundary_indexes)
            else len(paragraphs)
        )
        body = [
            paragraph for paragraph in paragraphs[start_index + 1 : end_index] if paragraph.strip()
        ]
        if not body:
            continue
        drafts.append(
            _SegmentDraft(
                date=parsed_date,
                paragraphs=body,
                segmentation_confidence="high",
            )
        )
    return drafts


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


def _segment_with_llm_fallback(paragraphs: list[str]) -> list[_SegmentDraft]:
    try:
        from app.llm.client import segment_dream_boundaries  # type: ignore[attr-defined]
    except ImportError as exc:
        raise NotImplementedError(
            "LLM segmentation fallback is reserved for T08 when app/llm/client.py exists"
        ) from exc

    return segment_dream_boundaries(paragraphs)
