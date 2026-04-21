from __future__ import annotations

import inspect
from datetime import datetime, timezone

import pytest

from app.retrieval.ingestion import normalize_source_document
from app.retrieval.types import FetchedSourceDocument, NormalizedDocument
from app.services.segmentation import segment_paragraphs


def test_normalized_document_requires_canonical_fields() -> None:
    signature = inspect.signature(NormalizedDocument)

    assert list(signature.parameters) == [
        "client_id",
        "source_type",
        "external_id",
        "source_path",
        "title",
        "raw_text",
        "sections",
        "metadata",
        "fetched_at",
    ]
    assert all(
        parameter.default is inspect.Signature.empty for parameter in signature.parameters.values()
    )

    fetched_at = datetime(2026, 4, 21, tzinfo=timezone.utc)
    document = normalize_source_document(
        FetchedSourceDocument(
            source_type="google_doc",
            external_id="doc-123",
            title="Dream Journal",
            source_path="documents/doc-123",
            updated_at=None,
            raw_contents=["First entry", "Second entry"],
        ),
        client_id="default",
        fetched_at=fetched_at,
    )

    assert document == NormalizedDocument(
        client_id="default",
        source_type="google_doc",
        external_id="doc-123",
        source_path="documents/doc-123",
        title="Dream Journal",
        raw_text="First entry\n\nSecond entry",
        sections=["First entry", "Second entry"],
        metadata={},
        fetched_at=fetched_at,
    )


def test_segmentation_rejects_non_normalized_input() -> None:
    with pytest.raises(TypeError, match="NormalizedDocument"):
        segment_paragraphs(["2026-01-01", "A staircase folded into the sea."])  # type: ignore[arg-type]
