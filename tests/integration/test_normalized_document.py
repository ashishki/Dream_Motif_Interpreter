from __future__ import annotations

from datetime import datetime, timezone

from app.retrieval.ingestion import fetch_normalized_documents
from app.retrieval.types import FetchedSourceDocument, SourceDocumentRef


class RecordingConnector:
    def __init__(self) -> None:
        self.calls: list[object] = []
        self._document_ref = SourceDocumentRef(
            source_type="google_doc",
            external_id="doc-456",
            title="Dream Journal",
            source_path="documents/doc-456",
        )
        self._document = FetchedSourceDocument(
            source_type="google_doc",
            external_id="doc-456",
            title="Dream Journal",
            source_path="documents/doc-456",
            updated_at=datetime(2026, 4, 20, 15, 30, tzinfo=timezone.utc),
            raw_contents=[
                "2026-04-20",
                "I crossed a bridge built from mirrors.",
                "The river below was full of lanterns.",
            ],
        )

    def list_documents(self) -> list[SourceDocumentRef]:
        self.calls.append("list_documents")
        return [self._document_ref]

    def fetch_document(self, document: SourceDocumentRef) -> FetchedSourceDocument:
        self.calls.append(("fetch_document", document.external_id))
        return self._document


def test_normalization_is_side_effect_free() -> None:
    connector = RecordingConnector()
    fetched_at = datetime(2026, 4, 21, 9, 0, tzinfo=timezone.utc)

    documents = fetch_normalized_documents(
        connector,
        client_id="default",
        fetched_at=fetched_at,
    )

    assert connector.calls == ["list_documents", ("fetch_document", "doc-456")]
    assert len(documents) == 1
    assert documents[0].raw_text == (
        "2026-04-20\n\nI crossed a bridge built from mirrors.\n\n"
        "The river below was full of lanterns."
    )
    assert documents[0].sections == [
        "2026-04-20",
        "I crossed a bridge built from mirrors.",
        "The river below was full of lanterns.",
    ]
    assert documents[0].metadata == {"updated_at": "2026-04-20T15:30:00+00:00"}
    assert documents[0].fetched_at == fetched_at
