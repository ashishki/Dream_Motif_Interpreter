from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services.gdocs_client import GDocsClient, SingleGoogleDocConnector


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


def test_single_doc_connector_matches_existing_fetch_behavior() -> None:
    document = {
        "title": "Сны",
        "body": {
            "content": [
                {
                    "paragraph": {
                        "elements": [
                            {"textRun": {"content": "Первая запись\n"}},
                            {"textRun": {"content": ""}},
                        ]
                    }
                },
                {"paragraph": {"elements": [{"textRun": {"content": "\n"}}]}},
                {"paragraph": {"elements": [{"textRun": {"content": "Вторая запись"}}]}},
            ]
        },
    }
    client = GDocsClient(settings=_build_settings())
    mocked_service = Mock()
    mocked_service.documents.return_value.get.return_value.execute.return_value = document

    with patch.object(client, "_build_docs_service", return_value=mocked_service):
        legacy_paragraphs = client.fetch_document()

    connector = SingleGoogleDocConnector(client=client)
    mocked_service = Mock()
    mocked_service.documents.return_value.get.return_value.execute.return_value = document

    with patch.object(client, "_build_docs_service", return_value=mocked_service):
        fetched_document = connector.fetch_document(connector.list_documents()[0])

    assert fetched_document.raw_contents == legacy_paragraphs
