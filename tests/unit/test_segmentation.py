from __future__ import annotations

from datetime import date
from datetime import datetime, timezone

from app.retrieval.types import NormalizedDocument
from app.services.segmentation import segment_paragraphs


def _build_document(paragraphs: list[str]) -> NormalizedDocument:
    return NormalizedDocument(
        client_id="default",
        source_type="google_doc",
        external_id="doc-segmentation",
        source_path="documents/doc-segmentation",
        title="Dream Journal",
        raw_text="\n\n".join(paragraphs),
        sections=paragraphs,
        metadata={},
        fetched_at=datetime(2026, 4, 21, tzinfo=timezone.utc),
    )


def test_standard_date_header_segmentation() -> None:
    paragraphs = [
        "2026-01-01",
        "I was in a train station.",
        "Everyone was wearing masks.",
        "2026-01-08",
        "I walked through a flooded library.",
        "2026-01-15",
        "A dog spoke in my grandmother's voice.",
        "2026-01-22",
        "I kept opening doors into the same room.",
        "2026-01-29",
        "The ocean had stairs descending into it.",
    ]

    entries = segment_paragraphs(_build_document(paragraphs))

    assert len(entries) == 5
    assert [entry.date for entry in entries] == [
        date(2026, 1, 1),
        date(2026, 1, 8),
        date(2026, 1, 15),
        date(2026, 1, 22),
        date(2026, 1, 29),
    ]
    assert all(entry.segmentation_confidence == "high" for entry in entries)


def test_no_date_header_fallback() -> None:
    paragraphs = [
        "I was standing at the edge of a lake at dusk.",
        "A voice behind me kept repeating my name.",
    ]

    entries = segment_paragraphs(_build_document(paragraphs))

    assert len(entries) == 1
    assert entries[0].date is None
    assert entries[0].segmentation_confidence == "low"


def test_raw_text_contains_no_secrets(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-value-123456789")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "refresh-token-abc123")

    paragraphs = [
        "I wrote down OPENAI_API_KEY sk-secret-value-123456789 in the dream.",
        "Then someone whispered refresh-token-abc123 into a microphone.",
        "A second voice said api_key=AIzaSyASecretLookingKey000000000.",
    ]

    entries = segment_paragraphs(_build_document(paragraphs))

    assert len(entries) == 1
    assert "sk-secret-value-123456789" not in entries[0].raw_text
    assert "refresh-token-abc123" not in entries[0].raw_text
    assert "AIzaSyASecretLookingKey000000000" not in entries[0].raw_text
