from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.retrieval.ingestion import fetch_source_documents
from app.services.gdocs_client import SingleGoogleDocConnector


def _build_settings(**overrides: str) -> SimpleNamespace:
    defaults = {
        "GOOGLE_CLIENT_ID": "client-id-123",
        "GOOGLE_CLIENT_SECRET": "client-secret-456",
        "GOOGLE_REFRESH_TOKEN": "refresh-token-789",
        "GOOGLE_SERVICE_ACCOUNT_FILE": "",
        "GOOGLE_DOC_ID": "doc-id-abc",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class StubGDocsClient:
    def __init__(self, document: dict[str, object], *, document_id: str = "doc-id-abc") -> None:
        self._document = document
        self._document_id = document_id

    @property
    def document_id(self) -> str:
        return self._document_id

    def fetch_document_resource(self, document_id: str | None = None) -> dict[str, object]:
        assert document_id in {None, self._document_id}
        return self._document


def test_connector_interface_separates_discovery_from_parsing() -> None:
    connector = SingleGoogleDocConnector(
        client=StubGDocsClient(
            {
                "title": "Сны",
                "body": {
                    "content": [
                        {"paragraph": {"elements": [{"textRun": {"content": "Первая запись\n"}}]}},
                        {"paragraph": {"elements": [{"textRun": {"content": "Вторая запись"}}]}},
                    ]
                },
            }
        )
    )

    documents = fetch_source_documents(connector)

    assert len(documents) == 1
    assert documents[0].raw_contents == ["Первая запись", "Вторая запись"]


def test_connector_preserves_provenance_fields() -> None:
    connector = SingleGoogleDocConnector(
        client=StubGDocsClient(
            {
                "title": "Сны",
                "updatedAt": "2026-04-21T12:34:56Z",
                "body": {
                    "content": [
                        {"paragraph": {"elements": [{"textRun": {"content": "Первая запись"}}]}}
                    ]
                },
            },
            document_id="1mq5mwCH_VoFsmdBj4V0MeygjqDjjPxEi-IOO1rHIxHs",
        )
    )

    document_ref = connector.list_documents()[0]
    fetched_document = connector.fetch_document(document_ref)

    expected_updated_at = datetime(2026, 4, 21, 12, 34, 56, tzinfo=timezone.utc)

    assert document_ref.source_type == "google_doc"
    assert document_ref.external_id == "1mq5mwCH_VoFsmdBj4V0MeygjqDjjPxEi-IOO1rHIxHs"
    assert document_ref.title == "Сны"
    assert document_ref.source_path == "documents/1mq5mwCH_VoFsmdBj4V0MeygjqDjjPxEi-IOO1rHIxHs"
    assert document_ref.updated_at == expected_updated_at
    assert fetched_document.source_type == document_ref.source_type
    assert fetched_document.external_id == document_ref.external_id
    assert fetched_document.title == document_ref.title
    assert fetched_document.source_path == document_ref.source_path
    assert fetched_document.updated_at == expected_updated_at
